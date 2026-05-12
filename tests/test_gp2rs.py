"""Tests for lib/gp2rs.py tempo/tick math helpers + playback-schedule walker.

The math helpers are fixture-free: hand-constructed `TempoEvent` lists and
integer tick / string inputs. The playback-schedule tests use
`SimpleNamespace` mocks shaped like `guitarpro.MeasureHeader` / `Song` —
the schedule walker only reads a small set of attributes, so we don't need
real .gp files on disk.

See issue #46 (tempo math) and the GP repeat-expansion PR for the schedule
walker.
"""

from types import SimpleNamespace

import pytest

from gp2rs import (
    GP_TICKS_PER_QUARTER,
    TempoEvent,
    _build_playback_schedule,
    _gp_string_to_rs,
    _tempo_at_tick,
    _tick_to_seconds,
)


# ── _tick_to_seconds ─────────────────────────────────────────────────────────

def test_tick_to_seconds_at_zero():
    # Tick 0 is always time 0 regardless of tempo.
    tempo_map = [TempoEvent(tick=0, tempo=120.0)]
    assert _tick_to_seconds(0, tempo_map) == 0.0


def test_tick_to_seconds_constant_tempo():
    # At 120 BPM with 960 ticks/quarter, one quarter = 0.5s, so 1920 ticks = 1.0s.
    tempo_map = [TempoEvent(tick=0, tempo=120.0)]
    assert _tick_to_seconds(GP_TICKS_PER_QUARTER, tempo_map) == pytest.approx(0.5)
    assert _tick_to_seconds(2 * GP_TICKS_PER_QUARTER, tempo_map) == pytest.approx(1.0)
    assert _tick_to_seconds(4 * GP_TICKS_PER_QUARTER, tempo_map) == pytest.approx(2.0)


def test_tick_to_seconds_tempo_change_accumulates():
    # 4 quarter notes at 120 BPM = 2.0s, then 4 at 60 BPM = 4.0s. Total 6.0s.
    tempo_map = [
        TempoEvent(tick=0, tempo=120.0),
        TempoEvent(tick=4 * GP_TICKS_PER_QUARTER, tempo=60.0),
    ]
    # At the tempo-change boundary, time is 2.0 (4 beats at 120).
    assert _tick_to_seconds(4 * GP_TICKS_PER_QUARTER, tempo_map) == pytest.approx(2.0)
    # 4 more beats at 60 BPM = 4.0s. Total 6.0.
    assert _tick_to_seconds(8 * GP_TICKS_PER_QUARTER, tempo_map) == pytest.approx(6.0)


def test_tick_to_seconds_extrapolates_past_last_event():
    # Ticks past the last tempo event use that last event's tempo.
    tempo_map = [
        TempoEvent(tick=0, tempo=120.0),
        TempoEvent(tick=1000, tempo=240.0),
    ]
    # First 1000 ticks at 120 BPM = 1000/960 * 0.5 = 0.5208...s
    # Next 1000 ticks at 240 BPM = 1000/960 * 0.25 = 0.2604...s
    expected = (1000 / GP_TICKS_PER_QUARTER) * (60.0 / 120.0) + \
               (1000 / GP_TICKS_PER_QUARTER) * (60.0 / 240.0)
    assert _tick_to_seconds(2000, tempo_map) == pytest.approx(expected)


# ── _tempo_at_tick ───────────────────────────────────────────────────────────

def test_tempo_at_tick_before_first_event_returns_first_tempo():
    tempo_map = [TempoEvent(tick=100, tempo=120.0)]
    # Tick 0 is before the "first" event (which is at 100). Function starts
    # result at tempo_map[0].tempo and only updates when event.tick <= tick.
    assert _tempo_at_tick(0, tempo_map) == 120.0


def test_tempo_at_tick_at_exact_event():
    tempo_map = [
        TempoEvent(tick=0, tempo=120.0),
        TempoEvent(tick=500, tempo=200.0),
    ]
    assert _tempo_at_tick(500, tempo_map) == 200.0


def test_tempo_at_tick_between_events():
    tempo_map = [
        TempoEvent(tick=0, tempo=120.0),
        TempoEvent(tick=1000, tempo=200.0),
    ]
    assert _tempo_at_tick(500, tempo_map) == 120.0


def test_tempo_at_tick_past_last_event():
    tempo_map = [
        TempoEvent(tick=0, tempo=120.0),
        TempoEvent(tick=100, tempo=60.0),
        TempoEvent(tick=500, tempo=180.0),
    ]
    assert _tempo_at_tick(999999, tempo_map) == 180.0


