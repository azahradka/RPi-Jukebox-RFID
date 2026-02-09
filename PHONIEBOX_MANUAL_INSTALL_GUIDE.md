# Phoniebox Manual Installation Guide for Raspberry Pi Zero 2 W

**Last Updated:** 2026-02-02
**Target Hardware:** Raspberry Pi Zero 2 W (416 MB RAM)
**OS:** Raspberry Pi OS Lite (Debian 13 Trixie, 32-bit)
**Installation Source:** Fork `azahradka/RPi-Jukebox-RFID`, branch `future3/develop`

---

## Why Manual Installation?

The automated installer (`install-jukebox.sh`) has several issues:
- ❌ SSH configuration bugs (IPQoS errors) that break SSH after reboot
- ❌ Non-resumable (can't continue after failures)
- ❌ Service check failures (e.g., triggerhappy)
- ❌ Attempts to build Web App on-device (impossible on Pi Zero 2 W with 416 MB RAM)

**Manual installation gives you:**
- ✅ Complete control over each step
- ✅ Ability to troubleshoot and fix issues as they arise
- ✅ No SSH lockouts
- ✅ Pre-built Web App (built on development machine)
- ✅ ~45 minutes total time (faster than debugging the installer)

---

## Prerequisites

### Hardware Setup

**PN532 RFID Reader (I2C Mode):**
- Jumpers: SEL0=ON, SEL1=OFF
- Connections:
  - 5V → Pin 4
  - GND → Pin 6
  - SDA → GPIO 2 (Pin 3)
  - SCL → GPIO 3 (Pin 5)

**Adafruit MAX98357 I2S Amplifier:**
- Connections:
  - VIN → 5V (Pin 2/4)
  - GND → GND (Pin 6/9)
  - BCLK → GPIO 18 (Pin 12)
  - LRC → GPIO 19 (Pin 35)
  - DIN → GPIO 21 (Pin 40)

**Power:** Anker power bank (no monitoring capability)

### Software Prerequisites

**On Development Machine (macOS/Linux):**
- Node.js 18+ and npm (for building Web App)
- SSH client
- rsync

**On Raspberry Pi:**
- Fresh Raspberry Pi OS Lite (32-bit, Debian 13 Trixie)
- SSH enabled (via Raspberry Pi Imager settings)
- WiFi configured
- Static hostname: `phoniebox.local`

---

## Installation Overview

**Total Time:** ~45 minutes

1. **Prepare Development Machine** (5 min) - Build Web App locally
2. **Prepare Raspberry Pi** (10 min) - System updates, enable I2C
3. **Install Jukebox Core** (15 min) - Python, dependencies, clone repo
4. **Install Components** (10 min) - MPD, Samba, nginx
5. **Configure Hardware** (5 min) - RFID, Audio, timers
6. **Deploy and Test** (5 min) - Web App, services, verification

---

## Phase 1: Prepare Development Machine

### 1.1 Build Web App Locally

**CRITICAL:** The Pi Zero 2 W cannot build the Web App due to insufficient RAM (416 MB). Always build on your development machine.

```bash
# On your development machine
cd ~/Documents/Projects/phoniebox/src/RPi-Jukebox-RFID/src/webapp

# Install dependencies (first time only)
npm install

# Build production bundle
npm run build

# Verify build output
ls -lh build/
# Should show ~4.8 MB with index.html, static/, etc.
```

**Build output location:** `build/` directory
**Size:** ~4.8 MB
**Build time:** 3-5 minutes

---

## Phase 2: Prepare Raspberry Pi

### 2.1 Initial Setup

Connect via SSH:
```bash
ssh -i ~/.ssh/Phoniebox.pub boxadmin@phoniebox.local
```

### 2.2 System Updates

```bash
sudo apt-get update
sudo apt-get upgrade -y

# Install ALL required packages upfront
sudo apt-get install -y git i2c-tools swig liblgpio-dev pulseaudio
```

**Packages explained:**
- `git` - Clone repository
- `i2c-tools` - I2C hardware detection
- `swig` - Build wrapper generator (required for lgpio)
- `liblgpio-dev` - GPIO library development files
- `pulseaudio` - Audio system (required for jukebox volume control)

**Time:** ~5 minutes on Pi Zero 2 W

### 2.3 Enable I2C for PN532

```bash
# Enable I2C interface
sudo raspi-config nonint do_i2c 0

# Reboot to apply
sudo reboot
```

Wait ~60 seconds for reboot, then reconnect:
```bash
ssh -i ~/.ssh/Phoniebox.pub boxadmin@phoniebox.local

# Verify PN532 is detected at address 0x24
sudo i2cdetect -y 1
```

**Expected output:** Device at address `24`

### 2.4 Configure Boot Settings

Determine boot config location:
```bash
if [ -f /boot/firmware/config.txt ]; then
    BOOT_CONFIG=/boot/firmware/config.txt
else
    BOOT_CONFIG=/boot/config.txt
fi
echo "Boot config: $BOOT_CONFIG"
```

**Disable onboard audio** (for I2S):
```bash
sudo sed -i 's/^dtparam=audio=on/dtparam=audio=off/' $BOOT_CONFIG

# Verify
grep "dtparam=audio" $BOOT_CONFIG
# Should show: dtparam=audio=off
```

**Add I2S overlay for MAX98357** (do this AFTER jukebox is working):
```bash
# DON'T DO THIS YET - save for Phase 5
# echo "dtoverlay=hifiberry-dac" | sudo tee -a $BOOT_CONFIG
```

**Boot optimizations:**
```bash
echo -e "\n## Jukebox Boot Config\ndisable_splash=1" | sudo tee -a $BOOT_CONFIG
```

---

## Phase 3: Install Jukebox Core

### 3.1 Clone Repository

```bash
cd ~
git clone https://github.com/azahradka/RPi-Jukebox-RFID.git
cd RPi-Jukebox-RFID
git checkout future3/develop

# Verify branch
git branch
git log --oneline -5
```

### 3.2 Create Python Virtual Environment

```bash
cd ~/RPi-Jukebox-RFID

# Install Python venv
sudo apt-get install -y python3-venv python3-pip

# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip
```

### 3.3 Install Python Dependencies

**IMPORTANT:** Ensure system dependencies are installed (from Phase 2.2: `swig`, `liblgpio-dev`)

```bash
# Still in virtual environment
cd ~/RPi-Jukebox-RFID

# Verify build dependencies are present
which swig || echo "ERROR: swig not installed! Run: sudo apt-get install -y swig liblgpio-dev"

# Install requirements
pip install -r requirements.txt

# This takes ~10-15 minutes on Pi Zero 2 W
# Watch for errors - all packages should install successfully
```

**Common packages installed:**
- pyzmq (RPC communication) - **builds from source, takes ~5 min**
- paho-mqtt (MQTT support)
- python-mpd2 (MPD control)
- gpiozero (GPIO control)
- lgpio (GPIO library) - **requires swig and liblgpio-dev**
- evdev (input device handling)
- pulsectl (audio control)
- And many more...

**Common build issues:**
- If `lgpio` fails with "command 'swig' failed" → Install `swig`: `sudo apt-get install -y swig`
- If `lgpio` fails with "cannot find -llgpio" → Install `liblgpio-dev`: `sudo apt-get install -y liblgpio-dev`
- If installation fails, check the error output and install missing system packages

### 3.3.1 Verify Critical Packages

After installation completes, verify pyzmq (required for RPC):

```bash
# Still in virtual environment
python -c "import zmq; print(f'pyzmq {zmq.pyzmq_version()} - ZMQ {zmq.zmq_version()}')"
# Should output: pyzmq 27.1.0 - ZMQ 4.3.5 (or similar)
```

If pyzmq is missing, install manually:
```bash
pip install pyzmq
# This will compile from source (~5 minutes on Pi Zero 2 W)
```

### 3.3.2 Install pyzmq with WebSocket Support

**⚠️ CRITICAL:** pyzmq requires special compilation to support WebSocket protocol. Do NOT skip this step.

The standard `pip install pyzmq` installs a pre-compiled wheel without WebSocket support, causing the jukebox to crash with `zmq.error.ZMQError: Protocol not supported`.

**Option A: Pre-built libzmq (RECOMMENDED for Pi Zero 2 W - 2 minutes):**

```bash
# Still in virtual environment
cd ~

# Create temporary directory
mkdir -p ~/libzmq
cd ~/libzmq

# Detect architecture and map to download format
UNAME_ARCH=$(uname -m)
if [ "$UNAME_ARCH" = "armv7l" ]; then
    ARCH="armv7"
elif [ "$UNAME_ARCH" = "armv6l" ]; then
    ARCH="armv6"
elif [ "$UNAME_ARCH" = "aarch64" ]; then
    ARCH="arm64"
else
    ARCH="$UNAME_ARCH"
fi
echo "Architecture: $ARCH (detected: $UNAME_ARCH)"

# Download pre-built libzmq 4.3.5 with DRAFT API
wget -q https://github.com/pabera/libzmq/releases/download/v4.3.5/libzmq5-${ARCH}-4.3.5.tar.gz -O libzmq.tar.gz

# Extract to /usr/local
tar -xzf libzmq.tar.gz
sudo rsync -a ./* /usr/local/

# Verify installation
ls -la /usr/local/lib/libzmq*
# Should show libzmq.so.5.2.5

# Uninstall existing pyzmq (if present)
pip uninstall -y pyzmq

# Build pyzmq with DRAFT API support
ZMQ_PREFIX=/usr/local ZMQ_DRAFT_API=1 pip install -v 'pyzmq<26' --no-binary pyzmq
# This takes ~5 minutes on Pi Zero 2 W

# Clean up
cd ~
rm -rf ~/libzmq
```

**Option B: Build libzmq from source (20-30 minutes on Pi Zero 2 W):**

```bash
# Still in virtual environment
cd ~

# Install build dependencies
sudo apt-get install -y build-essential libtool autoconf automake pkg-config

# Create temporary directory
mkdir -p ~/libzmq
cd ~/libzmq

# Download libzmq 4.3.5 source
wget -q https://github.com/zeromq/libzmq/releases/download/v4.3.5/zeromq-4.3.5.tar.gz
tar -xzf zeromq-4.3.5.tar.gz
cd zeromq-4.3.5

# Configure with DRAFT API enabled
./configure --prefix=/usr/local --enable-drafts --disable-Werror

# Build (use single job on Pi Zero 2 W to avoid OOM)
make -j1
sudo make install

# Update library cache
sudo ldconfig

# Uninstall existing pyzmq (if present)
cd ~
pip uninstall -y pyzmq

# Build pyzmq with DRAFT API support
ZMQ_PREFIX=/usr/local ZMQ_DRAFT_API=1 pip install -v 'pyzmq<26' --no-binary pyzmq

# Clean up
rm -rf ~/libzmq
```

**Verify Installation:**

```bash
# Check libzmq version
python -c "import zmq; print(f'libzmq: {zmq.zmq_version()}')"
# Should output: libzmq: 4.3.5

# Check pyzmq version
python -c "import zmq; print(f'pyzmq: {zmq.pyzmq_version()}')"
# Should output: pyzmq: 25.x.x (NOT 27.x.x)

# Check DRAFT API is enabled
python -c "import zmq; print(f'DRAFT API: {zmq.DRAFT_API}')"
# Should output: DRAFT API: True

# Test WebSocket binding (CRITICAL TEST)
python -c "
import zmq
ctx = zmq.Context()
sock = ctx.socket(zmq.REP)
try:
    sock.bind('ws://127.0.0.1:9999')
    print('✅ WebSocket protocol SUPPORTED')
    sock.unbind('ws://127.0.0.1:9999')
except zmq.ZMQError as e:
    print(f'❌ WebSocket protocol NOT supported: {e}')
finally:
    sock.close()
    ctx.term()
"
```

**Expected output:**
```
libzmq: 4.3.5
pyzmq: 25.1.2
DRAFT API: True
✅ WebSocket protocol SUPPORTED
```

**If WebSocket test fails:**
- Verify libzmq is 4.3.5: `ldconfig -p | grep libzmq`
- Verify DRAFT API is True: `python -c "import zmq; print(zmq.DRAFT_API)"`
- Uninstall pyzmq and rebuild: `pip uninstall pyzmq && ZMQ_PREFIX=/usr/local ZMQ_DRAFT_API=1 pip install -v 'pyzmq<26' --no-binary pyzmq`

### 3.4 Install Jukebox Package

```bash
# Still in virtual environment
cd ~/RPi-Jukebox-RFID/src/jukebox

# Install jukebox as editable package
pip install -e .
```

### 3.5 Copy Default Configuration Files

The jukebox requires configuration files in `shared/settings/`. The automated installer copies these from `resources/default-settings/` — we must do it manually:

```bash
cd ~/RPi-Jukebox-RFID

# Create settings and logs directories
mkdir -p shared/settings shared/logs

# Copy logger config (REQUIRED - without this, logs are not written to files)
cp resources/default-settings/logger.default.yaml shared/settings/logger.yaml

# Copy main jukebox config (if not already present)
[ -f shared/settings/jukebox.yaml ] || cp resources/default-settings/jukebox.default.yaml shared/settings/jukebox.yaml
```

**Why this matters:** Without `logger.yaml`, the daemon falls back to console-only logging — `shared/logs/app.log` and `errors.log` will be empty. Logs will only appear in `journalctl`.

---

## Phase 4: Install Components

### 4.1 Install MPD (Music Player Daemon)

```bash
sudo apt-get install -y mpd mpc

# Stop MPD system service (we'll use user service)
sudo systemctl stop mpd
sudo systemctl disable mpd

# Create user MPD directory
mkdir -p ~/.config/mpd
mkdir -p ~/.mpd

# Copy default MPD config
cp ~/RPi-Jukebox-RFID/resources/default-settings/mpd.default.conf ~/.config/mpd/mpd.conf

# Update paths in config
sed -i "s|%%USER_HOME%%|$HOME|g" ~/.config/mpd/mpd.conf

# Create MPD directories
mkdir -p ~/RPi-Jukebox-RFID/shared/audiofolders
mkdir -p ~/.mpd/playlists

# Disable volume normalization (preserves audio quality)
sed -i 's/^volume_normalization[[:space:]]*"yes"/volume_normalization\t\t"no"/' ~/.config/mpd/mpd.conf

# Note: Audio output will be configured in Phase 5 after I2S DAC is enabled
# For now, MPD will start with default output

# Enable and start user MPD service
systemctl --user enable mpd
systemctl --user start mpd

# Verify MPD is running
systemctl --user status mpd
mpc version
```

### 4.2 Install Samba (File Sharing)

**Optional but recommended** - makes it easy to upload music files.

```bash
sudo apt-get install -y samba samba-common-bin

# Backup original config
sudo cp /etc/samba/smb.conf /etc/samba/smb.conf.backup

# Add Phoniebox share
sudo tee -a /etc/samba/smb.conf > /dev/null << 'EOF'

[phoniebox]
   comment = Phoniebox Shared Folder
   path = /home/boxadmin/RPi-Jukebox-RFID/shared
   browseable = yes
   writeable = yes
   create mask = 0775
   directory mask = 0775
   public = no
   valid users = boxadmin
EOF

# Set Samba password (use your SSH password)
sudo smbpasswd -a boxadmin

# Restart Samba
sudo systemctl restart smbd

# Verify
sudo systemctl status smbd
```

**Access from macOS:**
```
smb://boxadmin@phoniebox.local/phoniebox
```

### 4.3 Install and Configure nginx

```bash
sudo apt-get install -y nginx

# Copy Phoniebox nginx config
sudo cp ~/RPi-Jukebox-RFID/resources/default-settings/nginx.default /etc/nginx/sites-available/default

# Replace placeholders
sudo sed -i "s|%%INSTALLATION_PATH%%|$HOME/RPi-Jukebox-RFID|g" /etc/nginx/sites-available/default

# Test nginx config
sudo nginx -t

# Restart nginx
sudo systemctl restart nginx

# Verify
sudo systemctl status nginx
```

### 4.4 Deploy Pre-Built Web App

**From your development machine:**
```bash
# Transfer pre-built Web App to Pi
rsync -avz --delete \
  -e "ssh -i ~/.ssh/Phoniebox.pub" \
  ~/Documents/Projects/phoniebox/src/RPi-Jukebox-RFID/src/webapp/build/ \
  boxadmin@phoniebox.local:~/RPi-Jukebox-RFID/src/webapp/build/
```

**On the Pi, verify:**
```bash
ls -la ~/RPi-Jukebox-RFID/src/webapp/build/
du -sh ~/RPi-Jukebox-RFID/src/webapp/build/
# Should show ~4.8 MB
```

**Fix directory permissions for nginx:**

nginx needs execute permission on the home directory to access the Web App files.

```bash
# On the Pi:
chmod +x ~
chmod -R a+rX ~/RPi-Jukebox-RFID/src/webapp/build/

# Verify permissions
ls -ld ~ ~/RPi-Jukebox-RFID/src/webapp/build/
# Home dir should show: drwx--x--x
# Build dir should show: drwxr-xr-x
```

**Test nginx access:**
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost/
# Should return: 200
```

If you get 403 Forbidden, permissions are incorrect. Re-run the chmod commands above.

---

## Phase 5: Configure Hardware and Features

### 5.1 Configure RFID Reader (PN532)

```bash
cd ~/RPi-Jukebox-RFID
source .venv/bin/activate

# Run RFID configuration tool
./installation/components/setup_rfid_reader.sh
```

**Configuration prompts:**
- Reader type: **PN532 (I2C)**
- I2C address: **0x24** (auto-detected)
- Same-ID delay: **1.0** seconds
- Place/remove mode: **YES**
- Add another reader: **NO**

**Verify config created:**
```bash
cat ~/RPi-Jukebox-RFID/shared/settings/rfid.yaml
```

### 5.2 Configure Audio (After Jukebox is Working)

**IMPORTANT:** Do NOT add the I2S overlay until the jukebox is running and SSH is stable. Adding it too early can cause boot issues.

#### Step 1: Get Jukebox Working First
Skip this section for now and come back after Phase 6 (Deploy and Test).

#### Step 2: Add I2S Overlay (Once Jukebox is Confirmed Working)

```bash
# Determine boot config location
if [ -f /boot/firmware/config.txt ]; then
    BOOT_CONFIG=/boot/firmware/config.txt
else
    BOOT_CONFIG=/boot/config.txt
fi

# Add I2S overlay
echo "dtoverlay=hifiberry-dac" | sudo tee -a $BOOT_CONFIG

# CRITICAL: Verify SSH will survive reboot
ls /boot/firmware/ssh || sudo touch /boot/firmware/ssh

# Reboot
sudo reboot
```

Wait ~90 seconds, then reconnect:
```bash
ssh -i ~/.ssh/Phoniebox.pub boxadmin@phoniebox.local

# Verify I2S DAC is available
aplay -l
# Should show: snd_rpi_hifiberry_dac or similar
```

#### Step 3: Configure MPD Audio Output (PulseAudio)

**IMPORTANT:** MPD must output through PulseAudio, not directly to ALSA. The jukebox
uses PulseAudio for volume control and the startup jingle. If MPD uses direct ALSA
(`hw:0,0`), it will conflict with PulseAudio — only one program can hold the ALSA
device at a time, causing "Device or resource busy" errors.

```bash
# Stop services
systemctl --user stop jukebox-daemon
systemctl --user stop mpd

# Backup MPD config
cp ~/.config/mpd/mpd.conf ~/.config/mpd/mpd.conf.backup

# Configure PulseAudio output for MPD
cat >> ~/.config/mpd/mpd.conf << 'EOF'

# PulseAudio output - routes through PulseAudio so volume control,
# startup jingle, and MPD can all share the audio device
audio_output {
    type            "pulse"
    name            "PulseAudio Output"
}
EOF

# Restart services
systemctl --user start mpd
systemctl --user start jukebox-daemon

# Verify MPD output is configured
mpc outputs
# Should show: PulseAudio Output (enabled)
```

**Test audio output:**
```bash
# Test through MPD
mpc clear
mpc add http://stream.radioparadise.com/mp3-128
mpc volume 60
mpc play
```

**If audio is very quiet**, the intermediate PulseAudio sinks may have low default
volumes. Only the `phoniebox_speaker` sink should control volume — set the filter
sinks to 100% passthrough:
```bash
pactl set-sink-volume alsa_output.platform-soc_sound.stereo-fallback 100%
pactl set-sink-volume eq_main 100%
# These settings are saved by module-device-restore and persist across reboots
```

**Why PulseAudio instead of direct ALSA?**
- PulseAudio already holds the ALSA device for volume control and the startup jingle
- ALSA `hw:0,0` only allows one program at a time — MPD and PulseAudio can't share it
- Routing MPD through PulseAudio eliminates "Device or resource busy" errors
- Volume normalization is disabled to preserve dynamic range

### 5.3 Configure Timers and Battery Monitor

Edit jukebox configuration:
```bash
nano ~/RPi-Jukebox-RFID/shared/settings/jukebox.yaml
```

**Verify timers are enabled** (should already be present):
```yaml
modules:
  named:
    timers: timers
```

**Verify battery monitor is NOT present** (we don't have monitoring capability):
```yaml
# Should NOT have a battery_monitor section
# If present, remove it or set enabled: false
```

**Adjust timer settings if needed:**
```yaml
timers:
  idle_shutdown:
    timeout_sec: 0  # 0 = disabled, or set seconds for auto-shutdown
  shutdown:
    default_timeout_sec: 3600  # 1 hour
  stop_player:
    default_timeout_sec: 3600  # 1 hour
```

Save and exit (Ctrl+X, Y, Enter).

---

## Phase 6: Deploy and Test

### 6.1 Create Systemd User Service

```bash
mkdir -p ~/.config/systemd/user

# Create service file
cat > ~/.config/systemd/user/jukebox-daemon.service << 'EOF'
[Unit]
Description=Jukebox Daemon
After=network.target sound.target

[Service]
Type=simple
WorkingDirectory=/home/boxadmin/RPi-Jukebox-RFID/src/jukebox
ExecStart=/home/boxadmin/RPi-Jukebox-RFID/.venv/bin/python run_jukebox.py
Restart=on-failure
RestartSec=10s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF

# Reload systemd
systemctl --user daemon-reload

# Enable service to start on boot
systemctl --user enable jukebox-daemon

# Enable lingering (so user services start at boot)
sudo loginctl enable-linger boxadmin
```

### 6.1.1 Verify WebSocket Protocol Support

Before starting the jukebox, verify that pyzmq was built with WebSocket support:

```bash
cd ~/RPi-Jukebox-RFID
source .venv/bin/activate

python -c "
import zmq
ctx = zmq.Context()
sock = ctx.socket(zmq.REP)
try:
    sock.bind('ws://127.0.0.1:9999')
    print('✅ WebSocket protocol SUPPORTED - jukebox will start correctly')
    sock.unbind('ws://127.0.0.1:9999')
except zmq.ZMQError as e:
    print(f'❌ ERROR: WebSocket NOT supported: {e}')
    print('Go back to Section 3.3.2 and rebuild pyzmq with DRAFT API')
finally:
    sock.close()
    ctx.term()
"
```

**If you see the ✅ message, proceed to start the service.**

**If you see the ❌ error:**
1. Return to Section 3.3.2
2. Follow the pyzmq installation steps carefully
3. Verify all verification tests pass
4. Return here and test again

### 6.2 Start Jukebox Service

```bash
# Start the service
systemctl --user start jukebox-daemon

# Check status
systemctl --user status jukebox-daemon

# View logs
journalctl --user -u jukebox-daemon -f
```

**Expected in logs:**
- Jukebox starting
- Loading components
- RFID reader initialized
- RPC server started on ports 5555/5556
- Publishing server started on ports 5557/5558

**If errors occur:**
- Check logs carefully: `journalctl --user -u jukebox-daemon -n 100`
- Verify all paths in jukebox.yaml are correct
- Ensure virtual environment is activated when running manually

### 6.3 Test Web App Access

**From your browser:**
```
http://phoniebox.local
```

or

```
http://10.0.0.46
```

**Expected:**
- Web App loads successfully
- Status shows "Ready" or "Idle"
- Volume controls work
- Library tab shows (empty until music is uploaded)

### 6.4 Test RFID Reader

```bash
# Watch for card swipes in logs
journalctl --user -u jukebox-daemon -f

# Place RFID card on reader
# Should see: Card detected: [UID]
```

### 6.5 Upload Music and Test Playback

**From macOS (via Samba):**
```bash
# Connect to share
open smb://boxadmin@phoniebox.local/phoniebox

# Navigate to audiofolders/
# Drag and drop music folders
```

**Or via rsync:**
```bash
rsync -avz --progress \
  -e "ssh -i ~/.ssh/Phoniebox.pub" \
  /path/to/music/folder/ \
  boxadmin@phoniebox.local:~/RPi-Jukebox-RFID/shared/audiofolders/
```

**On Pi, update MPD database:**
```bash
mpc update
# Wait for update to complete
mpc stats
# Should show your music files
```

### 6.6 Register RFID Card

**Via Web App:**
1. Open Web App: `http://phoniebox.local`
2. Navigate to "Cards" section
3. Click "Register New Card"
4. Place card on reader
5. Card UID appears automatically
6. Select action: "Play folder"
7. Choose music folder
8. Save

**Test playback:**
1. Place card on reader
2. Music should start playing
3. Remove card (if place/remove mode enabled)
4. Music should pause

---

## Verification Checklist

After installation, verify:

### System
- [ ] SSH access works: `ssh -i ~/.ssh/Phoniebox.pub boxadmin@phoniebox.local`
- [ ] Git repository present: `ls ~/RPi-Jukebox-RFID`
- [ ] On correct branch: `cd ~/RPi-Jukebox-RFID && git branch` shows `* future3/develop`
- [ ] Virtual environment exists: `ls ~/RPi-Jukebox-RFID/.venv`

### Services
- [ ] Jukebox daemon running: `systemctl --user status jukebox-daemon`
- [ ] MPD running: `systemctl --user status mpd`
- [ ] nginx running: `sudo systemctl status nginx`
- [ ] Services auto-start: `systemctl --user is-enabled jukebox-daemon mpd`

### Hardware
- [ ] I2C enabled: `lsmod | grep i2c_bcm2835`
- [ ] PN532 detected: `sudo i2cdetect -y 1` shows device at 0x24
- [ ] I2S DAC loaded (if configured): `aplay -l` shows HiFiBerry DAC
- [ ] Audio output working: `speaker-test -t wav -c 2 -l 1` produces sound

### Configuration
- [ ] Logger config exists: `cat ~/RPi-Jukebox-RFID/shared/settings/logger.yaml`
- [ ] Log files are being written: `ls -lh ~/RPi-Jukebox-RFID/shared/logs/` (app.log should be non-zero)
- [ ] RFID config exists: `cat ~/RPi-Jukebox-RFID/shared/settings/rfid.yaml`
- [ ] Jukebox config exists: `cat ~/RPi-Jukebox-RFID/shared/settings/jukebox.yaml`
- [ ] Timers enabled in jukebox.yaml
- [ ] Battery monitor not configured in jukebox.yaml

### Functionality
- [ ] Web App accessible: `http://phoniebox.local`
- [ ] RPC working: `cd ~/RPi-Jukebox-RFID && source .venv/bin/activate && ./tools/run_rpc_tool.sh -c host.shutdown` responds (don't execute!)
- [ ] Publishing working: `./tools/run_publicity_sniffer.sh` shows messages
- [ ] RFID card detected: Place card, check logs show UID
- [ ] Music playback: Upload music, register card, test playback
- [ ] Volume control: Adjust volume via Web App
- [ ] Place/remove mode: Card placement plays, removal pauses

---

## Troubleshooting

### SSH Connection Issues

**Problem:** SSH refuses connection after reboot

**Solution:**
1. Power off Pi, remove SD card
2. Insert SD card in development machine
3. Check if `/Volumes/bootfs/ssh` file exists
4. If missing, create it: `touch /Volumes/bootfs/ssh`
5. Eject SD card, reinsert in Pi, power on

**Prevention:**
- Never modify `/etc/ssh/sshd_config` manually
- Always verify SSH works before rebooting
- Keep a backup of working config

### I2C Device Not Detected

**Problem:** `i2cdetect -y 1` shows no device at 0x24

**Solution:**
1. Verify I2C is enabled: `sudo raspi-config nonint do_i2c 0`
2. Check wiring: SDA→Pin 3, SCL→Pin 5, VCC→Pin 4, GND→Pin 6
3. Verify PN532 jumpers: SEL0=ON, SEL1=OFF
4. Reboot: `sudo reboot`
5. Check kernel modules: `lsmod | grep i2c`

### Python Package Build Failures

**Problem:** `pip install -r requirements.txt` fails with build errors for `lgpio`

**Solutions:**

**If error mentions "command 'swig' failed":**
```bash
sudo apt-get install -y swig
pip install -r requirements.txt  # Retry installation
```

**If error mentions "cannot find -llgpio":**
```bash
sudo apt-get install -y liblgpio-dev
pip install -r requirements.txt  # Retry installation
```

**If pyzmq is missing:**
```bash
source .venv/bin/activate
pip install pyzmq
# This compiles from source (~5 minutes on Pi Zero 2 W)
```

### Jukebox Won't Start - ZMQ WebSocket Error

**Problem:** `systemctl --user status jukebox-daemon` shows failed, logs show:
```
zmq.error.ZMQError: Protocol not supported (addr='ws://*:5556')
```

**Root Cause:** pyzmq was not built with DRAFT API support (WebSocket requires it)

**Solution:**

```bash
cd ~/RPi-Jukebox-RFID
source .venv/bin/activate

# Check current pyzmq configuration
python -c "import zmq; print(f'pyzmq: {zmq.pyzmq_version()}, libzmq: {zmq.zmq_version()}, DRAFT: {zmq.DRAFT_API}')"

# If DRAFT API is False, rebuild pyzmq:
pip uninstall -y pyzmq

# Download pre-built libzmq with drafts
mkdir -p ~/libzmq && cd ~/libzmq
UNAME_ARCH=$(uname -m)
case "$UNAME_ARCH" in
    armv7l) ARCH="armv7" ;;
    armv6l) ARCH="armv6" ;;
    aarch64) ARCH="arm64" ;;
    *) ARCH="$UNAME_ARCH" ;;
esac
wget -q https://github.com/pabera/libzmq/releases/download/v4.3.5/libzmq5-${ARCH}-4.3.5.tar.gz -O libzmq.tar.gz
tar -xzf libzmq.tar.gz
sudo rsync -a ./* /usr/local/
cd ~ && rm -rf ~/libzmq

# Rebuild pyzmq with DRAFT API
ZMQ_PREFIX=/usr/local ZMQ_DRAFT_API=1 pip install -v 'pyzmq<26' --no-binary pyzmq

# Verify WebSocket support
python -c "import zmq; ctx = zmq.Context(); sock = ctx.socket(zmq.REP); sock.bind('ws://127.0.0.1:9999'); print('✅ WebSocket works'); sock.close(); ctx.term()"

# Restart jukebox
systemctl --user restart jukebox-daemon
```

### MPD Audio Output Error

**Problem:** MPD errors with "Failed to open ALSA device" or audio output issues

**Solutions:**

1. **Verify I2S DAC is detected:**
```bash
aplay -l
# Should show: snd_rpi_hifiberry_dac at card 0
```

2. **Check MPD output configuration:**
```bash
mpc outputs
# Should show: HifiBerry DAC (enabled)
```

3. **If output is missing, add direct ALSA configuration:**
```bash
cat >> ~/.config/mpd/mpd.conf << 'EOF'

audio_output {
    type            "alsa"
    name            "HifiBerry DAC"
    device          "hw:0,0"
    mixer_type      "software"
}
EOF

systemctl --user restart mpd
```

4. **Test audio directly:**
```bash
# Test hardware
speaker-test -c 2 -t wav -D hw:0,0 -l 1

# Test through MPD
mpc clear
mpc add http://stream.radioparadise.com/mp3-128
mpc volume 60
mpc play
```

### Web App Returns 403 Forbidden

**Problem:** Accessing `http://phoniebox.local` returns 403 Forbidden

**Solution:** Fix directory permissions for nginx:

```bash
chmod +x ~
chmod -R a+rX ~/RPi-Jukebox-RFID/src/webapp/build/

# Test
curl -s -o /dev/null -w "%{http_code}" http://localhost/
# Should return: 200
```

If still not working, check nginx error log:
```bash
sudo tail -20 /var/log/nginx/error.log
```

### No Audio Output

**Problem:** No sound from MAX98357 amplifier

**Solution:**
1. Verify I2S overlay loaded: `grep hifiberry /boot/firmware/config.txt`
2. Check ALSA devices: `aplay -l`
3. Verify wiring: BCLK→Pin 12, LRC→Pin 35, DIN→Pin 40
4. Test with speaker-test: `speaker-test -t wav -c 2 -l 1`
5. Check PulseAudio sinks: `pactl list sinks short`
6. Verify jukebox.yaml has correct sink configured

### Jukebox Service Won't Start

**Problem:** `systemctl --user status jukebox-daemon` shows failed

**Solution:**
1. Check logs: `journalctl --user -u jukebox-daemon -n 100`
2. Test manual start: `cd ~/RPi-Jukebox-RFID && source .venv/bin/activate && ./run_jukebox.sh -vv`
3. Verify paths in jukebox.yaml are correct
4. Check Python dependencies: `pip list | grep pyzmq`
5. Verify config files exist in `~/RPi-Jukebox-RFID/shared/settings/`

### Web App Not Loading

**Problem:** `http://phoniebox.local` doesn't load

**Solution:**
1. Check nginx status: `sudo systemctl status nginx`
2. Test nginx config: `sudo nginx -t`
3. Verify Web App files: `ls ~/RPi-Jukebox-RFID/src/webapp/build/index.html`
4. Check nginx logs: `sudo tail -50 /var/log/nginx/error.log`
5. Try IP address instead: `http://10.0.0.46`

### RFID Card Not Detected

**Problem:** Card placement doesn't show in logs

**Solution:**
1. Verify PN532 detected: `sudo i2cdetect -y 1`
2. Check RFID config: `cat ~/RPi-Jukebox-RFID/shared/settings/rfid.yaml`
3. Watch jukebox logs: `journalctl --user -u jukebox-daemon -f`
4. Test RFID component manually: Run RPC tool with RFID commands
5. Verify RFID reader component is loaded in jukebox.yaml

---

## Post-Installation

### Regular Maintenance

**Update Phoniebox:**
```bash
cd ~/RPi-Jukebox-RFID
git pull origin future3/develop
systemctl --user restart jukebox-daemon
```

**Update System:**
```bash
sudo apt-get update
sudo apt-get upgrade -y
```

**Backup Configuration:**
```bash
# Backup settings folder
tar -czf ~/phoniebox-settings-$(date +%Y%m%d).tar.gz \
  ~/RPi-Jukebox-RFID/shared/settings/
```

### Performance Tuning

**For Pi Zero 2 W (limited RAM):**
- Disable Web App cover art if performance issues: `show_covers: false` in jukebox.yaml
- Limit MPD cache size in `~/.config/mpd/mpd.conf`
- Close unused SSH sessions
- Disable unnecessary services

### Security

**Change default passwords:**
```bash
# SSH password
passwd

# Samba password
sudo smbpasswd boxadmin
```

**Update regularly:**
```bash
sudo apt-get update && sudo apt-get upgrade -y
```

---

## Resources

### Documentation
- Installation Guide: `~/RPi-Jukebox-RFID/documentation/builders/installation.md`
- Developer Docs: `~/RPi-Jukebox-RFID/documentation/developers/`
- Component Docs: `~/RPi-Jukebox-RFID/src/jukebox/components/[component]/README.md`

### Development Commands
- Run Jukebox (debug): `./run_jukebox.sh -vv`
- RPC Tool: `./tools/run_rpc_tool.sh`
- Publishing Monitor: `./tools/run_publicity_sniffer.sh`
- Test Suite: `./run_pytest.sh`
- Linting: `./run_flake8.sh`

### Configuration Files
- Main: `~/RPi-Jukebox-RFID/shared/settings/jukebox.yaml`
- RFID: `~/RPi-Jukebox-RFID/shared/settings/rfid.yaml`
- Cards: `~/RPi-Jukebox-RFID/shared/settings/cards.yaml`
- Logging: `~/RPi-Jukebox-RFID/shared/settings/logger.yaml`
- MPD: `~/.config/mpd/mpd.conf`

### Log Files
- Jukebox: `journalctl --user -u jukebox-daemon`
- MPD: `~/.mpd/mpd.log`
- nginx: `/var/log/nginx/error.log`

---

## Estimated Timeline

| Phase | Time | Description |
|-------|------|-------------|
| 1. Prepare Dev Machine | 5 min | Build Web App locally |
| 2. Prepare Raspberry Pi | 10 min | System updates, I2C, boot config |
| 3. Install Jukebox Core | 15 min | Clone repo, Python env, dependencies |
| 4. Install Components | 10 min | MPD, Samba, nginx, Web App |
| 5. Configure Hardware | 5 min | RFID, audio (later), timers |
| 6. Deploy and Test | 5 min | Services, Web App, verification |
| **Total** | **~50 min** | **Complete installation** |

*Note: Times are for Raspberry Pi Zero 2 W. Faster models (Pi 3/4/5) will be quicker.*

---

## Success Criteria

Installation is complete when:
- ✅ Web App accessible at `http://phoniebox.local`
- ✅ RFID card placement detected in logs
- ✅ Music plays when card is placed
- ✅ Volume controls work via Web App
- ✅ All services auto-start on boot
- ✅ SSH connection is stable after reboots

---

**Last tested:** 2026-02-02
**Fork:** azahradka/RPi-Jukebox-RFID
**Branch:** future3/develop
**Commit:** cd455384
