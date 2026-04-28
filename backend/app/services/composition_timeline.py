"""Composition timeline signal extraction — M5-10.

Transforms raw writing-process snapshots (stored in
``essay_versions.writing_snapshots``) into interpretable session timeline
segments, event flags, and summary metrics for teacher review.

This module is intentionally side-effect-free: all I/O is handled by the
callers in ``essay.py`` (DB read/write) and ``routers/essays.py`` (HTTP layer).
The core :func:`analyze_writing_process` function takes a plain list of
snapshot dicts and returns a :class:`CompositionTimeline` dataclass — making
it straightforward to unit-test without any database mocking.

Design notes
~~~~~~~~~~~~
*Session segmentation*
    Two consecutive snapshots are considered part of the same writing session
    when the gap between them is less than :data:`SESSION_GAP_SECONDS` (30 min).
    Gaps at or above this threshold open a new session.

*Paste detection*
    A snapshot step is flagged as a potential paste event when the word-count
    delta (relative to the previous snapshot) is at least
    :data:`PASTE_MIN_WORDS` **and** at least :data:`PASTE_MIN_FRACTION` of the
    essay's final word count.  Both thresholds must be met to avoid false
    positives on very short or very long essays.

*Rapid-completion detection*
    A session is flagged as a rapid-completion event when it contributed at
    least :data:`RAPID_COMPLETION_FRACTION` of the essay's final word count
    within a time window of at most :data:`RAPID_COMPLETION_MAX_SECONDS`.

*Sparse / noisy sequences*
    Snapshots with unparseable timestamps are silently skipped.  An empty
    (or entirely invalid) snapshot list returns a ``CompositionTimeline`` with
    ``has_process_data=False`` and zero sessions.  Single-snapshot essays yield
    one session with ``duration_seconds=0``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Tunable thresholds
# ---------------------------------------------------------------------------

#: Seconds of inactivity between consecutive snapshots that signals a new session.
SESSION_GAP_SECONDS: float = 1800.0  # 30 minutes

#: Minimum word-count delta (from previous snapshot) to consider a paste event.
PASTE_MIN_WORDS: int = 50

#: Minimum fraction of the essay's *final* word count that the word-count delta
#: must represent to flag a paste event.  Prevents false positives on very
#: long essays where a 50-word jump is unremarkable.
PASTE_MIN_FRACTION: float = 0.15

#: A session must have contributed at least this fraction of the essay's final
#: word count to qualify as a rapid-completion event.
RAPID_COMPLETION_FRACTION: float = 0.75

#: Maximum session duration (seconds) for rapid-completion detection.
RAPID_COMPLETION_MAX_SECONDS: float = 1200.0  # 20 minutes


# ---------------------------------------------------------------------------
# Output dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SessionSegment:
    """A contiguous period of writing activity."""

    session_index: int  # 0-based
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    snapshot_count: int
    word_count_start: int
    word_count_end: int
    words_added: int


@dataclass
class PasteEvent:
    """A snapshot step where a large word-count jump was detected."""

    snapshot_seq: int  # seq number of the snapshot where the jump occurred
    occurred_at: datetime
    words_before: int
    words_after: int
    words_added: int
    session_index: int  # which session this occurred in


@dataclass
class RapidCompletionEvent:
    """A session that brought the essay near-complete in a short time."""

    session_index: int
    duration_seconds: float
    words_at_start: int
    words_at_end: int
    completion_fraction: float  # fraction of final word count added in this session


@dataclass
class CompositionTimeline:
    """Full analysis result from :func:`analyze_writing_process`."""

    has_process_data: bool
    session_count: int
    sessions: list[SessionSegment] = field(default_factory=list)
    inter_session_gaps_seconds: list[float] = field(default_factory=list)
    active_writing_seconds: float = 0.0
    total_elapsed_seconds: float = 0.0
    paste_events: list[PasteEvent] = field(default_factory=list)
    rapid_completion_events: list[RapidCompletionEvent] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Type alias for a parsed snapshot triple.
_ParsedSnap = tuple[int, datetime, int]  # (seq, ts, word_count)


def _parse_snapshots(raw: list[dict]) -> list[_ParsedSnap]:
    """Parse raw snapshot dicts into (seq, ts, word_count) triples.

    Snapshots with missing keys, unparseable timestamps, or non-integer seq /
    word_count values are silently skipped so that sparse or partially corrupted
    sequences are handled gracefully.
    """
    parsed: list[_ParsedSnap] = []
    for snap in raw:
        try:
            seq = int(snap["seq"])
            ts_raw = str(snap["ts"])
            ts = datetime.fromisoformat(ts_raw)
            ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
            word_count = max(0, int(snap["word_count"]))
            parsed.append((seq, ts, word_count))
        except (KeyError, ValueError, TypeError):
            continue
    # Defensive sort — snapshots should already be in order, but concurrent
    # browser tabs or clock skew could produce out-of-order timestamps.
    parsed.sort(key=lambda t: t[1])
    return parsed


def _make_session(snaps: list[_ParsedSnap], session_index: int) -> SessionSegment:
    """Build a :class:`SessionSegment` from a non-empty list of parsed snapshots."""
    started_at = snaps[0][1]
    ended_at = snaps[-1][1]
    duration_seconds = max(0.0, (ended_at - started_at).total_seconds())
    word_count_start = snaps[0][2]
    word_count_end = snaps[-1][2]
    return SessionSegment(
        session_index=session_index,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=duration_seconds,
        snapshot_count=len(snaps),
        word_count_start=word_count_start,
        word_count_end=word_count_end,
        words_added=word_count_end - word_count_start,
    )


def _find_session_index(sessions: list[SessionSegment], ts: datetime) -> int:
    """Return the session index that contains *ts*, defaulting to 0."""
    for session in sessions:
        if session.started_at <= ts <= session.ended_at:
            return session.session_index
    return 0


# ---------------------------------------------------------------------------
# Core analysis function
# ---------------------------------------------------------------------------


def analyze_writing_process(
    snapshots: list[dict],
    *,
    session_gap_seconds: float = SESSION_GAP_SECONDS,
    paste_min_words: int = PASTE_MIN_WORDS,
    paste_min_fraction: float = PASTE_MIN_FRACTION,
    rapid_completion_fraction: float = RAPID_COMPLETION_FRACTION,
    rapid_completion_max_seconds: float = RAPID_COMPLETION_MAX_SECONDS,
) -> CompositionTimeline:
    """Analyse raw snapshot data and return a :class:`CompositionTimeline`.

    All threshold parameters have module-level defaults and are exposed as
    keyword arguments so tests can override them without monkeypatching globals.

    Args:
        snapshots: Ordered list of snapshot dicts, each containing at minimum
            ``seq`` (int), ``ts`` (ISO-8601 string), and ``word_count`` (int).
            Extra keys (e.g. ``html_content``) are ignored.
        session_gap_seconds: Gap threshold that opens a new session boundary.
        paste_min_words: Minimum word-count delta to flag a paste event.
        paste_min_fraction: Minimum fraction of final word count the delta
            must represent for paste flagging.
        rapid_completion_fraction: Fraction of final word count a session must
            contribute to be flagged as rapid completion.
        rapid_completion_max_seconds: Maximum session duration for rapid-
            completion detection.

    Returns:
        A fully populated :class:`CompositionTimeline`.  When *snapshots* is
        empty or contains no parseable entries, the returned object has
        ``has_process_data=False`` and zero sessions with all numeric fields
        set to zero.
    """
    if not snapshots:
        return CompositionTimeline(has_process_data=False, session_count=0)

    parsed = _parse_snapshots(snapshots)
    if not parsed:
        return CompositionTimeline(has_process_data=False, session_count=0)

    final_word_count = parsed[-1][2]

    # -----------------------------------------------------------------------
    # Session segmentation
    # -----------------------------------------------------------------------
    sessions: list[SessionSegment] = []
    current: list[_ParsedSnap] = [parsed[0]]

    for i in range(1, len(parsed)):
        gap = (parsed[i][1] - parsed[i - 1][1]).total_seconds()
        if gap > session_gap_seconds:
            sessions.append(_make_session(current, len(sessions)))
            current = [parsed[i]]
        else:
            current.append(parsed[i])

    sessions.append(_make_session(current, len(sessions)))

    # Inter-session gaps (seconds between the end of one session and the start
    # of the next).
    inter_session_gaps: list[float] = [
        max(0.0, (sessions[j].started_at - sessions[j - 1].ended_at).total_seconds())
        for j in range(1, len(sessions))
    ]

    active_writing_seconds = sum(s.duration_seconds for s in sessions)
    total_elapsed_seconds = max(
        0.0,
        (sessions[-1].ended_at - sessions[0].started_at).total_seconds(),
    )

    # -----------------------------------------------------------------------
    # Paste event detection
    # -----------------------------------------------------------------------
    paste_events: list[PasteEvent] = []
    for i in range(1, len(parsed)):
        seq, ts, wc = parsed[i]
        prev_wc = parsed[i - 1][2]
        delta = wc - prev_wc
        if delta < paste_min_words:
            continue
        if final_word_count > 0 and (delta / final_word_count) < paste_min_fraction:
            continue
        session_index = _find_session_index(sessions, ts)
        paste_events.append(
            PasteEvent(
                snapshot_seq=seq,
                occurred_at=ts,
                words_before=prev_wc,
                words_after=wc,
                words_added=delta,
                session_index=session_index,
            )
        )

    # -----------------------------------------------------------------------
    # Rapid-completion detection
    # -----------------------------------------------------------------------
    rapid_completion_events: list[RapidCompletionEvent] = []
    for session in sessions:
        if session.duration_seconds > rapid_completion_max_seconds:
            continue
        if final_word_count == 0:
            continue
        fraction = session.words_added / final_word_count
        if fraction >= rapid_completion_fraction:
            rapid_completion_events.append(
                RapidCompletionEvent(
                    session_index=session.session_index,
                    duration_seconds=session.duration_seconds,
                    words_at_start=session.word_count_start,
                    words_at_end=session.word_count_end,
                    completion_fraction=fraction,
                )
            )

    return CompositionTimeline(
        has_process_data=True,
        session_count=len(sessions),
        sessions=sessions,
        inter_session_gaps_seconds=inter_session_gaps,
        active_writing_seconds=active_writing_seconds,
        total_elapsed_seconds=total_elapsed_seconds,
        paste_events=paste_events,
        rapid_completion_events=rapid_completion_events,
    )