def test_tempo_at_tick_single_event_map():
    tempo_map = [TempoEvent(tick=0, tempo=90.0)]
    assert _tempo_at_tick(0, tempo_map) == 90.0
    assert _tempo_at_tick(100000, tempo_map) == 90.0


# ── _gp_string_to_rs ─────────────────────────────────────────────────────────
# GP string numbering: 1 = highest pitch, N = lowest
# RS string numbering: 0 = lowest pitch (low E on a guitar)
# Transform: rs_index = num_strings - gp_string

@pytest.mark.parametrize("gp_string,num_strings,rs_index", [
    # 6-string guitar: GP 1 (high e) -> RS 5, GP 6 (low E) -> RS 0
    (1, 6, 5),
    (2, 6, 4),
    (3, 6, 3),
    (4, 6, 2),
    (5, 6, 1),
    (6, 6, 0),
    # 4-string bass: GP 1 (G) -> RS 3, GP 4 (E) -> RS 0
    (1, 4, 3),
    (2, 4, 2),
    (3, 4, 1),
    (4, 4, 0),
    # 7-string guitar: GP 1 (high e) -> RS 6, GP 7 (low B) -> RS 0
    (1, 7, 6),
    (7, 7, 0),
])
def test_gp_string_to_rs(gp_string, num_strings, rs_index):
    assert _gp_string_to_rs(gp_string, num_strings) == rs_index


# ── _build_playback_schedule ─────────────────────────────────────────────────
# Mocks `guitarpro.MeasureHeader` and `guitarpro.Song` with `SimpleNamespace`.
# The schedule walker reads only:
#   - song.measureHeaders[i].start, .timeSignature.numerator/.denominator.value,
#     .isRepeatOpen, .repeatClose, .repeatAlternative, .direction, .fromDirection
# That's all the fixture surface we need to construct.

def _make_song(headers):
    return SimpleNamespace(measureHeaders=headers)


def _make_header(
    start_quarters: float,
    numerator: int = 4,
    denominator: int = 4,
    *,
    is_repeat_open: bool = False,
    repeat_close: int = -1,
    repeat_alt: int = 0,
    direction_name: str | None = None,
    from_direction_name: str | None = None,
):
    """Build a mock MeasureHeader. ``start_quarters`` is in quarter-notes
    from the song start; converted to ticks internally."""
    return SimpleNamespace(
        start=int(round(start_quarters * GP_TICKS_PER_QUARTER)),
        number=0,  # unused by schedule walker; converters set it from mh.number
        timeSignature=SimpleNamespace(
            numerator=numerator,
            denominator=SimpleNamespace(value=denominator),
        ),
        isRepeatOpen=is_repeat_open,
        repeatClose=repeat_close,
        repeatAlternative=repeat_alt,
        direction=SimpleNamespace(name=direction_name) if direction_name else None,
        fromDirection=SimpleNamespace(name=from_direction_name) if from_direction_name else None,
        marker=None,
    )


def _ids(schedule):
    """Compact `(mh_index, pass_index)` summary for assertions."""
    return [(e.mh_index, e.pass_index) for e in schedule]


# Standard tempo map: 120 BPM constant → one 4/4 measure = 2.0 s.
_TM_120 = [TempoEvent(tick=0, tempo=120.0)]


def test_schedule_no_repeats_no_directions():
    # 4 plain measures → 4 entries, pass=0 each, output times monotonic at 2 s/measure.
    headers = [_make_header(i * 4) for i in range(4)]
    schedule = _build_playback_schedule(_make_song(headers), _TM_120)
    assert _ids(schedule) == [(0, 0), (1, 0), (2, 0), (3, 0)]
    assert [round(e.output_start_secs, 3) for e in schedule] == [0.0, 2.0, 4.0, 6.0]


def test_schedule_simple_repeat():
    # ||: A | B :||×2 → 4 entries: A0 B0 A1 B1
    headers = [
        _make_header(0, is_repeat_open=True),   # A
        _make_header(4, repeat_close=1),         # B (×2: 1 additional rep)
    ]
    schedule = _build_playback_schedule(_make_song(headers), _TM_120)
    assert _ids(schedule) == [(0, 0), (1, 0), (0, 1), (1, 1)]
    assert [round(e.output_start_secs, 3) for e in schedule] == [0.0, 2.0, 4.0, 6.0]


