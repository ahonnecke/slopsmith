# Slopsmith — AI Agent Guide

Slopsmith is a self-hosted web app for browsing, playing, and practicing Rocksmith 2014 Custom DLC. It runs as a Docker container with a FastAPI backend (`server.py`), vanilla JavaScript frontend (`static/`), shared Python libraries (`lib/`), and an extensive plugin system (`plugins/`). There are no frontend frameworks — everything is plain JS, HTML, and Tailwind CSS.

## Architecture Quick Reference

```
server.py              FastAPI app — library API, WebSocket highway, plugin loading
static/
  app.js               Main frontend — screens, library views, player, plugin loader
  highway.js           Canvas note highway renderer (createHighway factory)
  index.html           Single-page app shell
  style.css            Custom CSS loaded alongside Tailwind
lib/
  song.py              Core data models (Note, Chord, Arrangement, Song)
  psarc.py             PSARC archive reading and extraction
  sloppak.py           Sloppak format support
  audio.py             WEM/OGG/MP3 audio handling
  retune.py            Pitch-shifting logic
  tunings.py           Tuning name/offset utilities
  gp2rs.py             Guitar Pro to Rocksmith XML conversion
  gp2midi.py           Guitar Pro to MIDI
plugins/
  __init__.py           Plugin discovery, loading, requirements install
  <plugin_name>/        Each plugin is its own directory (often a git submodule)
tests/
  test_*.py             pytest test suite
```

## Plugin System

Plugins are the primary extension point. Each plugin lives in `plugins/<name>/` with a `plugin.json` manifest:

```json
{
  "id": "my_plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "private": false,
  "nav": { "label": "My Plugin", "screen": "plugin-my_plugin" },
  "screen": "screen.html",
  "script": "screen.js",
  "routes": "routes.py",
  "settings": { "html": "settings.html" }
}
```

All fields except `id` and `name` are optional. Plugins can have any combination of frontend (screen/script), backend (routes), and settings.

`version` and `private` are advisory metadata — the plugin loader does not currently consume them, but plugins commonly include them for publishing/tooling purposes.

**Backend routes** — `routes.py` must export a `setup(app, context)` function. The `context` dict provides:
- `config_dir` — persistent config path
- `get_dlc_dir()` — returns the DLC folder Path
- `extract_meta()` — metadata extraction callable
- `meta_db` — shared MetadataDB instance
- `get_sloppak_cache_dir()` — sloppak cache path

**Frontend scripts** — `screen.js` runs in the global scope via a `<script>` tag. It can access `window.playSong`, `window.showScreen`, `window.createHighway`, the `<audio>` element, and the `window.slopsmith` event emitter.

**The playSong wrapper chain** — Plugins commonly wrap `window.playSong` to hook into song playback. Plugins load alphabetically, so the last-loaded (alphabetically later) wrapper runs first, while the alphabetically first plugin runs closest to the original. Be aware that `await` calls in inner wrappers yield to the event loop — WebSocket messages can arrive before outer wrappers finish setup.

## Plugin Best Practices

### Visualization plugins MUST export a factory function

