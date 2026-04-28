/**
 * Writing process signals API helpers — M5-11 (Writing process visibility UI).
 *
 * Covers:
 *   GET /essays/{essayId}/process-signals — composition timeline and process signals
 *
 * The data is computed lazily on first request and cached on the server.
 * When `has_process_data` is false, the essay was submitted via file upload
 * and no writing-process data was captured.
 *
 * All signals are framed as indicators, not definitive findings. UI language
 * must reflect this — paste events and rapid-completion events are never
 * presented as evidence of wrongdoing.
 *
 * Security notes:
 * - No student PII is logged; only entity IDs appear in error paths.
 * - All endpoints require a valid JWT access token.
 */

import { apiGet } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types — mirror backend ProcessSignalsResponse exactly
// ---------------------------------------------------------------------------

/** One contiguous writing session derived from the snapshot history. */
export interface SessionSegment {
  session_index: number;
  started_at: string;
  ended_at: string;
  duration_seconds: number;
  snapshot_count: number;
  word_count_start: number;
  word_count_end: number;
  words_added: number;
}

/** A snapshot step where a large word-count jump was detected. */
export interface PasteEvent {
  snapshot_seq: number;
  occurred_at: string;
  words_before: number;
  words_after: number;
  words_added: number;
  session_index: number;
}

/** A session that brought the essay near-complete in a short time. */
export interface RapidCompletionEvent {
  snapshot_seq: number;
  occurred_at: string;
  words_before: number;
  words_after: number;
  words_added: number;
  completion_fraction: number;
  duration_seconds: number;
  session_index: number;
}

/**
 * Full process signals response returned by GET /essays/{essayId}/process-signals.
 * Matches backend `ProcessSignalsResponse` exactly.
 *
 * When `has_process_data` is false, all list fields are empty and numeric
 * metrics are zero — the essay was submitted via file upload or has no
 * analyzable snapshot history.
 */
export interface ProcessSignalsResponse {
  essay_id: string;
  essay_version_id: string;
  /** True when writing-process data is available (browser-composed essays only). */
  has_process_data: boolean;
  session_count: number;
  active_writing_seconds: number;
  total_elapsed_seconds: number;
  inter_session_gaps_seconds: number[];
  sessions: SessionSegment[];
  paste_events: PasteEvent[];
  rapid_completion_events: RapidCompletionEvent[];
  computed_at: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Fetch composition timeline and process signals for an essay.
 * Calls GET /essays/{essayId}/process-signals.
 *
 * Returns 404 when the essay does not exist or belongs to another teacher.
 * Returns 403 when the teacher does not own the essay.
 *
 * When `has_process_data` is false on the returned object, no usable
 * writing-process data was available — render the "no process data" state.
 */
export async function getProcessSignals(
  essayId: string,
): Promise<ProcessSignalsResponse> {
  return apiGet<ProcessSignalsResponse>(`/essays/${essayId}/process-signals`);
}