def test_schedule_with_volta():
    # ||: A | B :|1.| C |2.| D ||  — C plays pass 0 only, D plays pass 1 only.
    # Volta C: repeatAlternative bit 0 set; close-of-pass-0 is at C itself
    # (repeatClose=1 because the bracket repeats once total, so 2 passes).
    headers = [
        _make_header(0, is_repeat_open=True),         # A
        _make_header(4),                                # B
        _make_header(8, repeat_alt=0b01),               # C (1st ending)
        _make_header(12, repeat_alt=0b10, repeat_close=1),  # D (2nd ending, closes)
    ]
    schedule = _build_playback_schedule(_make_song(headers), _TM_120)
    # Pass 0: A B C (skip D). Pass 1: A B D (skip C).
    assert _ids(schedule) == [
        (0, 0), (1, 0), (2, 0),
        (0, 1), (1, 1), (3, 1),
    ]


def test_schedule_sequential_groups():
    # ||: A :||×2 | B | ||: C :||×3  → 2×A, B, 3×C
    headers = [
        _make_header(0, is_repeat_open=True, repeat_close=1),  # A (×2)
        _make_header(4),                                          # B
        _make_header(8, is_repeat_open=True, repeat_close=2),  # C (×3)
    ]
    schedule = _build_playback_schedule(_make_song(headers), _TM_120)
    assert _ids(schedule) == [
        (0, 0), (0, 1),       # 2×A
        (1, 0),                # B
        (2, 0), (2, 1), (2, 2),  # 3×C
    ]


def test_schedule_da_capo_al_fine():
    # A | B(Fine) | C | D(D.C. al Fine) → A B C D A B (stop at Fine on pass 2)
    headers = [
        _make_header(0),                                            # A
        _make_header(4, direction_name="Fine"),                     # B
        _make_header(8),                                            # C
        _make_header(12, from_direction_name="Da Capo al Fine"),    # D
    ]
    schedule = _build_playback_schedule(_make_song(headers), _TM_120)
    assert _ids(schedule) == [(0, 0), (1, 0), (2, 0), (3, 0), (0, 0), (1, 0)]


def test_schedule_dal_segno_al_coda():
    # A | B(Segno) | C(To Coda) | D | E(D.S. al Coda) | F(Coda) | G
    # → A B C D E B C F G  (jump to Segno, replay until Da Coda redirect, jump to Coda)
    headers = [
        _make_header(0),                                            # A
        _make_header(4, direction_name="Segno"),                    # B
        _make_header(8, from_direction_name="Da Coda"),             # C (To Coda)
        _make_header(12),                                           # D
        _make_header(16, from_direction_name="Da Segno al Coda"),   # E
        _make_header(20, direction_name="Coda"),                    # F
        _make_header(24),                                           # G
    ]
    schedule = _build_playback_schedule(_make_song(headers), _TM_120)
    # First pass: A B C D E → at E, jump back to Segno (B). Now jumped_back=True,
    # stop_at="coda". Replay from B: B is fine (no Da Coda). C has Da Coda →
    # redirect to F. Then G plays. Final: A B C D E B F G.
    assert _ids(schedule) == [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (1, 0), (5, 0), (6, 0)]


def test_schedule_da_capo_inside_repeat_block_fires_immediately():
    # ||: A | B(D.C. al Fine) :||×2 | C(Fine) | D
    # A D.C. authored *inside* a repeat block must still fire the first time
    # we reach the measure carrying it — without the repeat completing the
    # remaining passes. This is the regression the inline repeat sub-loop
    # used to miss: it would silently complete the bracket and the D.C.
    # never triggered.
    headers = [
        _make_header(0, is_repeat_open=True),                                # A
        _make_header(4, repeat_close=1, from_direction_name="Da Capo al Fine"),  # B
        _make_header(8, direction_name="Fine"),                              # C
        _make_header(12),                                                    # D
    ]
    schedule = _build_playback_schedule(_make_song(headers), _TM_120)
    # First pass through the bracket plays A B once; the D.C. fires at the
    # end of B before the second pass; the jumped-back walk plays A B C and
    # stops at Fine.
    assert _ids(schedule) == [(0, 0), (1, 0), (0, 0), (1, 0), (2, 0)]


def test_schedule_da_capo_suppresses_inner_repeats():
    # ||: A :||×2 | B(D.C.) → first pass plays the bracket (A A B), then D.C.
    # jumps back to measure 0 and replays inner repeat *once* (A B).
    headers = [
        _make_header(0, is_repeat_open=True, repeat_close=1),       # A (×2)
        _make_header(4, from_direction_name="Da Capo"),              # B
    ]
    schedule = _build_playback_schedule(_make_song(headers), _TM_120)
    # Pass 1: A A B (repeat honored). After D.C.: jumped_back=True → A B.
    assert _ids(schedule) == [(0, 0), (0, 1), (1, 0), (0, 0), (1, 0)]


