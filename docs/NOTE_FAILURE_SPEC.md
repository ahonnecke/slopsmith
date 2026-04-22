# Note Failure Feedback — Technical Spec

## Goal

When a user loops over a lick, **show note misses on the highway** with diagnostic
detail: which note was missed, and *how* it was missed (timing vs pitch).

Rocksmith shows a `!` marker at the missed note position after it passes. We improve
on this by showing *why* the note was missed — too early, too late, wrong pitch, or
not played at all.

---

## Prerequisites

This feature depends on the **note detection plugin** (`slopsmith-plugin-notedetect`),
which provides real-time pitch detection via server-side aubio/YIN over WebSocket.
The detection plugin streams `DetectedNote` events; this spec describes the
**matching, judgment, and rendering** layer that consumes those events.

Without the detection plugin active, no miss/hit feedback is shown — the highway
renders exactly as it does today.

---

## Architecture

```
Guitar → USB Adapter → sounddevice (server)
                          ↓
                   aubio YIN detection
                          ↓
              WebSocket: detected notes
                          ↓
              ┌───────────────────────┐
              │   Note Matcher        │  ← THIS SPEC
              │   (client-side JS)    │
              │                       │
              │ Chart notes (highway) │
              │ × Detected notes (WS) │
              │ = Match/Miss/Extra    │
              └───────────────────────┘
                          ↓
              Highway draw hook overlay
              (hit glow, miss markers, diagnostics)
```

### Data Flow

1. **Chart notes** arrive via existing highway WebSocket (`/ws/highway/{filename}`).
   Wire format: `{ t, s, f, sus, bn, ho, po, ... }` (see `lib/song.py:note_to_wire`)

2. **Detected notes** arrive via detection plugin WebSocket
   (`/api/plugins/note_detect/stream`).
   Wire format: `{ note: "A2", freq: 110.0, confidence: 0.92, time: 1.234 }`

3. **Note Matcher** (new, client-side) correlates these two streams in real-time.

4. **Draw hook** renders results on the highway via `highway.addDrawHook()`.

---

## Note Matching Algorithm

### Match Window

A detected note matches a chart note when:

| Criterion      | Threshold              | Notes                                      |
|----------------|------------------------|---------------------------------------------|
| **Time**       | ±200ms (configurable)  | Centered on chart note time                 |
| **Pitch**      | ±50 cents              | Accounts for imperfect intonation           |
| **String**     | Exact match preferred  | Fall back to pitch-only if string unknown   |

### Expected Frequency Calculation

```javascript
// Standard tuning open-string frequencies (high E to low E)
const STANDARD_TUNING = [329.63, 246.94, 196.00, 146.83, 110.00, 82.41];

function expectedFreq(string, fret, tuningOffsets) {
    // tuningOffsets: array of 6 cent offsets from standard (from song metadata)
    const base = STANDARD_TUNING[string] * Math.pow(2, tuningOffsets[string] / 1200);
    return base * Math.pow(2, fret / 12);
}
```

### Match States

Each chart note transitions through these states:

```
PENDING  →  HIT       (matched detection within window)
         →  MISSED    (window expired, no match)

         →  EARLY     (matched detection, but > 100ms before chart time)
         →  LATE      (matched detection, but > 100ms after chart time)
         →  SHARP     (matched time, detected freq > expected + 30 cents)
         →  FLAT      (matched time, detected freq < expected - 30 cents)
```

A note can have **compound state**: e.g., `LATE + FLAT`.

### Judgment Data Structure

```javascript
// Per-note judgment, attached after the note passes the now-line
{
    chartNote: { t, s, f, ... },      // Original chart note
    state: 'HIT' | 'MISSED' | ...,
    timingError: -0.12,               // Seconds (negative = early)
    pitchError: +15,                  // Cents (positive = sharp)
    detectedFreq: 112.3,             // What was actually played
    expectedFreq: 110.0,             // What should have been played
    detectedAt: 1.354,               // When the detection arrived
}
```

---

## Highway Rendering

### Hit Feedback

Notes matched within ±50ms and ±20 cents get a **green glow ring** that fades
over 0.5s. The existing note rendering is unchanged — the glow is drawn *behind*
the note at the now-line position as it passes.

```
  [existing note bubble]
  └── green glow ring (additive blend, fades)
```

### Miss Markers

Missed notes get a persistent marker that scrolls down past the now-line and
remains visible for 2 seconds (configurable). The marker sits at the note's
string/fret position on the "past" portion of the highway (below now-line).

| State  | Visual                                                      |
|--------|-------------------------------------------------------------|
| MISSED | Red `✕` at note position + red tint on string segment       |
| EARLY  | Orange `↑` (up arrow) + timing offset label (e.g., "-120ms")|
| LATE   | Orange `↓` (down arrow) + timing offset label ("+85ms")     |
| SHARP  | Blue `♯` + cents label ("+35¢")                             |
| FLAT   | Blue `♭` + cents label ("-42¢")                             |

