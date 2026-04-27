/**
 * Assignments API helpers — M3.13 implementation.
 *
 * Covers assignment CRUD and status-transition operations.
 *
 * Status state machine (server-enforced):
 *   draft → open → grading → review → complete → returned
 *
 * Security notes:
 * - No student PII is logged; only entity IDs appear in error paths.
 * - All endpoints require a valid JWT access token.
 */

import { apiGet, apiPatch, apiPost } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AssignmentStatus =
  | "draft"
  | "open"
  | "grading"
  | "review"
  | "complete"
  | "returned";

/**
 * Valid next states for each assignment status.
 * Only transitions present in this map are offered to the teacher.
 */
export const VALID_TRANSITIONS: Partial<
  Record<AssignmentStatus, AssignmentStatus>
> = {
  draft: "open",
  open: "grading",
  grading: "review",
  review: "complete",
  complete: "returned",
};

/**
 * Human-readable label for each status-transition action.
 * Keyed by the *current* status.
 */
export const TRANSITION_LABELS: Partial<Record<AssignmentStatus, string>> = {
  draft: "Open assignment",
  open: "Close submissions",
  grading: "Move to review",
  review: "Mark complete",
  complete: "Return to class",
};

/** Human-readable display label for each status. */
export const STATUS_LABELS: Record<AssignmentStatus, string> = {
  draft: "Draft",
  open: "Open",
  grading: "Grading",
  review: "In review",
  complete: "Complete",
  returned: "Returned",
};

export interface CreateAssignmentRequest {
  title: string;
  prompt?: string | null;
  rubric_id: string;
  due_date?: string | null;
}

export interface UpdateAssignmentRequest {
  title?: string;
  prompt?: string | null;
  due_date?: string | null;
  status?: AssignmentStatus;
}

/** Per-student submission status entry within an assignment detail response. */
export interface SubmissionStatusItem {
  student_id: string;
  student_name: string;
  /** Aggregated status reflecting essay + grade lifecycle. */
  submission_status: "pending" | "submitted" | "graded" | "returned";
  submitted_at: string | null;
}

/**
 * Full assignment detail returned by GET /assignments/{id}.
 *
 * Matches backend `AssignmentResponse`. The rubric name is read from the
 * immutable `rubric_snapshot` — never from a live rubric record.
 *
 * `submission_statuses` is not returned by the backend today; it is optional
 * here so callers can attach it via a separate endpoint in a future milestone.
 */
export interface AssignmentDetailResponse {
  id: string;
  class_id: string;
  rubric_id: string;
  rubric_snapshot: { name: string; [key: string]: unknown };
  title: string;
  prompt: string | null;
  due_date: string | null;
  status: AssignmentStatus;
  created_at: string;
  submission_statuses?: SubmissionStatusItem[];
}

/**
 * Lightweight item returned by GET /classes/{classId}/assignments.
 *
 * Note: the backend list endpoint (`AssignmentListItemResponse`) does not
 * include a rubric name field. Callers that need the name should read it from
 * `rubric_snapshot.name` on the detail endpoint.
 */
export interface AssignmentListItem {
  id: string;
  class_id: string;
  rubric_id: string;
  title: string;
  prompt: string | null;
  due_date: string | null;
  status: AssignmentStatus;
  created_at: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * List all assignments for a class.
 * Calls GET /api/v1/classes/{classId}/assignments.
 */
export async function listAssignments(
  classId: string,
): Promise<AssignmentListItem[]> {
  return apiGet<AssignmentListItem[]>(`/classes/${classId}/assignments`);
}

/**
 * Create a new assignment under a class.
 * Calls POST /api/v1/classes/{classId}/assignments.
 */
export async function createAssignment(
  classId: string,
  data: CreateAssignmentRequest,
): Promise<AssignmentDetailResponse> {
  return apiPost<AssignmentDetailResponse>(
    `/classes/${classId}/assignments`,
    data,
  );
}

/**
 * Get assignment detail.
 * Calls GET /api/v1/assignments/{assignmentId}.
 *
 * Note: per-student submission status may be omitted from the response until
 * the backend exposes it consistently in `AssignmentResponse`.
 */
export async function getAssignment(
  assignmentId: string,
): Promise<AssignmentDetailResponse> {
  return apiGet<AssignmentDetailResponse>(`/assignments/${assignmentId}`);
}

/**
 * Update an assignment's metadata or advance its status.
 * Calls PATCH /api/v1/assignments/{assignmentId}.
 *
 * Status transitions are applied via the `status` field. The server enforces
 * that only transitions defined in VALID_TRANSITIONS are permitted.
 */
export async function updateAssignment(
  assignmentId: string,
  data: UpdateAssignmentRequest,
): Promise<AssignmentDetailResponse> {
  return apiPatch<AssignmentDetailResponse>(
    `/assignments/${assignmentId}`,
    data,
  );
}

// ---------------------------------------------------------------------------
// Assignment analytics types (M5.8)
// ---------------------------------------------------------------------------

/**
 * A single (raw score value, count) pair in a per-criterion distribution.
 * Matches backend ScoreCount exactly.
 */
export interface ScoreCount {
  score: number;
  count: number;
}

/**
 * Per-criterion analytics for one assignment.
 * Matches backend CriterionAnalytics exactly.
 */
export interface CriterionAnalytics {
  criterion_id: string;
  criterion_name: string;
  /** Canonical skill dimension this criterion maps to. */
  skill_dimension: string;
  min_score_possible: number;
  max_score_possible: number;
  /** Mean raw final_score across all locked essays. */
  avg_score: number;
  /** Mean normalised score (0.0–1.0) across all locked essays. */
  avg_normalized_score: number;
  /** Count of essays per raw score value, ordered by ascending score. */
  score_distribution: ScoreCount[];
}

/**
 * Response from GET /assignments/{assignmentId}/analytics.
 * Matches backend AssignmentAnalyticsResponse exactly.
 */
export interface AssignmentAnalyticsResponse {
  assignment_id: string;
  class_id: string;
  total_essay_count: number;
  /** Essays with a locked grade (included in analytics). */
  locked_essay_count: number;
  /**
   * Mean normalised score across all criteria and all locked essays.
   * Null when there are no locked grades.
   */
  overall_avg_normalized_score: number | null;
  /** Per-criterion analytics in rubric display_order. */
  criterion_analytics: CriterionAnalytics[];
}

// ---------------------------------------------------------------------------
// Assignment analytics API function
// ---------------------------------------------------------------------------

/**
 * Get per-criterion analytics for an assignment.
 * Calls GET /api/v1/assignments/{assignmentId}/analytics.
 *
 * Only locked grades contribute. Returns criterion-level score distributions,
 * averages, and overall class performance for the assignment.
 */
export async function getAssignmentAnalytics(
  assignmentId: string,
): Promise<AssignmentAnalyticsResponse> {
  return apiGet<AssignmentAnalyticsResponse>(
    `/assignments/${assignmentId}/analytics`,
  );
}
