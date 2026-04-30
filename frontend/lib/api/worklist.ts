/**
 * Worklist API helpers — M6-05 / M6-06 (Teacher Worklist).
 *
 * Covers:
 *   GET    /worklist                     — prioritized worklist items
 *   POST   /worklist/{itemId}/complete   — mark item as done
 *   POST   /worklist/{itemId}/snooze     — snooze item (default 7 days)
 *   DELETE /worklist/{itemId}            — dismiss item permanently
 *
 * Aligned with backend `app/schemas/worklist.py` response shapes.
 *
 * Security notes:
 * - No student PII is logged; only entity IDs appear here.
 * - All endpoints require a valid JWT access token.
 * - No student data is stored in localStorage / sessionStorage.
 */

import { apiDelete, apiGet, apiPost } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Priority signal that generated this worklist item. */
export type TriggerType =
  | "regression"
  | "non_responder"
  | "persistent_gap"
  | "high_inconsistency";

/** Lifecycle status of a worklist item. */
export type WorklistItemStatus = "active" | "snoozed" | "completed" | "dismissed";

/** A single ranked item in the teacher's worklist. Matches backend WorklistItemResponse. */
export interface WorklistItem {
  id: string;
  student_id: string;
  trigger_type: TriggerType;
  /** Canonical skill dimension key, or null for student-level triggers. */
  skill_key: string | null;
  /** Urgency score 1–4; 4 = most urgent. */
  urgency: number;
  suggested_action: string;
  details: Record<string, unknown>;
  status: WorklistItemStatus;
  snoozed_until: string | null;
  completed_at: string | null;
  generated_at: string;
  created_at: string;
}

/** Full ranked worklist response. Matches backend TeacherWorklistResponse. */
export interface TeacherWorklistResponse {
  teacher_id: string;
  items: WorklistItem[];
  total_count: number;
  generated_at: string;
}

/** Request body for snooze endpoint. */
export interface SnoozeWorklistItemRequest {
  /** ISO-8601 datetime until which to hide the item. Omit for default (7 days). */
  snoozed_until?: string | null;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Fetch the authenticated teacher's prioritized worklist.
 * Calls GET /api/v1/worklist.
 */
export async function getWorklist(): Promise<TeacherWorklistResponse> {
  return apiGet<TeacherWorklistResponse>("/worklist");
}

/**
 * Mark a worklist item as completed.
 * Calls POST /api/v1/worklist/{itemId}/complete.
 */
export async function completeWorklistItem(itemId: string): Promise<WorklistItem> {
  return apiPost<WorklistItem>(`/worklist/${itemId}/complete`, {});
}

/**
 * Snooze a worklist item.
 * Calls POST /api/v1/worklist/{itemId}/snooze.
 */
export async function snoozeWorklistItem(
  itemId: string,
  body: SnoozeWorklistItemRequest = {},
): Promise<WorklistItem> {
  return apiPost<WorklistItem>(`/worklist/${itemId}/snooze`, body);
}

/**
 * Dismiss a worklist item permanently.
 * Calls DELETE /api/v1/worklist/{itemId}.
 */
export async function dismissWorklistItem(itemId: string): Promise<WorklistItem> {
  return apiDelete<WorklistItem>(`/worklist/${itemId}`);
}