def test_schedule_expand_disabled():
    # Same shape as simple_repeat but expand_repeats=False → 2 entries.
    headers = [
        _make_header(0, is_repeat_open=True),
        _make_header(4, repeat_close=1),
    ]
    schedule = _build_playback_schedule(
        _make_song(headers), _TM_120, expand_repeats=False,
    )
    assert _ids(schedule) == [(0, 0), (1, 0)]


def test_schedule_orphan_open_warns(caplog):
    # Open without matching close → log warning, walk linearly.
    headers = [
        _make_header(0, is_repeat_open=True),
        _make_header(4),
        _make_header(8),
    ]
    with caplog.at_level("WARNING", logger="slopsmith.lib.gp2rs"):
        schedule = _build_playback_schedule(_make_song(headers), _TM_120)
    assert _ids(schedule) == [(0, 0), (1, 0), (2, 0)]
    assert any("no matching close" in rec.message for rec in caplog.records)


def test_schedule_unresolved_dal_segno_warns(caplog):
    # Da Segno with no Segno target → warn, advance linearly past the jump.
    headers = [
        _make_header(0),
        _make_header(4, from_direction_name="Da Segno"),
        _make_header(8),
    ]
    with caplog.at_level("WARNING", logger="slopsmith.lib.gp2rs"):
        schedule = _build_playback_schedule(_make_song(headers), _TM_120)
    assert _ids(schedule) == [(0, 0), (1, 0), (2, 0)]
    assert any("no matching target" in rec.message for rec in caplog.records)


def test_schedule_note_time_shifts_under_repeat():
    # ||: A :||×2 with 4/4 at 120 BPM → measure A is 2 s long. First-pass A
    # starts at 0 s; second-pass A starts at 2 s.
    headers = [_make_header(0, is_repeat_open=True, repeat_close=1)]
    schedule = _build_playback_schedule(_make_song(headers), _TM_120)
    assert len(schedule) == 2
    assert schedule[0].output_start_secs == pytest.approx(0.0)
    assert schedule[1].output_start_secs == pytest.approx(2.0)
    # mh_authored_start_secs is the same for both (same source measure).
    assert schedule[0].mh_authored_start_secs == schedule[1].mh_authored_start_secs


def test_schedule_song_length_reflects_expansion():
    # ||: A | B :||×2 → expanded length is 4 measures × 2 s = 8 s, not 4 s.
    headers = [
        _make_header(0, is_repeat_open=True),
        _make_header(4, repeat_close=1),
    ]
    schedule = _build_playback_schedule(_make_song(headers), _TM_120)
    last = schedule[-1]
    last_mh = headers[last.mh_index]
    # Output end = last entry start + last measure duration.
    measure_secs = (last_mh.timeSignature.numerator
                    * (4.0 / last_mh.timeSignature.denominator.value)
                    * GP_TICKS_PER_QUARTER) \
                   / GP_TICKS_PER_QUARTER * (60.0 / 120.0)
    expanded_end = last.output_start_secs + measure_secs
    assert expanded_end == pytest.approx(8.0)


def test_schedule_empty_song():
    # No headers → empty schedule. Should not crash.
    schedule = _build_playback_schedule(_make_song([]), _TM_120)
    assert schedule == []


def test_schedule_irregular_measure_lengths():
    # A 3-quarter pickup followed by two 4-quarter measures, then ||: D :||×2.
    # The pickup is intentionally shorter than its 4/4 time signature would
    # suggest — that's how GP encodes an anacrusis. The schedule must use the
    # tick delta to the next measure as the duration, not the time signature.
    headers = [
        _make_header(0, numerator=4),   # A — 3 quarters long (starts at 0, next at 3)
        _make_header(3, numerator=4),   # B
        _make_header(7, numerator=4),   # C
        _make_header(11, numerator=4, is_repeat_open=True, repeat_close=1),  # D ×2
    ]
    schedule = _build_playback_schedule(_make_song(headers), _TM_120)
    # 120 BPM: 1 quarter = 0.5 s. Output starts:
    #   A: 0.0, B: 1.5 (3 q), C: 3.5 (4 q), D pass 0: 5.5 (4 q), D pass 1: 7.5
    out = [round(e.output_start_secs, 3) for e in schedule]
    assert out == [0.0, 1.5, 3.5, 5.5, 7.5]
