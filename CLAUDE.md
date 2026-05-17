# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is **Phoniebox Version 3** (future3) - an RFID-controlled jukebox for Raspberry Pi. It's a complete rewrite from Version 2, designed to run on Raspberry Pi OS Lite with a plugin-based architecture.

**Target Platform:** Raspberry Pi (all models supported, Pi 2/3/Zero 2 recommended)
**Python Version:** Minimum 3.9
**Main Branch:** `main`

## Active Refactor: Hardening Roadmap

The codebase is undergoing a phased cleanup. The full roadmap (meta-plan) lives at:

`~/.claude/plans/this-project-is-vaguely-wobbly-abelson.md`

**Workflow rule** — each phase runs in a fresh Claude Code conversation. At session start:

```
/plan implement Phase N of ~/.claude/plans/this-project-is-vaguely-wobbly-abelson.md
```

Reference the meta-plan; do not re-derive scope. End-of-phase: open PR, update `MEMORY.md` with anything surprising, update the phase status table below.

### Phase status

| # | Phase | Status | PR / Notes |
|---|-------|--------|------------|
| 0a | SPEC.md | done 2026-05-17 | [#1](https://github.com/azahradka/RPi-Jukebox-RFID/pull/1) |
| 0b | Test scaffolding (Python + React) + CI coverage gate | done 2026-05-17 | [#2](https://github.com/azahradka/RPi-Jukebox-RFID/pull/2) |
| 1 | Critical correctness fixes (7 commits) | done 2026-05-17 | [#3](https://github.com/azahradka/RPi-Jukebox-RFID/pull/3) |
| 2 | Player coordination rewrite | done 2026-05-17 | [#4](https://github.com/azahradka/RPi-Jukebox-RFID/pull/4) |
| 3a | playermpd cleanup + tests | done 2026-05-17 | [#5](https://github.com/azahradka/RPi-Jukebox-RFID/pull/5) |
| 3b | playerpodcast cleanup + tests | in progress | PR open |
| 3c | playerspotify cleanup + tests | done 2026-05-17 | [#6](https://github.com/azahradka/RPi-Jukebox-RFID/pull/6) |
| 4 | Web UI quick wins | done 2026-05-17 | [#8](https://github.com/azahradka/RPi-Jukebox-RFID/pull/8) |
| 5a | Unified RPC contract (single source of truth) | not started | |
| 5b | UI monolith breakups + socket pooling | not started | |
| 6 | Core framework polish (plugs/daemon/cfg validation) | in progress | PR open, awaiting review |
| 7 | Dev workflow (auto-sync, local smoke harness) | not started | |

**Status values:** `not started` → `in progress` → `done YYYY-MM-DD` → `blocked: <reason>`.

**Subagent policy during execution:** `Explore` for finding call sites; `Plan` for unforeseen design decisions mid-phase; `/review` and (for Phases 1 + 5) `/security-review` before opening the PR. Primary implementation stays in the main thread.

## Architecture

### Core Concepts

1. **Plugin System** (`src/jukebox/jukebox/plugs.py`)
   - Components are dynamically loaded Python packages based on configuration
   - Plugins register callable functions via decorators (`@plugs.register`)
   - Failing plugins are ignored during startup - always check logs if functionality is missing
   - Located in `src/jukebox/components/`

2. **RPC (Remote Procedure Call) Server**
   - ZMQ-based server for triggering actions remotely (e.g., from Web UI, GPIO buttons, RFID cards)
   - Only functions registered by plugins are callable
   - RPC commands use format: `package.plugin.method` (or 2-part: `package.plugin`)
   - Aliases exist for common commands (e.g., `play_card` → `player.ctrl.play_card`)
   - Commands in YAML configs: `package`, `plugin`, `method`, `args` (list), `kwargs` (dict)

3. **Publishing Message Queue**
   - Publishes status updates from core application
   - Used by Web UI and external integrations

### Directory Structure

```
src/jukebox/              # Jukebox Core (Python)
├── components/           # Plugin packages
│   ├── playermpd/       # MPD player integration (local audio files)
│   ├── playerpodcast/   # Podcast player (RSS feeds, episode caching)
│   ├── playerspotify/   # Spotify player (spotipy + librespot)
│   ├── rfid/            # RFID reader implementations
│   ├── volume/          # Volume control
│   ├── gpio/            # GPIO buttons
│   └── ...
├── jukebox/             # Core framework
│   ├── plugs.py         # Plugin system
│   ├── daemon.py        # Main daemon
│   ├── cfghandler.py    # Configuration handling
│   └── rpc/             # RPC server
└── run_*.py             # Entry point scripts

src/webapp/              # Web UI (React)
├── src/                 # React source code
├── build/               # Production build output
└── package.json

resources/
├── default-settings/    # Default YAML configs
└── default-services/    # systemd service files

shared/                  # Runtime data (created during installation)
├── settings/            # User configuration
└── logs/                # Application logs
```

## Development & Testing Setup

### Remote Raspberry Pi Test Box

A dedicated Raspberry Pi is available for testing changes:

```bash
# SSH into test box (uses specific key)
ssh -i ~/.ssh/Phoniebox.pub boxadmin@phoniebox.local
```

**CRITICAL: Web App Deployment**
- The Web UI **MUST BE BUILT LOCALLY** on your development machine
- **DO NOT** build on the RPi (insufficient memory/resources)
- Use `rsync` to copy the built files to the RPi

```bash
# Local build process
cd src/webapp

# On macOS/development machine: use npm directly
npm run build

# On Linux/RPi (if needed): use the rebuild script with swap management
# ./run_rebuild.sh -u

# Deploy to RPi (after building locally)
rsync -avz --delete build/ boxadmin@phoniebox.local:/home/boxadmin/RPi-Jukebox-RFID/src/webapp/build/

# Restart nginx on RPi to load new build
ssh -i ~/.ssh/Phoniebox.pub boxadmin@phoniebox.local "sudo systemctl restart nginx.service"
```

### Audio Hardware Configuration

The test box uses the following audio setup:

**Speaker:** Peerless PLS-65F25AL04-04
- 2.5" fullrange driver with aluminum diaphragm
- 4Ω impedance, 25W power rating
- Frequency range: 100-10,000 Hz
- Sensitivity: 84.6 dB (2.83V) / 81.6 dB (1W)

**Amplifier:** Adafruit Speaker Bonnet
- I2S stereo amplifier (MAX98357A chipset)
- 3W per channel, supports 4-8Ω speakers
- Connected via GPIO pins 18, 19, 21 (I2S - cannot be changed)
- Gain configurable: 3dB, 6dB (default), or 9dB via jumper pads
- Uses I2S digital audio (no analog headphone jack noise)

### Audio Stack Architecture

The audio stack has multiple layers. Understanding this is critical for debugging audio issues:

```
MPD → PulseAudio (phoniebox_speaker) → EQ (eq_main) → ALSA (alsa_output) → I2S → Speaker
```

- **ALSA**: Linux kernel audio driver. Only one program can use `hw:0,0` at a time
- **PulseAudio**: Sound server on top of ALSA. Allows multiple programs to share audio
- **MPD**: Music Player Daemon. **Must output through PulseAudio** (`type "pulse"` in mpd.conf), not direct ALSA, to avoid "Device or resource busy" errors
- **MPD config**: `~/.config/mpd/mpd.conf` (NOT `/etc/mpd.conf`). Runs as user `boxadmin`
- **PulseAudio sink chain**: `phoniebox_speaker` (mono remap, volume control) → `eq_main` (10-band EQ) → `alsa_output` (hardware). Only `phoniebox_speaker` should have a non-100% volume; the intermediate sinks should be at 100% passthrough

## Development Commands

### Setup
```bash
# Activate Python virtual environment (REQUIRED for all Python commands)
source .venv/bin/activate

# Install Python dependencies
python -m pip install --no-cache-dir -r requirements.txt

# Install Web UI dependencies (first time or after package.json changes)
cd src/webapp && npm install
```

### `PHONIEBOX_HOME` env var (Phase 6)

`jukebox.utils.paths` resolves all relative configuration paths under
a single anchor instead of the cwd. Resolution order:

1. `$PHONIEBOX_HOME` environment variable (if set).
2. Walk up from the module to the directory containing
   `src/jukebox/` (the production repo root).

Set `PHONIEBOX_HOME` only when running the daemon from a non-standard
location (e.g. tests, alternative installs, a systemd unit that
should be explicit). For a normal checkout — `/home/boxadmin/RPi-Jukebox-RFID`
on the RPi or `~/Documents/Projects/phoniebox/src/RPi-Jukebox-RFID`
on a dev machine — the walk-up fallback handles it.

Example (alternative install root):

```bash
export PHONIEBOX_HOME=/opt/phoniebox
systemctl --user restart jukebox-daemon
```

`cfghandler.load_yaml` and `cfghandler.write_yaml` honour the anchor
automatically. Absolute paths pass through unchanged.

### Running

```bash
# Run Jukebox core (NOT as service, for debugging)
./run_jukebox.sh
# With custom logger:
./run_jukebox.sh --logger path/to/logger.yaml
# Full debug to console:
./run_jukebox.sh -vv

# Run as systemd service (production)
systemctl --user start jukebox-daemon
systemctl --user stop jukebox-daemon
systemctl --user restart jukebox-daemon
systemctl --user status jukebox-daemon

# View service logs
journalctl --user -b -u jukebox-daemon

# Web UI development server (hot reload)
cd src/webapp && npm start

# Build Web UI for production
cd src/webapp && npm run build
# Note: ./run_rebuild.sh -u is for RPi/Linux only (handles swap)
# On macOS, use npm run build directly

# After rebuild, restart nginx (on RPi):
sudo systemctl restart nginx.service
```

### Testing & Linting

```bash
# Run Python tests
./run_pytest.sh
# Run specific test:
./run_pytest.sh test/path/to/test_file.py

# Lint Python code (REQUIRED before commits)
./run_flake8.sh

# Lint Markdown documentation
./run_markdownlint.sh

# Run React tests
cd src/webapp && npm test
```

### Developer Tools

```bash
# RPC command-line tool (interactive mode with autocomplete)
./tools/run_rpc_tool.sh
# Direct command execution:
./tools/run_rpc_tool.sh -c host.shutdown

# Monitor publishing messages (debugging)
./tools/run_publicity_sniffer.sh

# Configure RFID readers
./installation/components/setup_rfid_reader.sh

# Configure audio outputs
./installation/components/setup_configure_audio.sh
```

## Configuration Files

All configuration is in YAML format:

- `shared/settings/jukebox.yaml` - Main jukebox configuration
- `shared/settings/cards.yaml` - RFID card actions
- `shared/settings/logger.yaml` - Logging configuration
- `resources/default-settings/*.yaml` - Default templates

### RPC Command Format in YAML

```yaml
# Full format
package: player
plugin: ctrl
method: play_card
args: [path/to/folder]
kwargs:
  recursive: true

# Using alias
alias: play_card
args: [path/to/folder, true]

# Note: args MUST be a list, even for single argument: args: [value]
```

### RPC Package Naming

**CRITICAL**: Web UI command package names MUST use the module **alias** from `jukebox.yaml`, NOT the directory name.

- **Jukebox config**: `resources/default-settings/jukebox.default.yaml` - defines module aliases
- **Web UI commands**: `src/webapp/src/commands/index.js` - must use the alias
- **Python plugins**: `src/jukebox/components/<directory_name>/` - actual directory names

**Common pitfall**: Using directory name instead of alias causes "Package not registered" errors.

The `modules.named` section in `jukebox.yaml` defines aliases:

```yaml
modules:
  named:
    player_podcast: playerpodcast  # alias: directory_name
```

- **Left side (key)**: RPC package alias - used in Web UI commands
- **Right side (value)**: Python package directory name

Example of CORRECT naming:
```javascript
// src/webapp/src/commands/index.js
play_podcast_episode: {
  _package: 'player_podcast',  // Use the ALIAS from jukebox.yaml
  plugin: 'ctrl',
  method: 'play_podcast_episode',
}
```

```python
# src/jukebox/components/playerpodcast/__init__.py
# Directory is 'playerpodcast' but RPC calls use 'player_podcast' alias
plugs.register(player_ctrl, name='ctrl')
```

**How to verify package names**:
1. Check module aliases: `cat resources/default-settings/jukebox.default.yaml`
2. Look at `modules.named` section - use the LEFT side (alias) in Web UI commands
3. Common aliases:
   - `player` → `playermpd`
   - `player_podcast` → `playerpodcast`
   - `player_spotify` → `playerspotify`
   - `cards` → `rfid.cards`, `rfid` → `rfid.reader`
   - `host` → `hostif.linux`, `gpio` → `gpio.gpioz.plugin`

## Logging & Debugging

```bash
# Application logs (most useful)
shared/logs/app.log        # Full debug log
shared/logs/errors.log     # Errors and warnings only
# Previous run: app.log.1, errors.log.1

# Via web browser
http://ip.of.your.box/logs

# Stop service before debugging
systemctl --user stop jukebox-daemon
./run_jukebox.sh  # Run directly to see console output
```

## Code Style & Conventions

### Python
- Follow PEP 8 (enforced by flake8)
- Max line length: 127 characters
- Use docstrings for all modules, classes, and public functions
- File/folder names: lowercase with underscores (e.g., `my_module.py`, NOT `my-module.py`)

### JavaScript/React
- ESLint config in `src/webapp/package.json`
- Use functional components with hooks

### Git
- Base branches on `main`
- Run `./run_flake8.sh` before committing Python changes
- Run `./run_pytest.sh` to verify tests pass
- Activate git hooks: `cp .githooks/pre-commit .git/hooks/.`
- Folders starting with `scratch*` are git-ignored (use for local experiments)

## Plugin Development

### Registering Plugin Functions

```python
import jukebox.plugs as plugs

# Auto-register function
@plugs.register
def my_function(param):
    pass

# Register with custom name
@plugs.register(name='better_name')
def my_function2(param):
    pass

# Register class with methods
@plugs.register(auto_tag=True)
class MyClass:
    @plugs.tag
    def my_method(self):
        pass
```

### Plugin Structure

Each component in `src/jukebox/components/` is a plugin package:
- Must have `__init__.py`
- Optional `requirements.txt` for additional dependencies
- Register functions to be RPC-callable
- Handle initialization/cleanup via plugin lifecycle hooks

### State Persistence Pattern

Components that need to persist state should use direct JSON reads/writes:

```python
import json
import os

def _load_state(self):
    """Load state from JSON file"""
    if os.path.exists(self.status_file):
        try:
            with open(self.status_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return {}
    return {}

def _save_state(self):
    """Save state to JSON file"""
    try:
        with open(self.status_file, 'w') as f:
            json.dump(self.state, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")
```

**Important:**
- Call `_save_state()` after significant state changes
- Call `_save_state()` in the component's `exit()` method for graceful shutdown
- Keep state files in `shared/settings/` directory
- Use simple, explicit saves rather than complex abstractions

## Dependencies & Services

### Core Services (systemd)
- `jukebox-daemon.service` - Main application
- `mpd.service` - Music Player Daemon (required)
- `pulseaudio.service` - Audio system (required)
- `nginx.service` - Web server for UI

### Key Dependencies
- **Python**: evdev, pulsectl, python-mpd2, ruamel.yaml, pyzmq, spotipy, feedparser
- **System**: MPD (Music Player Daemon), PulseAudio, nginx
- **Node/React**: React 17, Material-UI 5, react-router-dom

## Common Issues

### Web App Build
- **CRITICAL**: Never build Web UI on the Raspberry Pi - always build locally and rsync
  - RPi has insufficient memory for npm build process
  - Build on development machine, then deploy with rsync
- **On macOS/development machine**: Use `npm run build` directly
  - `./run_rebuild.sh` won't work on macOS (it's Linux/RPi-specific)
  - The script checks `/proc/meminfo` and manages swap, which don't exist on macOS
- **On RPi/Linux (if needed)**: Use `./run_rebuild.sh -u` (handles swap automatically)
- **Memory errors on RPi**: The rebuild script manages swap automatically
- **Node heap out of memory**: Handled by run_rebuild.sh script on RPi
- **EOF errors**: Remove `node_modules` and rebuild

### Python
- **Import errors**: Ensure `.venv` is activated
- **Plugin not loading**: Check `shared/logs/app.log` for startup errors
- **PyZMQ**: Requires special compilation on Raspberry Pi (handled by install script)

### Spotify Player (`playerspotify`)
- **Never call the Spotify API from `__init__`** on the MainThread — it blocks RPC server startup. Defer with a background thread or first-use lazy init.
- **Always construct `spotipy.Spotify` with `requests_timeout=10, retries=0`** to prevent indefinite blocking on network hiccups.
- **Do not hold `self.lock` around read-only API calls** (search, playlists, status fetches). spotipy's underlying `requests.Session` is thread-safe for concurrent reads; only playback *mutations* need the lock. Holding the lock on reads serialises everything and stalls the UI.
- **Status publisher must call `_fetch_and_update_status()` directly**, not `playerstatus()` — `playerstatus()` swallows errors and returns the cached status, which hides 429s and prevents back-off.
- **Adaptive polling**: 1s while playing, 5s idle, 30s+ on error; honour the `Retry-After` header on 429.
- **spotipy API gotchas**: `search()` uses `q=` (not `query=`) and `type=` (not `content_type=`).

### Remote Testing
- **SSH key issues**: Ensure using `-i ~/.ssh/Phoniebox.pub` flag
- **Permission denied after rsync**: Check file ownership on RPi - may need `chown boxadmin:boxadmin`
- **Changes not appearing**: Remember to restart nginx after Web UI deployment, jukebox-daemon after Python changes

## Testing Workflow

### Local Development Testing

1. Modify code
2. Run `./run_flake8.sh` (Python changes only)
3. Run `./run_pytest.sh` to verify tests
4. For Web UI: `cd src/webapp && npm test`
5. Stop service: `systemctl --user stop jukebox-daemon`
6. Test manually: `./run_jukebox.sh` (observe console output)
7. Commit changes

### Testing on Remote Raspberry Pi

**All changes use rsync** - no need to commit/push for testing:

1. **Python changes:**
   ```bash
   # Sync Python source to RPi (from repo root)
   rsync -avz --delete src/jukebox/ boxadmin@phoniebox.local:/home/boxadmin/RPi-Jukebox-RFID/src/jukebox/

   # Restart daemon on RPi
   ssh -i ~/.ssh/Phoniebox.pub boxadmin@phoniebox.local "systemctl --user restart jukebox-daemon"

   # Monitor logs
   ssh -i ~/.ssh/Phoniebox.pub boxadmin@phoniebox.local "tail -f ~/RPi-Jukebox-RFID/shared/logs/app.log"
   ```

2. **Web UI changes:**
   ```bash
   # Build LOCALLY (critical - do NOT build on RPi)
   cd src/webapp
   npm run build  # On macOS/development machine
   # Note: Use ./run_rebuild.sh -u only on RPi/Linux if needed

   # Deploy to RPi
   rsync -avz --delete build/ boxadmin@phoniebox.local:/home/boxadmin/RPi-Jukebox-RFID/src/webapp/build/

   # Restart nginx on RPi to load new build
   ssh -i ~/.ssh/Phoniebox.pub boxadmin@phoniebox.local "sudo systemctl restart nginx.service"
   ```

3. **Audio testing:**
   ```bash
   # SSH to test box
   ssh -i ~/.ssh/Phoniebox.pub boxadmin@phoniebox.local

   # Test audio output
   speaker-test -c2 --test=wav -w /usr/share/sounds/alsa/Front_Center.wav

   # Adjust volume if needed
   alsamixer
   ```

## Documentation

- Main docs: `documentation/`
- Builders (users): `documentation/builders/`
- Developers: `documentation/developers/`
- Auto-generated API docs: `documentation/developers/docstring/`
- Use Python docstrings (auto-extracted for API documentation)