Any plugin that renders a visualization (tab view, note display, 3D highway, etc.) **must** export a factory function on `window` so the [Split Screen plugin](https://github.com/topkoa/slopsmith-plugin-splitscreen) can embed it as a per-panel pane.

**The contract:**

```js
window.createMyVisualization = function ({ container }) {
    // Create canvas/DOM inside container (split screen manages the container div)
    // Each call creates an INDEPENDENT instance — no shared mutable state
    return {
        connect(filename, arrangementIndex) { /* open WebSocket, start rendering */ },
        destroy() { /* cancel RAF, close WebSocket, remove DOM nodes */ },
        resize()  { /* update canvas backing store to match container size */ },
    };
};
```

**Key rules:**
- **No shared mutable state** — split screen creates 2-4 instances simultaneously. Each must have its own canvas, WebSocket, RAF handle, and internal state. Use closures or a context-swap pattern.
- **Own your WebSocket** — open your own connection to `/ws/highway/{filename}?arrangement={index}`. Do not reuse the main highway's connection.
- **Sync to audio directly** — read `document.getElementById('audio').currentTime` in your RAF loop.
- **Clean up completely in `destroy()`** — cancel RAF, close WebSocket, remove DOM nodes you created.
- **Handle `resize()` properly** — update canvas backing store respecting `devicePixelRatio`.
- **Gate on factory existence** — split screen checks `typeof window.createMyVisualization === 'function'` at runtime. If your plugin isn't installed, the option simply doesn't appear.

See the full integration guide: [Integrating Your Plugin With Split Screen](https://github.com/topkoa/slopsmith-plugin-splitscreen#integrating-your-plugin-with-split-screen)

Reference implementations:
- **Lyrics pane** — `createLyricsPane()` in splitscreen's screen.js (DOM-based, simplest example)
- **Jumping Tab** — `window.createJumpingTabPane()` in the [Jumping Tab plugin](https://github.com/renanboni/slopsmith-plugin-jumpingtab) (canvas-based with context-swap)

### General plugin guidelines

- Wrap your plugin code in an IIFE: `(function () { 'use strict'; ... })();`
- Use `localStorage` for user-facing settings, prefixed with your plugin id
- If hooking `window.playSong`, always call the original and `await` it
- If hooking `window.showScreen`, clean up your state when leaving the player screen
- Use `window.slopsmith.emit()` / `window.slopsmith.on()` for inter-plugin communication

## Song Formats

Slopsmith supports two song formats:

### PSARC (Rocksmith native)
The original Rocksmith 2014 archive format. Contains encrypted SNG note data, WEM audio, album art, and tone presets. Read-only — Slopsmith does fast metadata scanning in-memory via `lib/psarc.py` (`read_psarc_entries`) without fully unpacking the archive, but playback and conversion paths extract the PSARC to a temporary directory via `unpack_psarc()` before loading note/audio assets. Audio is decoded via `vgmstream-cli` + `ffmpeg`.

### Sloppak (open format)
An open, hand-editable song package designed for Slopsmith. Exists in two interchangeable forms:
- **Zip archive** (`.sloppak` file) — distribution form
- **Directory** (`.sloppak/` folder) — authoring form

**Contents:**
```
manifest.yaml          Song metadata (title, artist, album, duration, tuning, arrangement IDs, ...)
arrangements/
  lead.json            Note/chord/anchor data in wire format (see song.py)
  rhythm.json          Files here are driven by manifest.yaml arrangement entries
  ...                  (e.g. arrangements/<arrangement-id>.json)
stems/
  full.ogg             Mixed audio (always present)
  guitar.ogg           Individual stems (optional, from Demucs split)
  bass.ogg
  drums.ogg
  vocals.ogg
  piano.ogg
  other.ogg
cover.jpg              Album art (optional)
lyrics.json            Syllable-level lyrics (optional)
```

Sloppak is the preferred format for new features. The [Sloppak Converter plugin](https://github.com/topkoa/slopsmith-plugin-sloppak-converter) converts PSARCs to sloppak, and the [Stems plugin](https://github.com/topkoa/slopsmith-plugin-stems) provides live stem mixing for sloppak songs.

**Key code:**
- `lib/sloppak.py` — format detection, zip/directory resolution, metadata extraction, song loading
- `lib/sloppak_convert.py` — PSARC to sloppak conversion pipeline, Demucs stem splitting
- `lib/song.py` — shared data models (`Note`, `Chord`, `Arrangement`, `Song`) and wire format serialization used by both formats

## Frontend Conventions

- **No frameworks** — vanilla JS, fetch API, DOM manipulation
- **Globals** — `highway`, `audio`, `playSong()`, `showScreen()`, `createHighway()`, `window.slopsmith`
- **Storage** — `localStorage` for all user preferences
- **Styling** — Tailwind CSS utility classes, dark theme (`bg-dark-600`, `text-gray-300`, accent `#4080e0`, gold `#e8c040`)
- **Naming** — camelCase for JS functions, kebab-case for CSS classes, snake_case for plugin IDs
- **Player layout** — `#player` is `display:flex; flex-direction:column; position:fixed; inset:0`. `#highway` is `flex:1`. `#player-controls` sits at the bottom. Hiding the highway collapses the layout — use `margin-top: auto` on controls if you need to hide it.

## Backend Conventions

- **Framework** — FastAPI with uvicorn
- **Imports** — flat imports from `lib/` (no package `__init__.py`): `from song import Song`
- **Database** — SQLite via MetadataDB class with `threading.Lock` for thread safety
- **WebSocket** — JSON frames, try/except `WebSocketDisconnect`
- **Error handling** — graceful fallbacks (audio conversion errors don't crash the song, missing art returns placeholder)
- **Type hints** — used sparingly (`Path | None`, `dict`, `list`)
- **Docstrings** — minimal; code is self-documenting

## Testing

```bash
pytest                         # Run all tests
pytest tests/test_song.py -v   # Specific file
pytest -k "round_trip" -v      # Pattern match
```

- Framework: pytest
- Config: `pyproject.toml` sets `pythonpath = [".", "lib"]` and `testpaths = ["tests"]`
- CI: GitHub Actions runs pytest on push/PR to main (Python 3.12)
- Test dependencies: `requirements-test.txt`

## Versioning

- **`VERSION`** (repo root) — single source of truth; plain semver string (e.g. `0.2.4`). Bind-mounted into the container and copied by the Dockerfile so it's always available at `/app/VERSION`.
- **`GET /api/version`** — returns `{"version": "<contents of VERSION>"}`. Displayed as a badge in the navbar.
- **Auto-sync** — `.github/workflows/sync-version.yml` rewrites `VERSION` via a `repository_dispatch` (`desktop-released`) fired from `slopsmith-desktop`'s release job. As an explicit automation-only exception to the "Never push directly to main" rule in Git Workflow below, the sync job commits straight to `main` as `github-actions[bot]` (version bumps are mechanical; the PR round-trip adds no signal). Human contributors must still go through feature branches + PRs. No manual VERSION edits needed. Use the workflow's `workflow_dispatch` trigger with `version: X.Y.Z` for manual runs (recovery / out-of-band bumps).
- **`CHANGELOG.md`** — follows [Keep a Changelog](https://keepachangelog.com/) format. Update the `[Unreleased]` section with each PR; when `slopsmith-desktop` cuts a release, rename `[Unreleased]` to the new version + date (the VERSION bump itself is automated).

## Git Workflow

- **Never push directly to main** — always create a feature branch and open a PR
- **Upstream remote** — set `upstream` to the canonical Slopsmith repository; `origin` is your fork
- **Plugins are gitlinks** — each plugin in `plugins/` is typically its own git repo (submodule or clone). Branch switches on the main repo can clobber plugin directories. Use `git update-index --assume-unchanged` for plugin dirs if needed.
- **Commit style** — short imperative subject line, blank line, then body explaining *why*

## WebSocket Protocol Reference

The highway WebSocket at `/ws/highway/{filename}?arrangement={index}` streams these messages in order:

| Message | Shape | Description |
|---------|-------|-------------|
| `loading` | `{ type: 'loading', stage }` | Status/progress message during extraction or conversion |
| `song_info` | `{ type, title, artist, arrangement, arrangement_index, arrangements, duration, tuning, capo, format, audio_url, audio_error, stems }` | Song metadata. `arrangements` is the full list for the switcher. `audio_url` is `null` when audio is unavailable, in which case `audio_error` is non-null; otherwise `audio_error` is `null`. `stems` is always present — an empty array for non-sloppak songs or sloppak songs with no split stems. `tuning` is an array (6 for guitar, 4 for bass). |
| `beats` | `{ type, data: [{ time, measure }] }` | Beat timestamps with measure numbers |
| `sections` | `{ type, data: [{ time, name }] }` | Named sections (Intro, Verse, Chorus, etc.) |
| `anchors` | `{ type, data: [{ time, fret, width }] }` | Fret zoom anchors |
| `chord_templates` | `{ type, data: [{ name, frets: [6] }] }` | Named chord shapes |
| `lyrics` | `{ type, data: [{ w, t, d }] }` | Syllables: `w`=word, `t`=time, `d`=duration. `-` joins to previous, `+` = line break |
| `tone_changes` | `{ type: 'tone_changes', base, data: [{ time, name }] }` | Optional — tone change events relative to the arrangement base tone; only sent if tones were found |
| `notes` | `{ type, data: [{ t, s, f, sus, ho, po, sl, bn, ... }] }` | Single notes |
| `chords` | `{ type, data: [{ t, notes: [{ s, f, sus, ... }] }] }` | Chord events |
| `phrases` | `{ type, data: [{ start_time, end_time, max_difficulty, levels: [{ difficulty, notes, chords, anchors, handshapes }] }], total }` | Optional — per-phrase difficulty ladder for master-difficulty slider (slopsmith#48). Only sent when the source chart carries multi-level phrase data (PSARC / phrase-aware sloppak). Sent in chunks (`data` is a batch, `total` is the full count across messages) to avoid multi-MB single frames. Absent for GP imports and legacy sloppak; consumers must treat missing message as "single fixed difficulty — slider disabled". |
| `ready` | `{ type: 'ready' }` | All data sent — safe to finalize and start rendering |

Message delivery is incremental. You may receive `loading` updates and `lyrics` before note/chord payloads; `tone_changes` comes after `lyrics` when present and may be omitted entirely. Do not finalize rendering until you receive `ready`.

## Common Pitfalls

1. **playSong wrapper race condition** — The wrapper chain runs outermost-first (last-loaded wrapper runs first). If an inner plugin (e.g. `3dhighway`) does `await import(CDN)`, it yields to the event loop. WebSocket messages (`song_info`, `ready`) can arrive before outer plugins set their callbacks. Use `getSongInfo()` as a fallback rather than relying solely on `_onReady`.

2. **Plugin gitlinks** — Plugins are separate git repos cloned into `plugins/`. Switching branches on the main repo can delete or clobber these directories. Be careful with `git checkout` and `git clean`.

3. **Highway flex layout** — `#highway` has `flex:1` in the player. Hiding it with `display:none` removes the flex child, causing `#player-controls` to float to the top. If you hide the highway, add `margin-top: auto` to the controls div to keep it at the bottom.

4. **Multiple WebSocket connections** — The server supports many simultaneous WebSocket connections to the same song. Split screen panels, lyrics panes, and jumping tab panes each open their own. This is by design — don't try to multiplex.

5. **Plugin load order** — Plugins load alphabetically by directory name. This determines the `playSong` wrapper chain order and which plugin's UI elements appear first. If your plugin depends on another's globals, check at runtime (`typeof window.X === 'function'`), not at load time.
