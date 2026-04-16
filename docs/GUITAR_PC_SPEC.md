# Guitar Station PC — Dedicated Linux Build

A small, quiet Linux box that lives next to the guitar amp/setup. Runs Slopsmith
(and potentially other guitar tools) with the Rocksmith USB adapter for note detection.

## What It Needs To Do

- Run Slopsmith via Docker (FastAPI + vgmstream + ffmpeg)
- Run the note detection plugin (Python + aubio + sounddevice)
- Capture audio from Rocksmith USB Guitar Adapter (USB 2.0, 48kHz mono)
- Play back song audio through headphones or speakers
- Display the note highway in a browser (1080p minimum, smooth 60fps canvas)
- Access CDLC library from NAS (nasty) over network
- Be quiet enough to sit in a music room

## Hardware Requirements

| Component       | Minimum                    | Recommended                  | Why                                        |
|-----------------|----------------------------|------------------------------|--------------------------------------------|
| **CPU**         | Intel N100 (4C/4T)         | Intel N305 (8C/8T) or AMD   | Docker + Python audio + browser rendering  |
| **RAM**         | 8 GB                       | 16 GB                        | Docker overhead + browser + headroom       |
| **Storage**     | 128 GB SSD                 | 256 GB NVMe                  | OS + Docker images + audio cache           |
| **USB**         | 2x USB 2.0+ ports          | 3x USB 3.0                   | Rocksmith adapter + keyboard/mouse         |
| **Audio out**   | 3.5mm or HDMI audio        | 3.5mm + HDMI                 | Headphones for practice, HDMI for TV       |
| **Display**     | HDMI 1080p                 | HDMI 2.0 or DP              | Note highway needs smooth rendering        |
| **Network**     | Gigabit Ethernet            | Gigabit Ethernet             | Streaming CDLC from NAS, no WiFi jitter    |
| **Noise**       | Fanless or near-silent      | Fanless                      | Music room — fan noise is unacceptable     |

**NOT needed:** Dedicated GPU (browser canvas 2D is fine on integrated graphics),
Bluetooth, WiFi (use Ethernet for reliability).

## Recommended Builds

### Budget: ~$130-160 — Beelink Mini S12 Pro (or EQ12)
- Intel N100 (4C/4T, 3.4GHz boost), 16GB RAM, 500GB SSD
- 2x HDMI, 4x USB 3.0, 1x USB-C, Gigabit Ethernet
- Fanless or very quiet (N100 is 6W TDP)
- Ships with Windows but trivially wiped for Linux
- **This is the sweet spot. The N100 handles Docker + Python + Chromium easily.**
- Typical Amazon/AliExpress price: $130-160 for 16GB/500GB config

### Budget: ~$100-120 — Beelink Mini S12 (base)
- Same N100 but 8GB RAM, 256GB SSD
- Perfectly adequate — Slopsmith + Docker + browser fits in 8GB
- Save money here if tight on budget

### Budget: ~$70-90 — Raspberry Pi 5 (8GB)
- ARM64, USB 3.0, HDMI, Gigabit Ethernet
- **Risks:** Docker on ARM works but images may need rebuilding.
  Slopsmith's Dockerfile uses x86 binaries (vgmstream-cli, RsCli).
  Browser rendering may struggle at 60fps. Audio latency needs kernel tuning.
- Only recommended if you enjoy tinkering. The N100 mini PC is $50 more and just works.

### Budget: ~$200-250 — Beelink EQ12 Pro / Minisforum UM560
- Intel N305 (8C/8T) or AMD Ryzen 5 5560U
- Overkill for this use case, but future-proof
- Only if you want to also run amp sims (JACK + GuitarML/Neural Amp Modeler)

## Recommended Distro

**Ubuntu 24.04 LTS** — best Docker support, widest hardware compatibility,
PipeWire handles audio routing out of the box (replaces PulseAudio + JACK).

Alternative: Pop!_OS (same as antonym, familiar).

## Software Stack

```bash
# Base system
sudo apt update && sudo apt install -y \
    docker.io docker-compose-v2 \
    git curl wget \
    pipewire pipewire-alsa pipewire-jack \
    chromium-browser

# Add user to docker and audio groups
sudo usermod -aG docker,audio $USER

# Clone and run Slopsmith
git clone https://github.com/byrongamatos/slopsmith.git ~/slopsmith
cd ~/slopsmith

# Point at CDLC on NAS
# (mount NAS first, or set DLC_DIR to NFS/SMB mount)
sudo mount -t nfs nasty:/volume1/music/Rocksmith_CDLC/live /mnt/cdlc

# Run Slopsmith
DLC_DIR=/mnt/cdlc docker compose up -d

# For note detection plugin (runs outside Docker for USB audio access)
pip install aubio sounddevice numpy
```

## Signal Chain

```
Guitar ──→ Rocksmith USB Adapter ──→ Guitar PC (USB)
                                         │
                                         ├── sounddevice captures audio
                                         ├── aubio detects notes (Python)
                                         ├── Slopsmith renders highway (browser)
                                         └── Audio out → headphones / amp
```

No splitter needed. The Rocksmith adapter moves from the Mac to this machine.
Rocksmith on the Mac is no longer in the picture — Slopsmith replaces it.

## NAS Integration

```bash
# /etc/fstab entry for auto-mount at boot
nasty:/volume1/music/Rocksmith_CDLC/live  /mnt/cdlc  nfs  defaults,_netdev  0  0
```

Slopsmith reads PSARCs directly — no conversion step needed (unlike ChartPlayer).
Your entire CDLC library (1638 files in live/) is immediately available.

## Display Options

| Option                  | Cost     | Notes                                     |
|-------------------------|----------|-------------------------------------------|
| Existing TV via HDMI    | $0       | Most guitar setups have a TV nearby       |
| Spare monitor           | $0       | Any 1080p monitor works                   |
| Portable 15" USB-C      | $80-120  | Nice for a compact setup                  |
| Tablet + browser        | $0       | Access Slopsmith at http://guitarpc:8000  |

**Tablet option is interesting:** Since Slopsmith is a web app, you can run the server
on the PC but view the highway on an iPad/tablet/phone on the same network. The note
detection still runs on the PC (where the USB adapter is), and the browser just renders.

## Total Budget

### Minimal Setup: ~$130
| Item                          | Cost      |
|-------------------------------|-----------|
| Beelink Mini S12 Pro (16/500) | $130-160  |
| HDMI cable                    | $0-5      |
| Ethernet cable                | $0-5      |
| Display                       | $0 (TV)   |
| **Total**                     | **~$135** |

### Comfortable Setup: ~$200
| Item                          | Cost      |
|-------------------------------|-----------|
| Beelink Mini S12 Pro (16/500) | $150      |
| Portable 15" monitor          | $0-100    |
| Short Ethernet cable          | $5        |
| USB hub (if needed)           | $10       |
| **Total**                     | **~$165-265** |

## Setup Checklist

1. [ ] Buy mini PC
2. [ ] Install Ubuntu 24.04 (wipe Windows)
3. [ ] Install Docker, Chromium, PipeWire
4. [ ] Mount NAS CDLC share
5. [ ] Clone and run Slopsmith
6. [ ] Plug in Rocksmith USB adapter
7. [ ] Install note detection plugin
8. [ ] Test: open browser → pick song → play guitar → see notes detected
9. [ ] Configure auto-start (Slopsmith on boot, browser in kiosk mode)
