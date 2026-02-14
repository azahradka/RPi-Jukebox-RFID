# Spotify Integration for Phoniebox V3

This guide explains how to set up and use Spotify streaming with your Phoniebox.

## Overview

The Spotify integration allows you to:
- Play Spotify playlists, albums, and tracks via RFID cards
- Control playback using RFID cards or Web App
- Use Spotify alongside MPD (Music Player Daemon)
- Stream music directly from Spotify's catalog

**Architecture:**
- **spotipy**: Python library for Spotify Web API (playback control)
- **librespot**: Lightweight Spotify Connect daemon (audio streaming)
- Runs as a separate player plugin alongside MPD

## Requirements

### Essential
1. **Spotify Premium Account** (required for playback API)
2. **Raspberry Pi** with internet connection
   - Tested on RPi Zero 2 W, RPi 3, RPi 4
   - ARMv6 compatible (Pi Zero W/2W supported)
3. **Phoniebox V3** (future3/develop branch)

### Recommended
- Working audio output (speakers or headphones)
- At least 100 MB free disk space
- Stable WiFi connection

## Setup Steps

### 1. Create Spotify Developer App

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Log in with your Spotify account
3. Click **Create app**
4. Fill in the details:
   - **App name**: `Phoniebox`
   - **App description**: `RFID-controlled music player`
   - **Redirect URI**: `http://127.0.0.1:8888/callback`
   - **Website**: Leave blank or use your project URL
   - **API/SDKs**: Select "Web API"
