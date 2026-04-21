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

/** Full assignment detail including per-student submission status. */
export interface AssignmentDetailResponse {
  id: string;
  class_id: string;
  rubric_id: string;
  rubric_name: string;
  title: string;
  prompt: string | null;
  due_date: string | null;
  status: AssignmentStatus;
  created_at: string;
  submission_statuses: SubmissionStatusItem[];
}

/** Lightweight item returned by the list endpoint. */
export interface AssignmentListItem {
  id: string;
  class_id: string;
  rubric_id: string;
  rubric_name: string;
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
 * Get assignment detail including per-student submission status.
 * Calls GET /api/v1/assignments/{assignmentId}.
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
