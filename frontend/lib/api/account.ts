/**
 * Account API helpers — trial status and account-level information.
 *
 * All calls go through the typed `apiGet` wrapper in `lib/api/client.ts`.
 * No raw `fetch()` here.
 *
 * Security notes:
 * - No student PII is collected or processed in this module.
 * - These endpoints require a valid JWT access token (set via login).
 */

import { apiGet } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TrialStatus {
  trial_ends_at: string | null;
  is_active: boolean;
  days_remaining: number | null;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Return the authenticated teacher's trial status including expiry date,
 * active flag, and days remaining.
 */
export async function getTrialStatus(): Promise<TrialStatus> {
  return apiGet<TrialStatus>("/account/trial");
}
