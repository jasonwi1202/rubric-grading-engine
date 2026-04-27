"""Skill normalization layer.

Maps rubric criterion names to canonical skill dimensions used by Student
Intelligence (student skill profiles and class insights aggregation).

Canonical dimensions
--------------------
``thesis``, ``evidence``, ``organization``, ``analysis``, ``mechanics``,
``voice``, ``other``

The mapping between known criterion-name variants and canonical dimensions
is stored in ``skill_normalization_config.json``, *not* hardcoded here.
A custom config path can be supplied via :func:`load_skill_mapping`, or a
preloaded ``mapping`` dict can be passed directly to
:func:`normalize_criterion_name` — useful for testing and for supporting
subjects beyond English writing without code changes.

Design notes
------------
- This module is **purely functional** — no database access, no HTTP concerns.
- ``rapidfuzz`` is used for fuzzy matching (already a project dependency).
- Criterion names are teacher-created rubric fields, not student PII; however,
  raw criterion content is never emitted in log messages as a precaution.
- The normalizer is reusable by both the skill-profile update task and the
  class-insights aggregation service.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Final

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: All recognised canonical skill dimension names.
CANONICAL_DIMENSIONS: Final[frozenset[str]] = frozenset(
    {"thesis", "evidence", "organization", "analysis", "mechanics", "voice", "other"}
)

#: Fallback dimension for criterion names that cannot be mapped.
OTHER_DIMENSION: Final[str] = "other"

#: Fuzzy-match threshold (0.0–1.0).  A criterion must score at or above this
#: value against at least one known variant to be mapped to that dimension.
#: Matches the threshold documented in ``docs/architecture/data-ingestion.md``.
NORMALIZATION_MATCH_THRESHOLD: Final[float] = 0.80

#: Path to the bundled default mapping config, relative to this file.
_DEFAULT_CONFIG_PATH: Final[Path] = (
    Path(__file__).parent.parent / "skill_normalization_config.json"
)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_skill_mapping(config_path: Path | str | None = None) -> dict[str, list[str]]:
    """Load and return the skill mapping from a JSON config file.

    Args:
        config_path: Path to a JSON config file whose keys are canonical
            dimension names and whose values are lists of known
            criterion-name variants.  When ``None``, the bundled
            ``skill_normalization_config.json`` is used.

    Returns:
        Mapping of ``{canonical_dimension: [variant, ...]}``.

    Raises:
        FileNotFoundError: If the specified config file does not exist.
        ValueError: If the file contains invalid JSON or an unexpected
            top-level structure.
    """
    path = Path(config_path) if config_path is not None else _DEFAULT_CONFIG_PATH
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Skill normalization config not found: {path}"
        ) from None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in skill normalization config {path}: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise ValueError(
            "Skill normalization config must be a JSON object mapping dimension "
            f"names to variant lists; got {type(data).__name__}"
        )

    result: dict[str, list[str]] = {}
    for k, vs in data.items():
        if not isinstance(vs, list):
            raise ValueError(
                f"Expected a list of variants for dimension {k!r}; "
                f"got {type(vs).__name__}"
            )
        result[str(k)] = [str(v) for v in vs]
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _best_variant_score(criterion_lower: str, variants: list[str]) -> float:
    """Return the best fuzzy score (0.0–1.0) for *criterion_lower* against *variants*.

    Applies both :func:`rapidfuzz.fuzz.ratio` (character-level similarity) and
    :func:`rapidfuzz.fuzz.token_sort_ratio` (word-order-invariant similarity).
    The maximum across both metrics and all variants is returned.
    """
    best = 0.0
    for variant in variants:
        v = variant.lower()
        score = (
            max(
                fuzz.ratio(criterion_lower, v),
                fuzz.token_sort_ratio(criterion_lower, v),
            )
            / 100.0
        )
        if score > best:
            best = score
    return best


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_criterion_name(
    criterion_name: str,
    mapping: dict[str, list[str]] | None = None,
    threshold: float = NORMALIZATION_MATCH_THRESHOLD,
) -> str:
    """Map a rubric criterion name to a canonical skill dimension.

    Performs a case-insensitive fuzzy match of *criterion_name* against the
    known variants for each canonical dimension.  The dimension with the
    highest score at or above *threshold* is returned.  Ties are broken by
    the iteration order of *mapping* (insertion order for Python dicts).

    If no dimension scores at or above *threshold*, the criterion is stored
    under ``"other"`` and an info-level log entry is emitted so unmapped
    patterns can be identified and added to the config over time.

    Args:
        criterion_name: The raw rubric criterion name to normalise.
        mapping: Custom ``{dimension: [variant, ...]}`` dict.  When ``None``
            the bundled ``skill_normalization_config.json`` is loaded.  Pass
            a custom dict in tests or when supporting subjects beyond English
            writing.
        threshold: Minimum score to consider a match.  Defaults to
            :data:`NORMALIZATION_MATCH_THRESHOLD` (0.80).

    Returns:
        A canonical dimension name — one of the values in
        :data:`CANONICAL_DIMENSIONS`.
    """
    if mapping is None:
        mapping = load_skill_mapping()

    criterion_lower = criterion_name.strip().lower()

    # Fast-path: input is already a canonical dimension name.
    if criterion_lower in CANONICAL_DIMENSIONS:
        return criterion_lower

    best_dimension = OTHER_DIMENSION
    best_score = 0.0

    for dimension, variants in mapping.items():
        if dimension == OTHER_DIMENSION:
            # "other" is the fallback — never a fuzzy-match target.
            continue

        # Compare against the dimension name itself first (cheap exact check),
        # then against its variant list.
        all_variants = [dimension, *variants]
        score = _best_variant_score(criterion_lower, all_variants)
        if score >= threshold and score > best_score:
            best_score = score
            best_dimension = dimension

    if best_dimension == OTHER_DIMENSION:
        logger.info(
            "Criterion name could not be mapped to a canonical skill dimension; "
            "recording under 'other'. Add a matching variant to "
            "skill_normalization_config.json if this pattern recurs.",
            extra={"unmapped_criterion_length": len(criterion_name)},
        )

    return best_dimension