Compound states stack vertically: timing indicator on top, pitch indicator below.

### Miss markers on the string area

Below the now-line, the 6 open strings are always visible. For a missed note,
the relevant string segment between the now-line and ~20px below it gets a brief
red pulse (200ms fade).

### Loop Iteration Summary

When A-B looping is active, at the end of each loop iteration (when playback
wraps from B back to A), show a brief overlay:

```
┌─────────────────────┐
│  Loop 3/∞           │
│  5/7 notes hit (71%)│
│  Best: 6/7 (86%)    │
└─────────────────────┘
```

Displayed for 1.5s, then fades. Does not block the highway.

---

## State Management

### NoteJudgmentTracker

Client-side class that manages the correlation between chart notes and detections.

```javascript
class NoteJudgmentTracker {
    constructor(chartNotes, chartChords, tuning) { ... }

    // Called when a detected note arrives from the detection WebSocket
    addDetection(detected) { ... }

    // Called each frame; checks for expired match windows
    update(currentTime) { ... }

    // Returns judgments for notes in the visible time range
    getJudgmentsInRange(tStart, tEnd) { ... }

    // Reset (on song change, loop restart, arrangement switch)
    reset() { ... }

    // Stats for the current loop iteration
    getLoopStats() { ... }
}
```

### Memory Management

- Judgments older than 10 seconds behind current time are pruned each frame.
- Detection buffer holds last 5 seconds of raw detections.
- On loop wrap (B→A), archive current iteration stats, reset judgments for
  the loop range, keep detections flowing.

### Loop-Aware Behavior

The tracker must handle A-B looping:

1. Detect loop wrap: `currentTime < previousTime - 0.5` (jumped backward).
2. On wrap: snapshot current stats to `loopHistory[]`, reset judgments
   for notes in `[loopA, loopB]` range.
3. `getLoopStats()` returns current iteration + best historical iteration.

---

## Integration Points

### Existing Highway API Used

| API                          | Purpose                                  |
|------------------------------|------------------------------------------|
| `highway.addDrawHook(fn)`    | Register the overlay renderer            |
| `highway.removeDrawHook(fn)` | Cleanup on plugin unload                 |
| `highway.getTime()`          | Current chart time (audio-aligned)       |
| `highway.getNotes()`         | All chart notes (for matching)           |
| `highway.getChords()`        | All chart chords (match individual notes)|
| `highway.getSections()`      | Section boundaries (for section grading) |
| `highway.getSongInfo()`      | Tuning offsets for frequency calculation |
| `highway.project(tOffset)`   | Convert time offset to Y position        |
| `highway.fretX(fret, s, w)`  | Convert fret to X position               |
| `highway.fillTextUnmirrored` | Text that stays readable in lefty mode   |

### Existing App.js Used

| Global                       | Purpose                                  |
|------------------------------|------------------------------------------|
| `loopA`, `loopB`             | Current A-B loop boundaries              |
| `audio.currentTime`          | Actual audio playback position           |

### New Events Emitted (via `window.slopsmith.emit`)

| Event                        | Payload                                  |
|------------------------------|------------------------------------------|
| `note:hit`                   | `{ note, timing, pitch }`                |
| `note:miss`                  | `{ note, reason }`                       |
| `loop:complete`              | `{ iteration, stats }`                   |

These events allow other plugins (practice journal, scoring, section map) to
react to note judgments without coupling to the detection plugin directly.

---

## Configuration (plugin settings)

| Setting                | Default | Description                              |
|------------------------|---------|------------------------------------------|
| `matchWindowMs`        | 200     | Time tolerance for note matching (ms)    |
| `pitchToleranceCents`  | 50      | Pitch tolerance for note matching        |
| `showTimingErrors`     | true    | Show early/late indicators               |
| `showPitchErrors`      | true    | Show sharp/flat indicators               |
| `missMarkerDuration`   | 2.0     | How long miss markers stay visible (sec) |
| `showLoopSummary`      | true    | Show stats on loop wrap                  |
| `hitGlowDuration`      | 0.5     | Green glow fade time (sec)               |
| `timingThresholdMs`    | 100     | Below this = "good timing" (no label)    |
| `pitchThresholdCents`  | 20      | Below this = "good pitch" (no label)     |

Stored via Slopsmith's `/api/settings` endpoint under a `notedetect_feedback` key.

---

## What This Does NOT Cover

- **Audio input / pitch detection** — handled by the detection plugin
- **Device selection UI** — handled by the detection plugin
- **Score persistence / history** — future work (practice journal plugin)
- **Difficulty scaling** — Rocksmith's dynamic difficulty is not implemented
- **Chord grading** — chords are graded per-note (each note in the chord
  is independently matched), not as a single unit
