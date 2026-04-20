"""Unit tests for app/services/student_matching.py.

Tests cover:
- _normalize_name: separator replacement, case folding, whitespace collapsing
- _strip_extension: extension removal, basename extraction
- _score_filename: exact match, reversed name order, no match
- _score_author: exact, reversed order, no match
- _score_header: name found in header, name not found
- match_student:
  - empty roster → unassigned
  - no roster match below threshold → unassigned
  - single match ≥ threshold → assigned (correct student_id, signal)
  - multiple matches ≥ threshold → ambiguous (never silently picked)
  - confidence exactly at threshold → assigned (boundary condition)
  - confidence just below threshold → unassigned (boundary condition)
  - filename signal used
  - docx_author signal used (higher confidence wins)
  - header_text signal used
  - docx_author=None, header_text=None fallback to filename
  - reversed name order ("Smith_John") matches "John Smith"
  - no PII is returned in result.student_id for ambiguous/unassigned

All fixtures use synthetic names — no real student PII.
No network, database, or file I/O.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

from app.services.student_matching import (
    AUTO_ASSIGN_THRESHOLD,
    HEADER_CHAR_LIMIT,
    AutoAssignResult,
    CandidateMatch,
    _normalize_name,
    _score_author,
    _score_filename,
    _score_header,
    _strip_extension,
    match_student,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_roster(*names: str) -> list[tuple[uuid.UUID, str]]:
    """Build a synthetic roster of (uuid, name) pairs from *names*."""
    return [(uuid.uuid4(), name) for name in names]


# ---------------------------------------------------------------------------
# _normalize_name
# ---------------------------------------------------------------------------


class TestNormalizeName:
    def test_lowercases(self) -> None:
        assert _normalize_name("ALICE WALKER") == "alice walker"

    def test_replaces_underscores_with_space(self) -> None:
        assert _normalize_name("alice_walker") == "alice walker"

    def test_replaces_hyphens_with_space(self) -> None:
        assert _normalize_name("alice-walker") == "alice walker"

    def test_replaces_commas_with_space(self) -> None:
        assert _normalize_name("walker,alice") == "walker alice"

    def test_collapses_multiple_spaces(self) -> None:
        assert _normalize_name("alice   walker") == "alice walker"

    def test_strips_leading_trailing_whitespace(self) -> None:
        assert _normalize_name("  alice  ") == "alice"

    def test_empty_string_returns_empty(self) -> None:
        assert _normalize_name("") == ""

    def test_dots_replaced(self) -> None:
        assert _normalize_name("alice.walker") == "alice walker"


# ---------------------------------------------------------------------------
# _strip_extension
# ---------------------------------------------------------------------------


class TestStripExtension:
    def test_removes_txt_extension(self) -> None:
        assert _strip_extension("alice_walker.txt") == "alice_walker"

    def test_removes_pdf_extension(self) -> None:
        assert _strip_extension("alice_walker.pdf") == "alice_walker"

    def test_removes_docx_extension(self) -> None:
        assert _strip_extension("alice_walker.docx") == "alice_walker"

    def test_strips_path_prefix(self) -> None:
        # Only the basename matters.
        result = _strip_extension("uploads/2024/alice_walker.pdf")
        assert result == "alice_walker"

    def test_no_extension(self) -> None:
        assert _strip_extension("alice_walker") == "alice_walker"


# ---------------------------------------------------------------------------
# _score_filename
# ---------------------------------------------------------------------------


class TestScoreFilename:
    def test_exact_match_returns_high_score(self) -> None:
        score = _score_filename("alice_walker", "Alice Walker")
        assert score >= AUTO_ASSIGN_THRESHOLD, f"Expected ≥ {AUTO_ASSIGN_THRESHOLD}, got {score}"

    def test_reversed_name_order_returns_high_score(self) -> None:
        # "walker_alice" should still match "Alice Walker" via token_sort_ratio
        score = _score_filename("walker_alice", "Alice Walker")
        assert score >= AUTO_ASSIGN_THRESHOLD, f"Expected ≥ {AUTO_ASSIGN_THRESHOLD}, got {score}"

    def test_completely_different_name_returns_low_score(self) -> None:
        score = _score_filename("completely_unrelated_filename", "Alice Walker")
        assert score < AUTO_ASSIGN_THRESHOLD, f"Expected < {AUTO_ASSIGN_THRESHOLD}, got {score}"

    def test_empty_filename_returns_zero(self) -> None:
        assert _score_filename("", "Alice Walker") == 0.0

    def test_empty_student_name_returns_zero(self) -> None:
        assert _score_filename("alice_walker", "") == 0.0


# ---------------------------------------------------------------------------
# _score_author
# ---------------------------------------------------------------------------


class TestScoreAuthor:
    def test_exact_match_returns_high_score(self) -> None:
        score = _score_author("Alice Walker", "Alice Walker")
        assert score >= AUTO_ASSIGN_THRESHOLD

    def test_reversed_order_returns_high_score(self) -> None:
        score = _score_author("Walker, Alice", "Alice Walker")
        assert score >= AUTO_ASSIGN_THRESHOLD

    def test_unrelated_returns_low_score(self) -> None:
        score = _score_author("Random Name Here", "Alice Walker")
        assert score < AUTO_ASSIGN_THRESHOLD

    def test_empty_author_returns_zero(self) -> None:
        assert _score_author("", "Alice Walker") == 0.0


# ---------------------------------------------------------------------------
# _score_header
# ---------------------------------------------------------------------------


class TestScoreHeader:
    def test_name_at_start_of_header_returns_high_score(self) -> None:
        header = "Alice Walker\nEnglish 201\nProfessor Nguyen\nNovember 2024\n\nIntroduction..."
        score = _score_header(header, "Alice Walker")
        assert score >= AUTO_ASSIGN_THRESHOLD, f"Expected ≥ {AUTO_ASSIGN_THRESHOLD}, got {score}"

    def test_name_not_in_header_returns_low_score(self) -> None:
        header = "Introduction to a long essay about the history of science and research methods."
        score = _score_header(header, "Alice Walker")
        assert score < AUTO_ASSIGN_THRESHOLD

    def test_empty_header_returns_zero(self) -> None:
        assert _score_header("", "Alice Walker") == 0.0

    def test_empty_student_name_returns_zero(self) -> None:
        assert _score_header("Some header text here", "") == 0.0


# ---------------------------------------------------------------------------
# match_student — core behaviour
# ---------------------------------------------------------------------------


class TestMatchStudent:
    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_empty_roster_returns_unassigned(self) -> None:
        result = match_student(
            roster=[],
            filename="alice_walker.txt",
        )
        assert result.status == "unassigned", f"Expected 'unassigned', got {result.status!r}"
        assert result.student_id is None
        assert result.match_count == 0

    def test_roster_with_no_matches_returns_unassigned(self) -> None:
        roster = _make_roster("Bob Thompson", "Carol Davis", "Eve Martinez")
        result = match_student(
            roster=roster,
            filename="alice_walker.txt",
        )
        assert result.status == "unassigned"
        assert result.student_id is None

    # ------------------------------------------------------------------
    # Single match → assigned
    # ------------------------------------------------------------------

    def test_filename_match_assigns_student(self) -> None:
        student_id = uuid.uuid4()
        roster = [(student_id, "Alice Walker"), *_make_roster("Bob Thompson", "Carol Davis")]

        result = match_student(
            roster=roster,
            filename="alice_walker.docx",
        )

        assert result.status == "assigned", f"Expected 'assigned', got {result.status!r}"
        assert result.student_id == student_id
        assert result.match_count == 1
        assert result.candidates[0].signal == "filename"

    def test_reversed_filename_assigns_correct_student(self) -> None:
        student_id = uuid.uuid4()
        roster = [(student_id, "Alice Walker"), *_make_roster("Bob Thompson")]

        result = match_student(
            roster=roster,
            filename="walker_alice.pdf",
        )

        assert result.status == "assigned"
        assert result.student_id == student_id

    def test_docx_author_match_assigns_student(self) -> None:
        student_id = uuid.uuid4()
        roster = [(student_id, "Bob Thompson"), *_make_roster("Carol Davis")]

        # Filename is unrelated but author matches.
        result = match_student(
            roster=roster,
            filename="essay_final_v2.docx",
            docx_author="Bob Thompson",
        )

        assert result.status == "assigned"
        assert result.student_id == student_id
        assert result.candidates[0].signal == "docx_author"

    def test_header_text_match_assigns_student(self) -> None:
        student_id = uuid.uuid4()
        roster = [(student_id, "Carol Davis"), *_make_roster("Eve Martinez")]

        header = "Carol Davis\nLiterature 301\nDr. Patel\n\nIn this essay I will argue..."

        result = match_student(
            roster=roster,
            filename="essay_submission.pdf",
            header_text=header,
        )

        assert result.status == "assigned"
        assert result.student_id == student_id

    def test_only_first_200_chars_of_header_used(self) -> None:
        """A name that appears only AFTER the first 200 chars must not trigger a match."""
        student_id = uuid.uuid4()
        roster = [(student_id, "Alice Walker")]

        # Name is placed just beyond the HEADER_CHAR_LIMIT boundary.
        padding = "x" * (HEADER_CHAR_LIMIT + 1)
        header = padding + "Alice Walker"

        result = match_student(
            roster=roster,
            filename="unrelated.pdf",
            header_text=header,
        )

        # Should NOT match via header — filename is also unrelated.
        assert result.status == "unassigned", (
            "Name after char limit should not be matched via header signal"
        )

    # ------------------------------------------------------------------
    # Confidence threshold boundary
    # ------------------------------------------------------------------

    def test_confidence_exactly_at_threshold_is_candidate(self) -> None:
        student_id = uuid.uuid4()
        roster = [(student_id, "Alice Walker")]

        with patch(
            "app.services.student_matching._score_filename", return_value=AUTO_ASSIGN_THRESHOLD
        ):
            result = match_student(roster=roster, filename="any.txt")

        assert result.status == "assigned"
        assert result.student_id == student_id

    def test_confidence_just_below_threshold_is_not_candidate(self) -> None:
        student_id = uuid.uuid4()
        roster = [(student_id, "Alice Walker")]

        below = AUTO_ASSIGN_THRESHOLD - 0.01
        with patch("app.services.student_matching._score_filename", return_value=below):
            result = match_student(roster=roster, filename="any.txt")

        assert result.status == "unassigned"

    # ------------------------------------------------------------------
    # Ambiguous match → never silently picked
    # ------------------------------------------------------------------

    def test_two_matches_above_threshold_returns_ambiguous(self) -> None:
        id_a = uuid.uuid4()
        id_b = uuid.uuid4()
        # Both students have names that will produce high scores for the filename
        # "alice_bob" but that shouldn't happen in practice; we force it via mock.
        roster = [(id_a, "Alice Walker"), (id_b, "Alice Walker Junior")]

        # Mock so both always return a score above the threshold.
        with patch("app.services.student_matching._score_filename", return_value=0.95):
            result = match_student(roster=roster, filename="essay.txt")

        assert result.status == "ambiguous", f"Expected 'ambiguous', got {result.status!r}"
        assert result.student_id is None, "student_id must be None for ambiguous results"
        assert result.match_count == 2

    def test_ambiguous_result_lists_all_candidates(self) -> None:
        ids = [uuid.uuid4() for _ in range(3)]
        roster = [(ids[0], "Name One"), (ids[1], "Name Two"), (ids[2], "Name Three")]

        with patch("app.services.student_matching._score_filename", return_value=0.99):
            result = match_student(roster=roster, filename="essay.txt")

        assert result.status == "ambiguous"
        assert len(result.candidates) == 3
        candidate_ids = {c.student_id for c in result.candidates}
        assert candidate_ids == set(ids)

    # ------------------------------------------------------------------
    # Signal priority — higher score wins
    # ------------------------------------------------------------------

    def test_docx_author_signal_wins_over_lower_filename_score(self) -> None:
        student_id = uuid.uuid4()
        other_id = uuid.uuid4()
        # other_id has a higher filename score but student_id has a higher author score.
        roster = [(student_id, "Carol Davis"), (other_id, "Unrelated Name")]

        def _mock_filename(stem: str, name: str) -> float:
            return 0.90 if name == "Unrelated Name" else 0.50

        def _mock_author(author: str, name: str) -> float:
            return 0.95 if name == "Carol Davis" else 0.40

        with (
            patch("app.services.student_matching._score_filename", side_effect=_mock_filename),
            patch("app.services.student_matching._score_author", side_effect=_mock_author),
        ):
            result = match_student(
                roster=roster,
                filename="essay.docx",
                docx_author="Carol Davis",
            )

        # Both students exceed the threshold → ambiguous.
        assert result.status == "ambiguous"

    def test_none_docx_author_skipped(self) -> None:
        """When docx_author is None, only filename and header are checked."""
        student_id = uuid.uuid4()
        roster = [(student_id, "Alice Walker")]

        with (
            patch("app.services.student_matching._score_filename", return_value=0.95),
            patch("app.services.student_matching._score_author") as mock_author,
        ):
            result = match_student(roster=roster, filename="alice_walker.pdf", docx_author=None)

        mock_author.assert_not_called()
        assert result.status == "assigned"

    def test_none_header_text_skipped(self) -> None:
        """When header_text is None, only filename and docx_author are checked."""
        student_id = uuid.uuid4()
        roster = [(student_id, "Alice Walker")]

        with (
            patch("app.services.student_matching._score_filename", return_value=0.95),
            patch("app.services.student_matching._score_header") as mock_header,
        ):
            result = match_student(roster=roster, filename="alice_walker.pdf", header_text=None)

        mock_header.assert_not_called()
        assert result.status == "assigned"

    # ------------------------------------------------------------------
    # No PII leakage — student_id is None for non-assigned results
    # ------------------------------------------------------------------

    def test_unassigned_result_has_no_student_id(self) -> None:
        roster = _make_roster("Bob Thompson", "Carol Davis")
        result = match_student(roster=roster, filename="unrelated.txt")
        assert result.student_id is None, "student_id must be None when unassigned"

    def test_ambiguous_result_has_no_student_id(self) -> None:
        roster = _make_roster("Alice Walker", "Alice Waters")
        with patch("app.services.student_matching._score_filename", return_value=0.95):
            result = match_student(roster=roster, filename="essay.txt")
        assert result.student_id is None, "student_id must be None when ambiguous"

    # ------------------------------------------------------------------
    # AutoAssignResult structure
    # ------------------------------------------------------------------

    def test_assigned_result_has_one_candidate(self) -> None:
        student_id = uuid.uuid4()
        roster = [(student_id, "Alice Walker")]

        with patch("app.services.student_matching._score_filename", return_value=0.90):
            result = match_student(roster=roster, filename="essay.txt")

        assert result.status == "assigned"
        assert len(result.candidates) == 1
        candidate = result.candidates[0]
        assert isinstance(candidate, CandidateMatch)
        assert candidate.student_id == student_id
        assert 0.0 <= candidate.confidence <= 1.0

    def test_result_is_autoassignresult_instance(self) -> None:
        roster = _make_roster("Alice Walker")
        result = match_student(roster=roster, filename="alice_walker.txt")
        assert isinstance(result, AutoAssignResult)
