/**
 * Text comment bank API helpers — M8-02 (Text comment bank UI).
 *
 * Covers:
 *   GET    /comment-bank                — list saved text comments
 *   POST   /comment-bank               — save a new text snippet
 *   DELETE /comment-bank/{id}          — remove a saved comment
 *   GET    /comment-bank/suggestions   — fuzzy-match suggestions for a query
 *
 * Security notes:
 * - Comment text is free-form user input and may contain teacher-entered
 *   student-related information. Never log comment text.
 * - No student PII is logged; only entity IDs appear here.
 * - All endpoints require a valid JWT access token.
 */

import { apiDelete, apiGet, apiPost } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * A single saved text comment in the teacher's comment bank.
 * Matches backend `CommentBankEntryResponse` exactly.
 */
export interface CommentBankEntry {
  id: string;
  text: string;
  created_at: string;
}

/**
 * A suggested comment with its fuzzy-match score (0.0–1.0).
 * Matches backend `CommentBankSuggestionResponse` exactly.
 */
export interface CommentBankSuggestion extends CommentBankEntry {
  /** Fuzzy-match score in [0.0, 1.0]. Higher is a closer match. */
  score: number;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * List all saved text comments for the authenticated teacher.
 * Calls GET /api/v1/comment-bank.
 */
export async function listCommentBank(): Promise<CommentBankEntry[]> {
  return apiGet<CommentBankEntry[]>("/comment-bank");
}

/**
 * Save a new text feedback snippet to the teacher's comment bank.
 * Calls POST /api/v1/comment-bank.
 *
 * @param text - Feedback snippet (1–2000 characters, server-enforced).
 */
export async function createCommentBankEntry(
  text: string,
): Promise<CommentBankEntry> {
  return apiPost<CommentBankEntry>("/comment-bank", { text });
}

/**
 * Remove a saved text comment from the teacher's comment bank.
 * Calls DELETE /api/v1/comment-bank/{id}.
 */
export async function deleteCommentBankEntry(id: string): Promise<void> {
  return apiDelete<void>(`/comment-bank/${id}`);
}

/**
 * Fetch fuzzy-match suggestions for a query string.
 * Calls GET /api/v1/comment-bank/suggestions?q={query}.
 *
 * @param q - Query text (1–500 characters, server-enforced).
 */
export async function getCommentBankSuggestions(
  q: string,
): Promise<CommentBankSuggestion[]> {
  return apiGet<CommentBankSuggestion[]>(
    `/comment-bank/suggestions?q=${encodeURIComponent(q)}`,
  );
}