5. Click **Save**
6. On the app page, click **Settings**
7. Copy your **Client ID** and **Client Secret** (you'll need these later)

### 2. Install Dependencies

SSH to your Raspberry Pi:

```bash
ssh boxadmin@phoniebox.local
cd ~/RPi-Jukebox-RFID
```

Install Python packages:

```bash
source .venv/bin/activate
pip install --no-cache-dir -r requirements.txt
```

This installs `spotipy` and `pycryptodome` needed for Spotify integration.

Install librespot (Spotify Connect daemon):

```bash
# Download librespot for ARMv6 (Pi Zero) or ARMv7 (Pi 3/4)
# For Pi Zero 2 W:
wget https://github.com/librespot-org/librespot/releases/download/v0.4.2/librespot-linux-armhf-raspberry_pi.tar.gz

# For Pi 3/4:
# wget https://github.com/librespot-org/librespot/releases/download/v0.4.2/librespot-linux-armhf.tar.gz

# Extract and install
tar -xvf librespot-linux-armhf-raspberry_pi.tar.gz
sudo mv librespot /usr/local/bin/
sudo chmod +x /usr/local/bin/librespot
rm librespot-linux-armhf-raspberry_pi.tar.gz

# Verify installation
librespot --version
```

### 3. Configure Jukebox

Edit the jukebox configuration:

```bash
nano shared/settings/jukebox.yaml
```

Find or add the `playerspotify` section:

```yaml
playerspotify:
  client_id: 'YOUR_CLIENT_ID_HERE'
  client_secret: 'YOUR_CLIENT_SECRET_HERE'
  redirect_uri: 'http://127.0.0.1:8888/callback'
  credential_file: ../../shared/settings/spotify_credentials.json
  status_file: ../../shared/settings/spotify_player_status.json
  device_name: 'Phoniebox'
  second_swipe_action:
    alias: toggle
  cache_enabled: true
  cache_path: ../../shared/cache/spotify/
```

Replace `YOUR_CLIENT_ID_HERE` and `YOUR_CLIENT_SECRET_HERE` with values from step 1.

**Important:** Ensure the `modules.named` section includes:

```yaml
modules:
  named:
    # ... other modules ...
    player: playermpd
    player_spotify: playerspotify  # Add this line
```

Save and exit (Ctrl+O, Enter, Ctrl+X).

### 4. Set Up Librespot Service

Copy the systemd service file:

```bash
mkdir -p ~/.config/systemd/user
cp resources/default-settings/librespot.service ~/.config/systemd/user/
```

Edit if needed (optional):

```bash
nano ~/.config/systemd/user/librespot.service
```

You can customize:
- Device name (`--name "Phoniebox"`)
- Bitrate (`--bitrate 160`) - 96/160/320 kbps
- Initial volume (`--initial-volume 70`)

Enable and start the service:

```bash
systemctl --user daemon-reload
systemctl --user enable librespot.service
systemctl --user start librespot.service
```

Check status:

```bash
systemctl --user status librespot.service
```

You should see "active (running)". If not, check logs:

```bash
journalctl --user -u librespot.service -n 50
```

### 5. Authenticate with Spotify

Open the Phoniebox Web UI in your browser (e.g., `http://phoniebox.local` or
`http://<pi-ip>`). Navigate to **Settings** and find the **Spotify** card.

1. Click **Connect Spotify** — a new tab opens with the Spotify login page
2. Log in and approve the permissions
3. Spotify redirects to `http://127.0.0.1:8888/callback?code=...` — because
   nothing is listening on your local machine, the browser shows an error page
   ("This site can't be reached"). **This is expected.**
4. Copy the **full URL** from your browser's address bar
5. Switch back to the Phoniebox Settings tab and paste the URL into the text
   field
6. Click **Complete Connection**

The Phoniebox backend exchanges the code for an access token and stores
encrypted credentials. You should see the status change to "Connected".

**Alternative — CLI auth tool (advanced):**

If you prefer to authenticate from the command line you can still use SSH port
forwarding and the standalone script:

```bash
# Terminal 1: SSH tunnel
ssh -L 8888:127.0.0.1:8888 -i ~/.ssh/Phoniebox.pub boxadmin@phoniebox.local

# Terminal 2: run auth script on the Pi
ssh -i ~/.ssh/Phoniebox.pub boxadmin@phoniebox.local
cd ~/RPi-Jukebox-RFID
source .venv/bin/activate
python tools/spotify_auth_setup.py
```

**Troubleshooting authentication:**
- Verify the redirect URI in the Spotify Developer Dashboard exactly matches
  `http://127.0.0.1:8888/callback`
- Check that you're using a Spotify Premium account
- Make sure you copy the **entire** URL from the address bar (it starts with
  `http://127.0.0.1:8888/callback?code=`)

### 6. Restart Jukebox

Stop the jukebox service:

```bash
systemctl --user stop jukebox-daemon
```

Start with debug logging to verify:

```bash
cd ~/RPi-Jukebox-RFID
./run_jukebox.sh -vv
```

Look for these log messages:
- `Loading plugin: playerspotify`
- `Spotify player initialized (device: Phoniebox)`
- `Spotify player plugin registered as 'playerspotify.ctrl'`
- `Found Spotify device: Phoniebox (device_id)`

If everything looks good, press Ctrl+C and start the service normally:

```bash
systemctl --user start jukebox-daemon
```

### 7. Verify Device Visibility

Open the Spotify app on your phone or computer:
1. Start playing any song
2. Tap the "Connect to a device" icon (speaker with waves)
3. Look for "Phoniebox" in the device list
4. If you see it, the setup is successful!

## Usage

### RPC Commands

Test Spotify playback using the RPC tool:

```bash
cd ~/RPi-Jukebox-RFID
./tools/run_rpc_tool.sh
```

Try these commands:

```
# Play a single track
> playerspotify.ctrl.play_content spotify:track:11dFghVXANMlKmJXsNCbNl

# Play a playlist
> playerspotify.ctrl.play_content spotify:playlist:37i9dQZF1DXcBWIGoYBM5M

# Play an album
> playerspotify.ctrl.play_content spotify:album:6DEjYFkNZh67HP7R9PSZvv

# Control playback
> playerspotify.ctrl.toggle
> playerspotify.ctrl.next
> playerspotify.ctrl.prev
> playerspotify.ctrl.shuffle toggle
> playerspotify.ctrl.repeat toggle
```

Or use aliases:

```
> play_spotify_content spotify:track:11dFghVXANMlKmJXsNCbNl
> spotify_toggle
> spotify_next
> spotify_prev
```

### RFID Cards

Edit your card database:

```bash
nano shared/settings/cards.yaml
```

Add Spotify content to cards:

```yaml
# Play Spotify playlist
'1234567890':
  alias: play_spotify_content
  args: ['spotify:playlist:37i9dQZF1DXcBWIGoYBM5M']

# Play Spotify album
'0987654321':
  package: playerspotify
  plugin: ctrl
  method: play_content
  args: ['spotify:album:6DEjYFkNZh67HP7R9PSZvv']

# Control card (toggle playback)
'1111111111':
  alias: spotify_toggle

# Mix with MPD
'2222222222':
  alias: play_card
  args: ['Children/Disney']
```

**Second Swipe Behavior:**
When you swipe the same Spotify card twice:
- Default: Toggle play/pause
- Configurable in jukebox.yaml: `toggle`, `play`, `skip`, `rewind`, `replay`, `none`

### Getting Spotify URIs

**Method 1: Spotify App (Desktop)**
1. Right-click any playlist/album/track
2. Select "Share" → "Copy Spotify URI"
3. Paste into cards.yaml: `spotify:playlist:xxxxx`

**Method 2: Spotify App (Mobile)**
1. Tap "..." on any content
2. Select "Share"
3. Copy link (URL format)
4. Convert to URI format:
   - `https://open.spotify.com/playlist/xxxxx` → `spotify:playlist:xxxxx`
   - `https://open.spotify.com/album/xxxxx` → `spotify:album:xxxxx`

**Method 3: Web Player**
1. Open [Spotify Web Player](https://open.spotify.com/)
2. Copy URL from browser address bar
3. Extract ID and format as: `spotify:type:ID`

## Coexistence with MPD

The Spotify player runs alongside MPD without conflict:

- **MPD cards**: Use `play_card` alias or `package: playermpd`
- **Spotify cards**: Use `play_spotify_content` alias or `package: playerspotify`
- Both players accessible simultaneously
- Card swipe switches between players

Example mixed configuration:

```yaml
# MPD card
'card_mpd_1':
  alias: play_card
  args: ['Rock/ClassicRock']

# Spotify card
'card_spotify_1':
  alias: play_spotify_content
  args: ['spotify:playlist:37i9dQZF1DXcBWIGoYBM5M']

# Control cards work with currently active player
'card_toggle':
  alias: toggle  # Works with both!

'card_next':
  alias: next_song  # Works with both!
```

## Troubleshooting

### Device Not Found

**Symptom:** "Spotify device 'Phoniebox' not found" in logs

**Solutions:**
1. Check librespot is running:
   ```bash
   systemctl --user status librespot.service
   ```

2. Verify device appears in Spotify app (see "Connect to device")

3. Restart librespot:
   ```bash
   systemctl --user restart librespot.service
   ```

4. Check device name matches:
   ```bash
   # In jukebox.yaml
   device_name: 'Phoniebox'

   # In librespot.service
   --name "Phoniebox"
   ```

### Token Expired / Authentication Errors

**Symptom:** "Token expired" or "Authentication failed" in logs

**Solutions:**
1. Tokens auto-refresh, but if stuck, re-authenticate:
   ```bash
   python tools/spotify_auth_setup.py
   ```

2. Clear old credentials:
   ```bash
   rm shared/settings/spotify_credentials.json
   python tools/spotify_auth_setup.py
   ```

### Premium Account Required

**Symptom:** "Premium account required" or API 403 errors

**Solution:** Spotify's playback API only works with Premium accounts. Free accounts cannot control playback programmatically. Upgrade to Spotify Premium.

### Playback Stuttering / Poor Quality

**Solutions:**
1. Reduce bitrate in librespot.service:
   ```ini
   --bitrate 96  # Lower quality, less bandwidth
   ```

2. Check WiFi signal strength:
   ```bash
   iwconfig wlan0
   ```

3. Reduce cache usage:
   ```yaml
   # In jukebox.yaml
   cache_enabled: false
   ```

### Card Not Triggering Spotify

**Checklist:**
1. Verify card database syntax:
   ```bash
   cd ~/RPi-Jukebox-RFID
   python -c "import yaml; yaml.safe_load(open('shared/settings/cards.yaml'))"
   ```

2. Check Spotify URI is valid (test with RPC tool first)

3. Restart jukebox:
   ```bash
   systemctl --user restart jukebox-daemon
   ```

4. Watch logs:
   ```bash
   journalctl --user -u jukebox-daemon -f
   ```

### Memory Issues (Pi Zero 2 W)

**Symptom:** Jukebox crashes or becomes unresponsive

**Solutions:**
1. Disable cache:
   ```yaml
   cache_enabled: false
   ```

2. Reduce librespot memory usage:
   ```ini
   # In librespot.service [Service] section
   MemoryMax=100M
   CPUQuota=50%
   ```

3. Use lower bitrate (96 or 160 kbps)

4. Close other services:
   ```bash
   sudo systemctl stop bluetooth
   ```

### Network Connection Lost

**Symptom:** Playback stops when WiFi disconnects

**Solutions:**
1. Configure fallback to MPD (optional):
   ```yaml
   playerspotify:
     fallback_action:
       enabled: true
       package: playermpd
       plugin: ctrl
       method: play_card
       args: ['Offline/Favorites']
   ```

2. Disable WiFi power management:
   ```yaml
   host:
     wlan_power:
       disable_power_down: true
       card: wlan0
   ```

## Advanced Configuration

### Custom Second Swipe Actions

Change what happens when you swipe a card twice:

```yaml
playerspotify:
  second_swipe_action:
    alias: skip  # Options: toggle, play, skip, rewind, replay, none
```

### Cache Configuration

```yaml
playerspotify:
  cache_enabled: true
  cache_path: ../../shared/cache/spotify/
```

Cache stores resolved playlists/albums for 1 hour to reduce API calls.

### Multiple Spotify Accounts

To switch accounts:

```bash
# Clear existing credentials
rm shared/settings/spotify_credentials.json

# Re-authenticate with different account
python tools/spotify_auth_setup.py

# Restart jukebox
systemctl --user restart jukebox-daemon
```

## Logs and Debugging

**View jukebox logs:**
```bash
journalctl --user -u jukebox-daemon -f
```

**View librespot logs:**
```bash
journalctl --user -u librespot.service -f
```

**Debug mode (verbose logging):**
```bash
systemctl --user stop jukebox-daemon
cd ~/RPi-Jukebox-RFID
./run_jukebox.sh -vv  # Info logging
./run_jukebox.sh -vvv # Debug logging
```

**Test API connection:**
```bash
source .venv/bin/activate
python -c "
import spotipy
from components.playerspotify.spotify_auth import SpotifyAuthManager
auth = SpotifyAuthManager('client_id', 'client_secret', 'redirect_uri', 'cred_file')
sp = spotipy.Spotify(auth=auth.get_access_token())
print(sp.current_user())
"
```

## Uninstalling

To remove Spotify integration:

1. Stop services:
   ```bash
   systemctl --user stop jukebox-daemon
   systemctl --user stop librespot.service
   systemctl --user disable librespot.service
   ```

2. Remove credentials:
   ```bash
   rm shared/settings/spotify_credentials.json
   rm shared/settings/spotify_player_status.json
   rm -rf shared/cache/spotify/
   ```

3. Remove from jukebox.yaml:
   ```yaml
   modules:
     named:
       # player_spotify: playerspotify  # Comment out or remove
   ```

4. Remove librespot:
   ```bash
   sudo rm /usr/local/bin/librespot
   rm ~/.config/systemd/user/librespot.service
   systemctl --user daemon-reload
   ```

5. Restart jukebox:
   ```bash
   systemctl --user start jukebox-daemon
   ```

## FAQ

**Q: Can I use Spotify Free?**
A: No, Spotify Premium is required for playback control via API.

**Q: Does this work offline?**
A: No, Spotify requires internet connection. Use MPD for offline music.

**Q: Can I play Spotify and MPD simultaneously?**
A: No, only one player can be active at a time. Swipe a card to switch.

**Q: How much bandwidth does it use?**
A: ~2 MB per minute at 160 kbps, ~4 MB per minute at 320 kbps.

**Q: Can I use multiple Spotify devices?**
A: Yes, but only one can play at a time. Playback switches to the last activated device.

**Q: Does it support podcasts?**
A: Not yet. Only music content (tracks, albums, playlists).

**Q: Can I control volume?**
A: Yes, use standard volume commands (they work with both MPD and Spotify):
```bash
> set_volume 50
> change_volume 5
```

**Q: Does it work on Raspberry Pi 5?**
A: Yes, follow the same steps. Use the ARMv7 librespot binary.

## Support

- **Issues:** [GitHub Issues](https://github.com/azahradka/RPi-Jukebox-RFID/issues)
- **Discussions:** [GitHub Discussions](https://github.com/MiczFlor/RPi-Jukebox-RFID/discussions)
- **Documentation:** [Phoniebox Docs](https://github.com/MiczFlor/RPi-Jukebox-RFID/wiki)

## Credits

- **Spotify Web API:** [spotipy](https://github.com/spotipy-dev/spotipy)
- **Librespot:** [librespot-org](https://github.com/librespot-org/librespot)
- **Phoniebox Project:** [MiczFlor/RPi-Jukebox-RFID](https://github.com/MiczFlor/RPi-Jukebox-RFID)
