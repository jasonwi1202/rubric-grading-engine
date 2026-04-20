/**
 * Shared criterion conversion utilities used by both RubricBuilderForm and
 * TemplatePicker. Extracted here to avoid a circular module dependency between
 * those two components.
 */

/** The normalised criterion shape written into the rubric builder form. */
export type FormCriterion = {
  name: string;
  description: string;
  weight: number;
  min_score: number;
  max_score: number;
  anchor_descriptions: Record<string, string>;
};

/** Minimum criterion shape accepted as input (from API responses or templates). */
export type CriterionInput = {
  name: string;
  description?: string | null;
  weight: number;
  min_score: number;
  max_score: number;
  anchor_descriptions?: Record<string, string> | null;
};

/**
 * Convert an array of API criterion objects into the normalised `FormCriterion`
 * shape used by the rubric builder form and the template picker apply callback.
 *
 * - `description` defaults to `""` (the form schema does not allow `null`).
 * - `anchor_descriptions` defaults to `{}` (empty map is a valid state).
 */
export function convertApiCriteriaToForm(criteria: CriterionInput[]): FormCriterion[] {
  return criteria.map((c) => ({
    name: c.name,
    description: c.description ?? "",
    weight: c.weight,
    min_score: c.min_score,
    max_score: c.max_score,
    anchor_descriptions: c.anchor_descriptions ?? {},
  }));
}
