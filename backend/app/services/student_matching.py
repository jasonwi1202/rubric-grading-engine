"""Student auto-assignment matching.

Fuzzy-matches essay signals (filename, DOCX author metadata, header text)
against a class roster to identify the most likely student author.

Rules
-----
- Auto-assign only when **exactly one** student matches with confidence
  >= :data:`AUTO_ASSIGN_THRESHOLD`.
- If two or more students match at or above the threshold the result is
  ``"ambiguous"`` — the essay is held in the unassigned queue and the
  teacher is asked to review manually.
- If no student matches the result is ``"unassigned"``.

Design notes
------------
- This module is **purely functional** — no I/O, no DB access, no logging.
  All I/O sits in ``app.services.essay``.
- No student PII is included in any log output by this module.
- ``rapidfuzz`` is used for fuzzy matching; it is a zero-dependency C
  extension that is fast enough to run synchronously for roster sizes of
  up to a few hundred students.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Literal

from rapidfuzz import fuzz

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Confidence threshold (0.0 – 1.0) above which a match is considered
#: a candidate for auto-assignment.
AUTO_ASSIGN_THRESHOLD: float = 0.85

#: Maximum number of characters from the essay body used as the "header"
#: signal.  Only the first N characters are examined.
HEADER_CHAR_LIMIT: int = 200


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateMatch:
    """A single candidate student match for an uploaded essay.

    Attributes:
        student_id: UUID of the matched student record.
        confidence: Match confidence in the range [0.0, 1.0].
        signal: Which signal produced the winning score — one of
            ``"filename"``, ``"docx_author"``, or ``"header_text"``.
    """

    student_id: uuid.UUID
    confidence: float
    signal: str


@dataclass
class AutoAssignResult:
    """Result of attempting to auto-assign an essay to a student.

    Attributes:
        status: Outcome of the matching attempt —

            * ``"assigned"``  — exactly one candidate above threshold.
            * ``"ambiguous"`` — multiple candidates above threshold; the
              essay is placed in the unassigned queue for manual review.
            * ``"unassigned"`` — no candidate reached the threshold.

        student_id: The matched student's UUID when ``status == "assigned"``;
            ``None`` otherwise.
        match_count: Number of candidates at or above the threshold.
        candidates: All candidates that met the threshold.  **Do not log
            this list** — it contains student UUIDs that map to PII.
    """

    status: Literal["assigned", "ambiguous", "unassigned"]
    student_id: uuid.UUID | None
    match_count: int
    candidates: list[CandidateMatch] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_name(text: str) -> str:
    """Lowercase *text* and collapse common separators to single spaces.

    Handles common filename / metadata patterns:
    - Underscores, hyphens, commas, dots, and pipes → space
    - Runs of whitespace → single space
    """
    text = text.lower()
    text = re.sub(r"[_\-,.|]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _strip_extension(filename: str) -> str:
    """Return the filename stem (basename without extension)."""
    return os.path.splitext(os.path.basename(filename))[0]


def _score_filename(filename_stem: str, student_name: str) -> float:
    """Return best fuzzy score (0.0–1.0) for a filename stem against a student name.

    Applies ``ratio`` and ``token_sort_ratio``; the latter handles reversed
    name ordering (e.g. ``"smith_john"`` matching ``"John Smith"``).
    """
    q = _normalize_name(filename_stem)
    n = _normalize_name(student_name)
    if not q or not n:
        return 0.0
    return (
        max(
            fuzz.ratio(q, n),
            fuzz.token_sort_ratio(q, n),
        )
        / 100.0
    )


def _score_author(author: str, student_name: str) -> float:
    """Return best fuzzy score (0.0–1.0) for DOCX/PDF author metadata.

    Same strategy as filename: ratio + token_sort for reversed names.
    """
    q = _normalize_name(author)
    n = _normalize_name(student_name)
    if not q or not n:
        return 0.0
    return (
        max(
            fuzz.ratio(q, n),
            fuzz.token_sort_ratio(q, n),
        )
        / 100.0
    )


def _score_header(header: str, student_name: str) -> float:
    """Return best fuzzy score (0.0–1.0) for a name found within header text.

    Uses ``partial_ratio`` which finds the best alignment of the shorter
    string (``student_name``) against any equal-length window in the longer
    string (``header``).  This handles headers like::

        "Jane Smith\\nEnglish 101\\nProfessor Jones\\n..."

    where the student name is a substring of a longer passage.
    """
    n = _normalize_name(student_name)
    h = _normalize_name(header)
    if not h or not n:
        return 0.0
    return fuzz.partial_ratio(n, h) / 100.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def match_student(
    roster: list[tuple[uuid.UUID, str]],
    filename: str,
    docx_author: str | None = None,
    header_text: str | None = None,
) -> AutoAssignResult:
    """Attempt to match an uploaded essay to a student on the class roster.

    Checks three signals in priority order for each student:

    1. **Filename stem** — e.g. ``"john_smith.docx"`` → ``"john smith"``.
    2. **DOCX/PDF author metadata** — when available.
    3. **Essay header** — first :data:`HEADER_CHAR_LIMIT` characters of the
       extracted body text.

    For each student the **highest** score across all available signals is
    recorded.  A student becomes a *candidate* when their best score is
    >= :data:`AUTO_ASSIGN_THRESHOLD`.

    Args:
        roster: Sequence of ``(student_id, full_name)`` pairs for all
            actively enrolled students in the assignment's class.
        filename: The original upload filename (not sanitized, not logged).
        docx_author: Author string from DOCX ``core_properties.author``
            (``None`` if unavailable or non-DOCX file).
        header_text: First N characters of extracted essay body text
            (``None`` if not available).

    Returns:
        :class:`AutoAssignResult` describing the outcome.

    Security:
        This function contains no logging.  No student PII leaves this
        function through log statements.
    """
    if not roster:
        return AutoAssignResult(status="unassigned", student_id=None, match_count=0)

    filename_stem = _strip_extension(filename)
    header = (header_text or "")[:HEADER_CHAR_LIMIT]

    candidates: list[CandidateMatch] = []

    for student_id, full_name in roster:
        best_confidence = 0.0
        best_signal = "filename"

        # Signal 1: filename stem
        score = _score_filename(filename_stem, full_name)
        if score > best_confidence:
            best_confidence = score
            best_signal = "filename"

        # Signal 2: DOCX author metadata
        if docx_author:
            score = _score_author(docx_author, full_name)
            if score > best_confidence:
                best_confidence = score
                best_signal = "docx_author"

        # Signal 3: Header text
        if header:
            score = _score_header(header, full_name)
            if score > best_confidence:
                best_confidence = score
                best_signal = "header_text"

        if best_confidence >= AUTO_ASSIGN_THRESHOLD:
            candidates.append(
                CandidateMatch(
                    student_id=student_id,
                    confidence=best_confidence,
                    signal=best_signal,
                )
            )

    match_count = len(candidates)

    if match_count == 0:
        return AutoAssignResult(
            status="unassigned",
            student_id=None,
            match_count=0,
            candidates=[],
        )

    if match_count == 1:
        return AutoAssignResult(
            status="assigned",
            student_id=candidates[0].student_id,
            match_count=1,
            candidates=candidates,
        )

    # match_count >= 2 — ambiguous; never auto-pick
    return AutoAssignResult(
        status="ambiguous",
        student_id=None,
        match_count=match_count,
        candidates=candidates,
    )
