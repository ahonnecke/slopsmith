# Slopsmith Note Detection Plugin — Contribution Plan

## Context

Slopsmith is a 1-week-old open-source Rocksmith alternative (Python/FastAPI + vanilla JS).
It has native PSARC reading, a full note highway, and a plugin system — but NO note detection.
We have TonalRecall (`~/src/TonalRecall`), a working Python note detection system using
aubio/YIN + sounddevice that already handles the Rocksmith USB adapter.

**Goal:** Build a Slopsmith plugin that adds real-time note detection, hit/miss feedback,
and scoring — making it a true Rocksmith replacement.

---

## Architecture Decision: Server-Side vs Client-Side Detection

### Option A: Server-Side (Python) — RECOMMENDED
- Port TonalRecall's detection to a Slopsmith plugin `routes.py`
- Server captures audio via sounddevice (same machine running Slopsmith)
- WebSocket streams detected notes to the browser in real-time
- Browser renders hit/miss overlays via `highway.addDrawHook()`

**Pros:**
- Reuses TonalRecall code almost directly (Python, aubio, sounddevice)
- aubio's YIN is battle-tested and fast
- No browser permission UX issues (no getUserMedia needed)
- Works with USB audio interfaces (Rocksmith adapter) that browsers can't access
- Can use JACK or direct PortAudio — same stack as TonalRecall

**Cons:**
- Only works when Slopsmith runs locally (not remote/cloud)
- Adds sounddevice + aubio as server-side dependencies

### Option B: Client-Side (JavaScript)
- Use Web Audio API + getUserMedia for microphone capture
- Run pitch detection in browser (Pitchy.js, ML5.js, or custom YIN)

**Pros:** Works remotely, no server dependencies
**Cons:** getUserMedia UX friction, can't access USB audio devices directly,
JS pitch detection less mature than aubio, browser audio latency higher

**Verdict:** Option A. Slopsmith is already a "run locally" app (Docker/local Python).
The Rocksmith adapter is a USB device that browsers can't access. Server-side is the
natural fit and lets us reuse TonalRecall's proven code.

---

## Plugin Structure

```
plugins/note_detect/
├── plugin.json              # Plugin manifest
├── routes.py                # FastAPI WebSocket for audio capture + detection
├── screen.html              # Settings UI (device selection, gain, thresholds)
├── screen.js                # Highway draw hooks for hit/miss rendering + scoring
├── requirements.txt         # aubio, sounddevice, numpy
├── detection/
│   ├── __init__.py
│   ├── note_detector.py     # Ported from TonalRecall (YIN + aubio)
│   ├── stability.py         # Ported from TonalRecall stability_analyzer
│   └── frequency.py         # Frequency ↔ note conversion
└── README.md
```

---

## Phase 1: Core Detection WebSocket

### routes.py — Server-Side Audio Capture + Detection

```python
def setup(app, context):
    detector = None

    @app.websocket("/api/plugins/note_detect/stream")
    async def note_stream(ws):
        """Stream detected notes to the browser in real-time."""
        await ws.accept()
        # Start audio capture + YIN detection
        # Send JSON: {"note": "A2", "freq": 110.0, "confidence": 0.92, "time": 1.234}
        # Client compares with highway.getNotes() for scoring

    @app.get("/api/plugins/note_detect/devices")
    async def list_devices():
        """List available audio input devices."""
        # Return sounddevice.query_devices()

    @app.post("/api/plugins/note_detect/configure")
    async def configure(device_id: int, gain: float, ...):
        """Update detection parameters."""
```

### Key TonalRecall Code to Port

| TonalRecall File | Plugin File | What It Does |
|---|---|---|
| `audio/note_detector.py` | `detection/note_detector.py` | YIN pitch detection via aubio |
| `detection/stability_analyzer.py` | `detection/stability.py` | Deque-based note stability voting |
| `services/frequency.py` | `detection/frequency.py` | Hz ↔ note name conversion |
| `audio/audio_input.py` | `routes.py` (inline) | sounddevice stream setup |
| `note_types.py` | `detection/__init__.py` | DetectedNote dataclass |

### Detection Parameters (from TonalRecall)

```python
sample_rate = 48000          # Match JACK/Rocksmith adapter
hop_size = 512               # ~10ms at 48kHz
tolerance = 0.8              # YIN tolerance
min_confidence = 0.7         # Reject uncertain detections
min_frequency = 30.0         # Hz (low B on 5-string bass)
max_frequency = 1000.0       # Hz (high frets on guitar)
min_signal = 0.005           # Silence gate
stability_count = 3          # Detections needed for stable note
```

