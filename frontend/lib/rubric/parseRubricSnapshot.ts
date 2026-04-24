/**
 * Shared helper for parsing `rubric_snapshot` criterion metadata.
 *
 * The snapshot shape is defined by `build_rubric_snapshot` on the backend.
 * Both the assignment overview page and the essay review page use this helper
 * to avoid divergence when the snapshot shape evolves.
 */

/**
 * One criterion entry from assignment.rubric_snapshot.criteria.
 * Matches the shape produced by the backend `build_rubric_snapshot` function.
 */
export interface RubricSnapshotCriterion {
  id: string;
  name: string;
  description: string;
  weight: number;
  min_score: number;
  max_score: number;
}

/**
 * Parse the `criteria` array from a rubric snapshot object.
 * Returns an empty array if the snapshot is missing or malformed.
 */
export function parseRubricSnapshot(
  snapshot: Record<string, unknown>,
): RubricSnapshotCriterion[] {
  const raw = snapshot.criteria;
  if (!Array.isArray(raw)) return [];
  return raw.map((c) => {
    const criterion = c as Record<string, unknown>;
    return {
      id: String(criterion.id ?? ""),
      name: String(criterion.name ?? "Unnamed"),
      description: String(criterion.description ?? ""),
      weight: Number(criterion.weight ?? 0),
      min_score: Number(criterion.min_score ?? 0),
      max_score: Number(criterion.max_score ?? 0),
    };
  });
}
