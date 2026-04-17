/**
 * Onboarding API helpers — wizard status and completion.
 *
 * All calls go through the typed `apiGet` / `apiPost` wrappers in
 * `lib/api/client.ts`. No raw `fetch()` here.
 *
 * Security notes:
 * - No student PII is collected or processed in this module.
 * - These endpoints require a valid JWT access token (set via login).
 */

import { apiGet, apiPost } from "@/lib/api/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface OnboardingStatus {
  step: number;
  completed: boolean;
  trial_ends_at: string | null;
}

export interface OnboardingCompleteResponse {
  message: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Return the authenticated teacher's current onboarding wizard step and
 * completion flag, along with the trial expiry timestamp.
 */
export async function getOnboardingStatus(): Promise<OnboardingStatus> {
  return apiGet<OnboardingStatus>("/onboarding/status");
}

/**
 * Mark the teacher's onboarding wizard as complete.
 * Idempotent — safe to call multiple times.
 */
export async function completeOnboarding(): Promise<OnboardingCompleteResponse> {
  return apiPost<OnboardingCompleteResponse>("/onboarding/complete", {});
}