---

## Phase 2: Highway Integration (screen.js)

### Hit/Miss Rendering

```javascript
// Connect to detection WebSocket
const ws = new WebSocket(`ws://${location.host}/api/plugins/note_detect/stream`);
let detectedNotes = [];  // Recent detections with timestamps

ws.onmessage = (e) => {
    const det = JSON.parse(e.data);
    detectedNotes.push(det);
    // Trim old detections (> 5 seconds behind current time)
};

// Draw hook: overlay hit/miss on the highway
highway.addDrawHook(function(ctx, W, H) {
    const currentTime = highway.getTime();
    const notes = highway.getNotes();

    for (const note of notes) {
        if (note.time > currentTime - 2 && note.time < currentTime + 0.1) {
            const matched = detectedNotes.find(d =>
                Math.abs(d.time - note.time) < 0.2 &&
                noteMatchesFret(d.note, note.fret, note.string)
            );
            if (matched) {
                // Draw green glow / checkmark
            } else if (note.time < currentTime - 0.3) {
                // Draw red X / miss indicator
            }
        }
    }
});
```

### Scoring Display

```javascript
// Overlay score in top-right corner
let hits = 0, misses = 0, streak = 0, bestStreak = 0;

highway.addDrawHook(function(ctx, W, H) {
    const total = hits + misses;
    const pct = total > 0 ? Math.round(100 * hits / total) : 0;
    ctx.fillStyle = '#fff';
    ctx.font = '24px monospace';
    ctx.fillText(`${hits}/${total} (${pct}%)  Streak: ${streak}`, W - 350, 40);
});
```

---

## Phase 3: Practice Integration

### Loop + Slow Down + Score Per Section

The highway already has section data (`highway.getSections()`). We can:
- Track score per section
- Show section grades (A/B/C/D/F) at section boundaries
- Auto-suggest looping sections scored below threshold
- Integrate with Slopsmith's existing loop save/load API (`/api/loops`)

### Note Matching Logic

Matching a detected note to a chart note requires:
1. **Time window**: detected within ±200ms of chart note time
2. **Pitch matching**: detected frequency corresponds to the fret+string combo
3. **Tuning awareness**: use song's tuning offsets to calculate expected frequencies

```python
# Expected frequency for a note
STANDARD_TUNING = [329.63, 246.94, 196.00, 146.83, 110.00, 82.41]  # E4-E2
def expected_freq(string, fret, tuning_offsets):
    base = STANDARD_TUNING[string] * 2**(tuning_offsets[string]/12)
    return base * 2**(fret/12)
```

---

## Phase 4: Low Note Improvement

TonalRecall has known issues with notes below ~100Hz. Improvements:

1. **Larger window for low notes**: At 48kHz, a 41Hz fundamental (E1) needs ~1170 samples
   for one full cycle. Current 512 hop_size is too small. Use adaptive window:
   ```python
   hop_size = 512 if freq_estimate > 100 else 2048
   ```

2. **Sub-harmonic detection**: When YIN detects 2x the expected frequency,
   check sub-harmonic energy to confirm the fundamental

3. **Percentage-based grouping**: Replace fixed Hz threshold with percentage
   (e.g., 3% of detected frequency) for stability analysis

4. **Expected note hints**: Since we know what note the chart expects,
   bias detection toward nearby frequencies (Bayesian prior)

---

## Implementation Roadmap

```
Step 1: Create plugin skeleton (plugin.json, empty routes/screen)
Step 2: Port TonalRecall detection core (3 files, ~800 lines)
Step 3: WebSocket streaming (routes.py, ~100 lines)
Step 4: Device selection UI (screen.html, ~50 lines)
Step 5: Highway draw hooks for hit/miss (screen.js, ~150 lines)
Step 6: Scoring overlay (screen.js, ~50 lines)
Step 7: Section grading + practice integration (~100 lines)
Step 8: Low note improvements (detection refinement)
Step 9: PR to upstream slopsmith
```

---

## Dependencies to Add

```
# requirements.txt for the plugin
aubio>=0.4.9
sounddevice>=0.4.6
numpy>=1.24.0
```

---

## What Makes This PR-able

1. **Self-contained plugin** — doesn't modify any core slopsmith code
2. **Optional** — users who don't need detection don't install the plugin
3. **Uses existing plugin APIs** — highway draw hooks, WebSocket, settings
4. **Clear value add** — transforms Slopsmith from display-only to interactive
5. **Proven detection code** — TonalRecall's YIN approach already works
