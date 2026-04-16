# ChartPlayer Practice Tools — Implementation Plan

## Context

ChartPlayer is working with the Rocksmith USB adapter via JACK, but the practice experience
is lacking compared to Rocksmith. The on-screen notes lag audio by ~0.5s, there's no obvious
way to loop sections, no song search, and no feedback on missed notes.

The deployed version (0.1.10) is 16 versions behind upstream (0.1.26). Many features we need
already exist in the binary but aren't exposed. We'll fork from latest upstream, which may
already fix some issues, then build on top.

**Goal:** Make ChartPlayer a better *practice* tool than Rocksmith — focused on the
loop-slow-down-review workflow that actually builds muscle memory.

---

## Phase 0: Environment Setup

1. Install .NET 8 SDK: `brew install dotnet@8`
2. Fork upstream on GitHub: `gh repo fork mikeoliphant/ChartPlayer --clone ~/src/ChartPlayer`
3. Build locally: `cd ~/src/ChartPlayer && dotnet build ChartPlayerJack/ChartPlayerJack.csproj`
4. Deploy to ~/ChartPlayer and verify it runs with JACK + Rocksmith adapter
5. Verify we're on v0.1.26 — check if `[`/`]` loop keys and speed popup already work better

**Risk:** Build may have submodule or native dependency issues. Budget time for this.

---

## Phase 1: Audio-Visual Timing Fix *(highest impact, ~5 lines of code)*

**Problem:** Notes appear ~0.5s behind the music.

**What exists:** `ChartScene3D.CurrentTimeOffset` property, only applied to beat markers in
`DrawBeats()`, not the main note highway.

**Changes:**
- `ChartScene3D.cs` — In `Draw()`, apply offset to `currentTime` globally:
  `currentTime = (float)player.CurrentSecond + CurrentTimeOffset;`
- `SongPlayerSettings.cs` — Add `float AudioVideoOffset { get; set; } = 0;` property
- `SongPlayerSettingsInterface` — Add slider via existing `CreateFloatOption()` helper
  in the General tab (range -1.0 to 1.0 seconds)
- `SongPlayerInterface.cs` — In `ApplySettings()`, propagate:
  `chartScene.CurrentTimeOffset = settings.AudioVideoOffset;`
- `ChartPlayerGame.cs` — Add `+`/`-` key mappings for quick 10ms nudge

**Complexity:** Trivial. PR-able upstream.

---

## Phase 2: Loop & Speed Polish *(high impact, low effort)*

**What already exists (may be better in v0.1.26):**
- `[`/`]` toggle loop start/end markers
- Double-click section in timeline sets loop to section boundaries
- `CheckLoopMarkers()` runs every frame
- Speed slider (50%-100%) with RubberBand time-stretching

**Changes:**
- Add "clear loop" key (`\` or `Backspace`) — set both markers to -1
- Add loop status indicator in bottom bar (text: "Loop: 0:42-1:15" or hidden when no loop)
- Add loop iteration counter (how many times you've looped)
- Extend speed range to 25%-100% (change formula in `SpeedChanged()`)
- Add speed keyboard shortcuts (`Ctrl+Up`/`Down` for ±5%)
- Add "slow on loop restart" option: auto-reduce speed when loop replays,
  gradually increase each iteration (ramp practice)

**Complexity:** Trivial to moderate. Most is wiring existing features.
PR-able: clear-loop and indicator yes, ramp-practice is opinionated (fork feature).

**Files:** `SongPlayerInterface.cs`, `ChartPlayerGame.cs`

---

## Phase 3: Missed Note Visualization *(moderate impact, moderate effort)*

**What exists:** `FretPlayerScene3D.notesDetected[]` — sbyte array where 0=unseen, 1=hit, -1=missed.
Drawing code in `DrawNote()` already knows `isDetected` per note. Notes >1s behind `currentTime`
aren't drawn (`secsBehind` variable).

**Changes:**
- In `DrawNote()`, color missed notes red (tint or transparency change) and hit notes green
- Extend `secsBehind` from 1s to 3s so you can see recent misses on the fretboard
- Add a "Review" toggle: pauses playback, shows the entire current section with hit/miss colors
- Section summary: when a section ends, briefly flash "Section: 85% (17/20)" overlay

**Complexity:** Moderate. Note coloring is straightforward (modify color passed to quad draw).
Review mode requires adjusting the camera/viewport range. Section summary needs matching
note positions to `SongStructure.Sections`.

**Files:** `FretPlayerScene3D.cs`, `SongPlayerInterface.cs`

---

## Phase 4: Song Search *(moderate impact, moderate effort)*

**What exists:** `SongListDisplay` with `MultiColumnItemDisplay<SongIndexEntry>`, sortable columns,
tag-based filtering via `currentFilterTag`. UILayout has `ShowTextInputPopup()` for modal text input.

**Changes (Option A — search popup, simplest):**
- Add a "Search" button next to the filter button in song list
- On click, `ShowTextInputPopup()` → filter `allSongs` where `SongName` or `ArtistName`
  contains search text (case-insensitive)
- Integrate with existing `SetCurrentSongs()` method
- Add `/` keyboard shortcut to trigger search (like Vim)
- Add `Escape` to clear search and show all songs

**Future upgrade (Option B):** Build a persistent search box with live filtering.
Requires a custom TextBox widget in UILayout — more work.

**Complexity:** Option A is ~20 lines. Option B is significant.

**Files:** `SongListInterface.cs`

---

## Phase 5: Score & Streak Feedback *(polish, after core practice tools work)*

**What exists:** `scoreText` showing "X/Y (Z%)", `notesDetected[]` array.

**Changes:**
- Add streak counter: consecutive hits displayed next to score
- Flash/pulse effect on note hit (brighten the note quad briefly)
- Section letter grade (A/B/C/D/F) at section transitions
- Persist best score per song per instrument to SaveData

**Complexity:** Moderate. Streak counter is trivial. Visual effects need MonoGame texture work.
Score persistence needs XML schema addition.

---

## What's NOT realistic for an LLM

- **Tone/effects simulation** — Use a DAW or amp sim plugin alongside ChartPlayer instead
- **Dynamic difficulty** (Rocksmith's adaptive system) — Complex AI/ML tuning, not worth it
- **Multiplayer** — Networking code is out of scope
- **Video sync** — Different problem domain
- **Custom chart editor** — Huge UI effort for niche use
- **Mobile port** — Platform work, not a code change

---

## Execution Order

```
Day 1:  Phase 0 — clone, build, verify on latest upstream
Day 1:  Phase 1 — A/V offset fix (5 lines, immediate relief)
Day 1:  Phase 2 — Loop/speed polish (wiring existing code)
Day 2:  Phase 3 — Missed note colors + section summary
Day 2:  Phase 4 — Song search (popup version)
Day 3+: Phase 5 — Score/streak polish
```

Phases 1-2 are the critical path — they transform ChartPlayer from "barely usable for practice"
to "better than Rocksmith for focused practice." Phase 3-4 are quality of life. Phase 5 is nice-to-have.

---

## Verification

After each phase:
1. Build: `dotnet build ChartPlayerJack/ChartPlayerJack.csproj`
2. Deploy: copy publish output to ~/ChartPlayer/
3. Start JACK: `/opt/homebrew/opt/jack/bin/jackd -X coremidi -d coreaudio -r 48000 -p 1024`
4. Run ChartPlayer, load a song, and test the specific feature
5. For A/V offset: verify notes align with audio by playing along
6. For loop: verify `[`/`]` set markers, `\` clears, speed ramp works
7. For missed notes: play badly on purpose, verify red coloring appears
