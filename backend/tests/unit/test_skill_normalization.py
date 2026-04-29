"""Unit tests for app/services/skill_normalization.py.

Tests cover:
- normalize_criterion_name: exact canonical name → identity mapping
- normalize_criterion_name: exact variant match → correct dimension
- normalize_criterion_name: fuzzy (near-typo) variant match → correct dimension
- normalize_criterion_name: common shorthand (e.g. "claim" → "thesis")
- normalize_criterion_name: completely unmapped criterion → "other"
- normalize_criterion_name: case-insensitive matching
- normalize_criterion_name: custom mapping (config override behaviour)
- normalize_criterion_name: threshold boundary (just above / just below)
- normalize_criterion_name: empty string → "other"
- load_skill_mapping: loads the bundled default config successfully
- load_skill_mapping: loads a custom config path
- load_skill_mapping: raises FileNotFoundError for missing file
- load_skill_mapping: raises ValueError for malformed JSON
- load_skill_mapping: raises ValueError when JSON root is not an object
- _best_variant_score: returns 0.0 for empty variant list

No student PII in any fixture.
No network or database I/O.
File I/O occurs in load_skill_mapping tests (both bundled default-config and
custom-path cases) and implicitly when normalize_criterion_name loads the
bundled default via importlib.resources.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.skill_normalization import (
    CANONICAL_DIMENSIONS,
    NORMALIZATION_MATCH_THRESHOLD,
    OTHER_DIMENSION,
    _best_variant_score,
    load_skill_mapping,
    normalize_criterion_name,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def minimal_mapping() -> dict[str, list[str]]:
    """A small, deterministic mapping used for config-override tests."""
    return {
        "thesis": ["Thesis Statement", "Central Claim", "Claim"],
        "evidence": ["Evidence Use", "Supporting Details"],
        "mechanics": ["Grammar", "Conventions"],
    }


# ---------------------------------------------------------------------------
# load_skill_mapping — bundled default
# ---------------------------------------------------------------------------


class TestLoadSkillMappingDefault:
    def test_returns_dict(self) -> None:
        mapping = load_skill_mapping()
        assert isinstance(mapping, dict)

    def test_contains_all_canonical_dimensions_except_other(self) -> None:
        mapping = load_skill_mapping()
        expected = CANONICAL_DIMENSIONS - {OTHER_DIMENSION}
        for dim in expected:
            assert dim in mapping, f"Expected dimension '{dim}' in default mapping"

    def test_each_dimension_has_nonempty_variant_list(self) -> None:
        mapping = load_skill_mapping()
        for dim, variants in mapping.items():
            assert isinstance(variants, list), f"{dim}: expected list of variants"
            assert len(variants) > 0, f"{dim}: variant list must not be empty"

    def test_all_variants_are_strings(self) -> None:
        mapping = load_skill_mapping()
        for dim, variants in mapping.items():
            for v in variants:
                assert isinstance(v, str), f"{dim}: variant {v!r} is not a string"


# ---------------------------------------------------------------------------
# load_skill_mapping — custom path
# ---------------------------------------------------------------------------


class TestLoadSkillMappingCustomPath:
    def test_loads_custom_json_file(self, tmp_path: Path) -> None:
        config = {"thesis": ["Central Claim", "Thesis Statement"]}
        config_file = tmp_path / "custom_mapping.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")

        mapping = load_skill_mapping(config_file)
        assert mapping == config

    def test_accepts_path_object(self, tmp_path: Path) -> None:
        config = {"mechanics": ["Grammar"]}
        config_file = tmp_path / "mapping.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")

        mapping = load_skill_mapping(Path(config_file))
        assert "mechanics" in mapping

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        config = {"voice": ["Style"]}
        config_file = tmp_path / "mapping.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")

        mapping = load_skill_mapping(str(config_file))
        assert "voice" in mapping

    def test_raises_file_not_found_for_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError, match="Skill normalization config not found"):
            load_skill_mapping("/nonexistent/path/mapping.json")

    def test_raises_value_error_for_invalid_json(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json {{{{", encoding="utf-8")

        with pytest.raises(ValueError, match="Invalid JSON"):
            load_skill_mapping(bad_file)

    def test_raises_value_error_when_root_is_not_object(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "array.json"
        bad_file.write_text(json.dumps(["thesis", "evidence"]), encoding="utf-8")

        with pytest.raises(ValueError, match="JSON object"):
            load_skill_mapping(bad_file)

    def test_raises_value_error_when_variants_is_not_list(self, tmp_path: Path) -> None:
        # A string value instead of a list would silently iterate characters
        # without the type check — the validator must catch this early.
        bad_file = tmp_path / "bad_variants.json"
        bad_file.write_text(json.dumps({"thesis": "Thesis Statement"}), encoding="utf-8")
        with pytest.raises(ValueError, match="list of variants"):
            load_skill_mapping(bad_file)


# ---------------------------------------------------------------------------
# load_skill_mapping — mutation safety
# ---------------------------------------------------------------------------


class TestLoadSkillMappingMutationSafety:
    def test_mutating_returned_mapping_does_not_affect_cache(self, tmp_path: Path) -> None:
        """Callers that mutate the returned dict must not corrupt the cache."""
        config = {"thesis": ["Thesis Statement", "Central Claim"]}
        config_file = tmp_path / "mapping.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")

        first = load_skill_mapping(config_file)
        # Mutate the returned mapping.
        first["thesis"].append("Injected Variant")
        first["new_dimension"] = ["Something"]

        # A second call must still return the original clean mapping.
        second = load_skill_mapping(config_file)
        assert "new_dimension" not in second
        assert "Injected Variant" not in second.get("thesis", [])

    def test_each_call_returns_independent_copy(self, tmp_path: Path) -> None:
        """Two successive calls must return distinct objects."""
        config = {"evidence": ["Evidence Use"]}
        config_file = tmp_path / "mapping.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")

        first = load_skill_mapping(config_file)
        second = load_skill_mapping(config_file)
        assert first is not second
        assert first["evidence"] is not second["evidence"]


class TestBestVariantScore:
    def test_empty_variant_list_returns_zero(self) -> None:
        assert _best_variant_score("thesis", []) == 0.0

    def test_exact_match_returns_one(self) -> None:
        score = _best_variant_score("thesis statement", ["Thesis Statement"])
        assert score == pytest.approx(1.0)

    def test_returns_float_between_zero_and_one(self) -> None:
        score = _best_variant_score("something", ["Thesis Statement"])
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# normalize_criterion_name — exact canonical name
# ---------------------------------------------------------------------------


class TestNormalizeCriterionNameExactCanonical:
    @pytest.mark.parametrize(
        "dimension",
        sorted(CANONICAL_DIMENSIONS - {OTHER_DIMENSION}),
    )
    def test_canonical_name_maps_to_itself(self, dimension: str) -> None:
        result = normalize_criterion_name(dimension)
        assert result == dimension

    @pytest.mark.parametrize(
        "dimension",
        sorted(CANONICAL_DIMENSIONS - {OTHER_DIMENSION}),
    )
    def test_canonical_name_uppercase_maps_to_itself(self, dimension: str) -> None:
        result = normalize_criterion_name(dimension.upper())
        assert result == dimension

    def test_other_maps_to_other(self) -> None:
        result = normalize_criterion_name("other")
        assert result == OTHER_DIMENSION


# ---------------------------------------------------------------------------
# normalize_criterion_name — exact variant matches (from bundled config)
# ---------------------------------------------------------------------------


class TestNormalizeCriterionNameExactVariant:
    @pytest.mark.parametrize(
        "criterion,expected_dimension",
        [
            ("Thesis Statement", "thesis"),
            ("Main Argument", "thesis"),
            ("Central Claim", "thesis"),
            ("Evidence Use", "evidence"),
            ("Use of Textual Evidence", "evidence"),
            ("Supporting Details", "evidence"),
            ("Organization", "organization"),
            ("Essay Structure", "organization"),
            ("Flow", "organization"),
            ("Analysis", "analysis"),
            ("Critical Thinking", "analysis"),
            ("Depth of Analysis", "analysis"),
            ("Grammar", "mechanics"),
            ("Conventions", "mechanics"),
            ("Spelling and Grammar", "mechanics"),
            ("Voice", "voice"),
            ("Style", "voice"),
            ("Word Choice", "voice"),
        ],
    )
    def test_exact_variant_mapped_correctly(self, criterion: str, expected_dimension: str) -> None:
        result = normalize_criterion_name(criterion)
        assert result == expected_dimension, (
            f"Expected '{criterion}' → '{expected_dimension}', got '{result}'"
        )


# ---------------------------------------------------------------------------
# normalize_criterion_name — case insensitivity
# ---------------------------------------------------------------------------


class TestNormalizeCriterionNameCaseInsensitive:
    def test_all_uppercase_variant(self) -> None:
        assert normalize_criterion_name("THESIS STATEMENT") == "thesis"

    def test_mixed_case_variant(self) -> None:
        assert normalize_criterion_name("tHeSiS StAtEmEnT") == "thesis"

    def test_all_lowercase_variant(self) -> None:
        assert normalize_criterion_name("grammar") == "mechanics"


# ---------------------------------------------------------------------------
# normalize_criterion_name — fuzzy matches (common shorthand / near-typos)
# ---------------------------------------------------------------------------


class TestNormalizeCriterionNameFuzzy:
    def test_claim_maps_to_thesis(self) -> None:
        """'claim' is a common shorthand — must map to 'thesis'."""
        result = normalize_criterion_name("claim")
        assert result == "thesis", f"Expected 'claim' → 'thesis', got '{result}'"

    def test_near_typo_grammer_maps_to_mechanics(self) -> None:
        """'grammer' (common misspelling) should still match 'grammar'."""
        result = normalize_criterion_name("grammer")
        assert result == "mechanics", f"Expected 'grammer' → 'mechanics', got '{result}'"

    def test_near_typo_thesis_statment_maps_to_thesis(self) -> None:
        """Single-character deletion typo should still resolve correctly."""
        result = normalize_criterion_name("Thesis Statment")
        assert result == "thesis"

    def test_partial_match_evidence_maps_to_evidence(self) -> None:
        result = normalize_criterion_name("Evidence")
        assert result == "evidence"

    def test_plural_mechanics_maps_to_mechanics(self) -> None:
        result = normalize_criterion_name("Writing Mechanics")
        assert result == "mechanics"


# ---------------------------------------------------------------------------
# normalize_criterion_name — unmapped fallback → "other"
# ---------------------------------------------------------------------------


class TestNormalizeCriterionNameOtherFallback:
    def test_completely_unrelated_criterion_maps_to_other(self) -> None:
        result = normalize_criterion_name("Watercolor Brushstroke Technique")
        assert result == OTHER_DIMENSION

    def test_empty_string_maps_to_other(self) -> None:
        result = normalize_criterion_name("")
        assert result == OTHER_DIMENSION

    def test_whitespace_only_maps_to_other(self) -> None:
        result = normalize_criterion_name("   ")
        assert result == OTHER_DIMENSION

    def test_random_noise_maps_to_other(self) -> None:
        result = normalize_criterion_name("xyzzy1234_qwerty")
        assert result == OTHER_DIMENSION

    def test_unmapped_logs_info(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        with caplog.at_level(logging.INFO, logger="app.services.skill_normalization"):
            result = normalize_criterion_name("completely unknown criterion xyz987")
        assert result == OTHER_DIMENSION
        assert any(
            "could not be mapped" in record.message
            and "canonical skill dimension" in record.message
            for record in caplog.records
        )


# ---------------------------------------------------------------------------
# normalize_criterion_name — config override behaviour
# ---------------------------------------------------------------------------


class TestNormalizeCriterionNameConfigOverride:
    def test_custom_mapping_overrides_default(self, minimal_mapping: dict[str, list[str]]) -> None:
        """Custom mapping is used when supplied — default is not loaded."""
        # "Depth of Analysis" is only in the default config; minimal_mapping
        # does not include "analysis" at all, so it should fall back to "other".
        result = normalize_criterion_name("Depth of Analysis", mapping=minimal_mapping)
        assert result == OTHER_DIMENSION

    def test_custom_mapping_resolves_its_own_variants(
        self, minimal_mapping: dict[str, list[str]]
    ) -> None:
        result = normalize_criterion_name("Central Claim", mapping=minimal_mapping)
        assert result == "thesis"

    def test_custom_mapping_from_file(self, tmp_path: Path) -> None:
        config = {"science_claim": ["Hypothesis", "Research Question", "Scientific Claim"]}
        config_file = tmp_path / "science_mapping.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")

        custom_mapping = load_skill_mapping(config_file)
        result = normalize_criterion_name("Hypothesis", mapping=custom_mapping)
        assert result == "science_claim"

    def test_custom_mapping_unknown_criterion_falls_back_to_other(
        self, minimal_mapping: dict[str, list[str]]
    ) -> None:
        # "Tone" is a known variant of "voice" in the default config but
        # the minimal_mapping does not include "voice" at all, and "Tone" is
        # not itself a canonical dimension name — so it must fall to "other".
        result = normalize_criterion_name("Tone", mapping=minimal_mapping)
        assert result == OTHER_DIMENSION

    def test_none_mapping_uses_default(self) -> None:
        """Passing mapping=None (the default) loads the bundled config."""
        result = normalize_criterion_name("Thesis Statement", mapping=None)
        assert result == "thesis"


# ---------------------------------------------------------------------------
# normalize_criterion_name — threshold boundary
# ---------------------------------------------------------------------------


class TestNormalizeCriterionNameThresholdBoundary:
    def test_score_exactly_at_threshold_is_mapped(
        self, minimal_mapping: dict[str, list[str]]
    ) -> None:
        with patch(
            "app.services.skill_normalization._best_variant_score",
            return_value=NORMALIZATION_MATCH_THRESHOLD,
        ):
            result = normalize_criterion_name("any criterion", mapping=minimal_mapping)
        # Result must be one of the dimensions present in the custom mapping.
        assert result in minimal_mapping

    def test_score_just_below_threshold_falls_to_other(
        self, minimal_mapping: dict[str, list[str]]
    ) -> None:
        below = NORMALIZATION_MATCH_THRESHOLD - 0.01
        with patch(
            "app.services.skill_normalization._best_variant_score",
            return_value=below,
        ):
            result = normalize_criterion_name("any criterion", mapping=minimal_mapping)
        assert result == OTHER_DIMENSION

    def test_custom_threshold_zero_maps_everything(
        self, minimal_mapping: dict[str, list[str]]
    ) -> None:
        """A threshold of 0.0 means even zero-scoring criteria are mapped."""
        result = normalize_criterion_name("xyzzy_nomatch", mapping=minimal_mapping, threshold=0.0)
        # With threshold=0, the first dimension wins (any score ≥ 0).
        assert result != OTHER_DIMENSION

    def test_threshold_zero_still_maps_when_all_scores_are_zero(
        self, minimal_mapping: dict[str, list[str]]
    ) -> None:
        """When threshold=0.0 and every candidate scores exactly 0.0, the first
        dimension in the mapping must win (not fall through to 'other')."""
        with patch(
            "app.services.skill_normalization._best_variant_score",
            return_value=0.0,
        ):
            result = normalize_criterion_name(
                "completely unrelated", mapping=minimal_mapping, threshold=0.0
            )
        first_dimension = next(iter(minimal_mapping))
        assert result == first_dimension

    def test_custom_threshold_one_maps_only_exact_matches(
        self, minimal_mapping: dict[str, list[str]]
    ) -> None:
        """A threshold of 1.0 accepts only perfect matches."""
        # "Grammar" is an exact variant of "mechanics" in the minimal mapping.
        result = normalize_criterion_name("Grammar", mapping=minimal_mapping, threshold=1.0)
        assert result == "mechanics"

    def test_custom_threshold_one_rejects_near_matches(
        self, minimal_mapping: dict[str, list[str]]
    ) -> None:
        result = normalize_criterion_name("Grammer", mapping=minimal_mapping, threshold=1.0)
        assert result == OTHER_DIMENSION

    def test_threshold_below_zero_raises_value_error(
        self, minimal_mapping: dict[str, list[str]]
    ) -> None:
        with pytest.raises(ValueError, match="threshold must be between"):
            normalize_criterion_name("Grammar", mapping=minimal_mapping, threshold=-0.1)

    def test_threshold_above_one_raises_value_error(
        self, minimal_mapping: dict[str, list[str]]
    ) -> None:
        with pytest.raises(ValueError, match="threshold must be between"):
            normalize_criterion_name("Grammar", mapping=minimal_mapping, threshold=1.1)

    def test_threshold_exactly_zero_is_accepted(
        self, minimal_mapping: dict[str, list[str]]
    ) -> None:
        """Boundary: threshold=0.0 is a valid inclusive lower bound."""
        result = normalize_criterion_name("Grammar", mapping=minimal_mapping, threshold=0.0)
        assert isinstance(result, str)

    def test_threshold_exactly_one_is_accepted(self, minimal_mapping: dict[str, list[str]]) -> None:
        """Boundary: threshold=1.0 is a valid inclusive upper bound."""
        result = normalize_criterion_name("Grammar", mapping=minimal_mapping, threshold=1.0)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# normalize_criterion_name — return value is always a canonical dimension
# ---------------------------------------------------------------------------


class TestNormalizeCriterionNameReturnType:
    @pytest.mark.parametrize(
        "criterion",
        [
            "Thesis Statement",
            "completely unknown criterion 9999",
            "",
            "organization",
            "VOICE",
            "claim",
        ],
    )
    def test_always_returns_canonical_dimension(self, criterion: str) -> None:
        result = normalize_criterion_name(criterion)
        assert result in CANONICAL_DIMENSIONS, (
            f"normalize_criterion_name({criterion!r}) returned {result!r}, "
            f"which is not in CANONICAL_DIMENSIONS"
        )
