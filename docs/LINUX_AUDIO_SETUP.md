# Linux audio setup — hearing your USB guitar

USB guitar adapters (Hercules Rocksmith, Behringer UCG102, etc.) capture audio
to the OS but **do not** route it to your speakers automatically. Slopsmith's
note detection only needs the input side, so detection will work even with no
sound coming out — but you'll want to actually hear yourself play.

The fix is a PipeWire/PulseAudio **loopback module** that pipes the USB input
into your default output sink.

## Find your devices

```bash
pactl list short sources | grep -iE 'rocksmith|guitar'
pactl list short sinks   | grep -v monitor
```

Use the exact `name` from those outputs in the next step.

## Load the loopback (now)

```bash
pactl load-module module-loopback \
  source=alsa_input.usb-Hercules_Rocksmith_USB_Guitar_Adapter-00.mono-fallback \
  sink=alsa_output.pci-0000_00_1f.3.analog-stereo \
  latency_msec=20
```

Tunables:
- `latency_msec=20` — round-trip target. Lower = tighter monitoring; too low and
  PipeWire underruns. 20 ms is a good starting point on a modern desktop.
- Add `source_dont_move=true sink_dont_move=true` if you don't want
  pavucontrol/Helvum to reroute it.

Verify:

```bash
pactl list short modules | grep loopback
pactl list sink-inputs   | grep -A1 loopback
```

## Make it persistent

`pactl load-module` is **runtime-only**. Restarting `pipewire`/`wireplumber`
(or rebooting) wipes it. Pick one of the persistence options below.

### Option 1 — PipeWire config (preferred)

Create `~/.config/pipewire/pipewire.conf.d/99-guitar-monitor.conf`:

```
context.modules = [
  { name = libpipewire-module-loopback
    args = {
      node.description = "Guitar monitor"
      capture.props = {
        node.target = "alsa_input.usb-Hercules_Rocksmith_USB_Guitar_Adapter-00.mono-fallback"
        node.passive = true
      }
      playback.props = {
        node.target = "alsa_output.pci-0000_00_1f.3.analog-stereo"
        media.class = "Stream/Output/Audio"
      }
    }
  }
]
```

Reload: `systemctl --user restart pipewire`.

### Option 2 — systemd user unit

`~/.config/systemd/user/guitar-monitor.service`:

```
[Unit]
Description=Loopback USB guitar to speakers
After=pipewire.service
Wants=pipewire.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/pactl load-module module-loopback \
  source=alsa_input.usb-Hercules_Rocksmith_USB_Guitar_Adapter-00.mono-fallback \
  sink=alsa_output.pci-0000_00_1f.3.analog-stereo \
  latency_msec=20

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now guitar-monitor.service
```

## Troubleshooting

**No sound but capture is running** — check that the loopback module is
actually loaded (`pactl list short modules | grep loopback`). If a
`pipewire`/`wireplumber` restart happened (manually or after a session
crash), `pactl load-module` registrations are gone and need to be reloaded.

**Stale PipeWire client registrations** — after Firefox/Chromium crashes,
PipeWire can leave zombie source-outputs/sink-inputs referencing dead PIDs.
A `systemctl --user restart wireplumber pipewire-pulse pipewire` clears
them, but **also wipes any `pactl load-module` state** — reload your
loopback after.

**Device name changed** — USB device names are stable across reboots in
PipeWire (`alsa_input.usb-<vendor>_<model>...`) but a hardware re-enumerate
can occasionally produce a different suffix. If your persistent config
stops working, re-run `pactl list short sources` and update the source name.

**Detect toggle disrupts USB-out monitoring** — known intermittent issue:
when notedetect's Detect button toggles on/off, the loopback module that
pipes USB-guitar → speakers may stop passing audio. Workaround: toggle
Detect off and on once or twice (the user has reported needing 5 cycles
in worst case). Root cause is below the JS audio API: PipeWire
renegotiates the USB source's clock/quantum when Firefox's `getUserMedia`
grab attaches and detaches concurrently with the loopback's source-read.
The notedetect plugin disconnects its WebAudio graph in stages on stop
(source first, then worklet, then tracks, then context close) to reduce
the race, but PipeWire still occasionally drops the loopback's
source-output during the renegotiation.

When this happens, capture diagnostic data so we can write a real fix:

```bash
# Terminal — capture PipeWire state DURING the breakage:
pactl list sink-inputs > /tmp/sink-inputs-broken.txt
pactl list source-outputs > /tmp/source-outputs-broken.txt

# DevTools console — capture JS audio state at the same moment:
await slopsmith.ndDiag.audioPath()
```

Then toggle Detect to recover and re-capture both:

```bash
pactl list sink-inputs > /tmp/sink-inputs-working.txt
pactl list source-outputs > /tmp/source-outputs-working.txt
```

```js
await slopsmith.ndDiag.audioPath()
```

The diff between broken and working states tells us exactly which stream
got wedged (corked, disconnected from source, routed to a dead sink).
Without that data we can only ship defensive patches; with it we can
write a targeted fix.
