/**
 * Shared helper for parsing `rubric_snapshot` criterion metadata.
 *
 * The snapshot shape is defined by `build_rubric_snapshot` on the backend.
 * Both the assignment overview page and the essay review page use this helper
 * to avoid divergence when the snapshot shape evolves.
 */

import type { RubricSnapshotCriterion } from "@/components/grading/EssayReviewPanel";

/**
 * Parse the `criteria` array from a rubric snapshot object.
 * Returns an empty array if the snapshot is missing or malformed.
 */
export function parseRubricSnapshot(
  snapshot: Record<string, unknown>,
): RubricSnapshotCriterion[] {
  const raw = snapshot.criteria;
  if (!Array.isArray(raw)) return [];
  return raw.map((c) => ({
    id: String((c as Record<string, unknown>).id ?? ""),
    name: String((c as Record<string, unknown>).name ?? "Unnamed"),
    description: String((c as Record<string, unknown>).description ?? ""),
    weight: Number((c as Record<string, unknown>).weight ?? 0),
    min_score: Number((c as Record<string, unknown>).min_score ?? 0),
    max_score: Number((c as Record<string, unknown>).max_score ?? 0),
  }));
}
