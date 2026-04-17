/**
 * Auth API helpers — sign-up, email verification, and resend-verification.
 *
 * All calls go through the typed `apiPost` / `apiGet` wrappers in
 * `lib/api/client.ts`. No raw `fetch()` here.
 *
 * Security notes:
 * - No student PII is collected or processed in this module.
 * - Passwords are transmitted only over HTTPS (enforced by the backend).
 */

import { apiPost, apiGet } from "@/lib/api/client";
import type { SignupFormValues } from "@/lib/schemas/auth";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SignupResponseData {
  id: string;
  email: string;
  message: string;
  created_at: string;
}

export interface VerifyEmailResponseData {
  message: string;
}

export interface ResendVerificationResponseData {
  message: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

/**
 * Create a new unverified teacher account.
 * On success the backend enqueues a verification email and returns 201.
 */
export async function signup(
  values: SignupFormValues,
): Promise<SignupResponseData> {
  return apiPost<SignupResponseData>("/auth/signup", {
    email: values.email,
    password: values.password,
    first_name: values.first_name,
    last_name: values.last_name,
    school_name: values.school_name,
  });
}

/**
 * Consume a single-use verification token from the email link.
 * On success the account is marked as verified.
 */
export async function verifyEmail(
  token: string,
): Promise<VerifyEmailResponseData> {
  return apiGet<VerifyEmailResponseData>(
    `/auth/verify-email?token=${encodeURIComponent(token)}`,
  );
}

/**
 * Re-send the email verification link for an unverified account.
 * Always returns a success-like response regardless of whether the email
 * is registered (to avoid confirming account existence).
 */
export async function resendVerification(
  email: string,
): Promise<ResendVerificationResponseData> {
  return apiPost<ResendVerificationResponseData>("/auth/resend-verification", {
    email,
  });
}
