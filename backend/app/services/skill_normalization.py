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
- Criterion names are teacher-entered free-form rubric fields and should be
  treated as potentially containing student PII; raw criterion content is
  never emitted in log messages.
- The normalizer is reusable by both the skill-profile update task and the
  class-insights aggregation service.
"""

from __future__ import annotations

import functools
import importlib.resources
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


# ---------------------------------------------------------------------------
# Config loading (with memoization to avoid repeated disk reads)
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=8)
def _load_mapping_cached(path_key: str | None) -> dict[str, list[str]]:
    """Load and parse the skill mapping from disk; result is cached by *path_key*.

    Args:
        path_key: Resolved absolute path string, or ``None`` to load the
            bundled default config via :mod:`importlib.resources`.
    """
    if path_key is None:
        # Use importlib.resources so the bundled config is accessible even
        # when the package is installed as a wheel or zipapp.
        ref = importlib.resources.files("app").joinpath(
            "skill_normalization_config.json"
        )
        try:
            raw = ref.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as exc:
            raise FileNotFoundError(
                "Bundled skill normalization config could not be read: "
                "skill_normalization_config.json"
            ) from exc
    else:
        config_path = Path(path_key)
        try:
            raw = config_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise FileNotFoundError(
                f"Skill normalization config not found: {config_path}"
            ) from None

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in skill normalization config: {exc}"
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


def load_skill_mapping(config_path: Path | str | None = None) -> dict[str, list[str]]:
    """Load and return the skill mapping from a JSON config file.

    Results are memoized by resolved path so repeated calls with the same
    path do not re-read the file from disk (important for per-criterion
    normalization in high-volume grading tasks).

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
    path_key: str | None = (
        str(Path(config_path).resolve()) if config_path is not None else None
    )
    return _load_mapping_cached(path_key)


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
            the config is loaded from
            ``settings.skill_normalization_config_path`` (if set) or the
            bundled ``skill_normalization_config.json``.  Pass a custom dict
            in tests or when supporting subjects beyond English writing.
        threshold: Minimum score (0.0–1.0) to consider a match.  Defaults to
            :data:`NORMALIZATION_MATCH_THRESHOLD` (0.80).

    Returns:
        When using the default or bundled mapping, always a member of
        :data:`CANONICAL_DIMENSIONS`.  When a custom *mapping* is supplied,
        the returned value is a key from that mapping and may not be a member
        of :data:`CANONICAL_DIMENSIONS` (e.g. ``"science_claim"`` for a
        science-subject mapping).

    Raises:
        ValueError: If *threshold* is not in the range ``[0.0, 1.0]``.
    """
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(
            f"threshold must be between 0.0 and 1.0 inclusive; got {threshold!r}"
        )

    if mapping is None:
        # Lazy import: app.config imports app.services modules indirectly via
        # Celery task registration, so a top-level import here would create a
        # circular dependency.  Importing inside the function body defers
        # resolution until after all modules are fully initialised.
        from app.config import settings

        mapping = load_skill_mapping(settings.skill_normalization_config_path)

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
