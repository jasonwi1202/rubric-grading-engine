/**
 * Shared helpers for E2E tests.
 *
 * All helpers use the real Docker Compose stack — no mocking.
 * Mailpit API: http://localhost:8025/api/v1/messages
 */

import { Page, expect } from "@playwright/test";

const MAILPIT_API = process.env.MAILPIT_API_URL ?? "http://localhost:8025";

/** Poll Mailpit until an email arrives for `toAddress`, then return its full text body. */
export async function waitForEmail(
  toAddress: string,
  subjectContains: string,
  timeoutMs = 10_000,
): Promise<{ subject: string; body: string; id: string }> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = await fetch(`${MAILPIT_API}/api/v1/messages`);
    if (!res.ok) throw new Error(`Mailpit API returned ${res.status}`);
    const data = (await res.json()) as {
      messages: Array<{
        ID: string;
        Subject: string;
        To: Array<{ Address: string }>;
      }>;
    };
    const match = data.messages.find(
      (m) =>
        m.To.some((t) => t.Address === toAddress) &&
        m.Subject.includes(subjectContains),
    );
    if (match) {
      const detail = await fetch(`${MAILPIT_API}/api/v1/message/${match.ID}`);
      const body = (await detail.json()) as { Text: string };
      return { subject: match.Subject, body: body.Text, id: match.ID };
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(
    `No email for ${toAddress} with subject containing "${subjectContains}" found within ${timeoutMs}ms`,
  );
}

/** Delete all messages in Mailpit — call before tests that send email to avoid stale matches. */
export async function clearMailpit(): Promise<void> {
  await fetch(`${MAILPIT_API}/api/v1/messages`, { method: "DELETE" });
}

/** Extract the first https?:// URL from an email body. */
export function extractLinkFromEmail(body: string): string {
  const match = body.match(/https?:\/\/\S+/);
  if (!match) throw new Error("No URL found in email body");
  return match[0].trim().replace(/[>)\]'"]+$/, ""); // strip trailing punctuation
}

/** Generate a unique test email to avoid collisions between test runs.
 *
 * Combines the epoch millisecond timestamp with a random alphanumeric suffix so
 * that two suites starting within the same millisecond (e.g. parallel CI shards)
 * still produce distinct addresses for the same `tag`.
 */
export function testEmail(tag: string): string {
  const suffix = Math.random().toString(36).slice(2, 8);
  return `e2e-${tag}-${Date.now()}-${suffix}@example.com`;
}

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

/**
 * Seed a verified teacher account via the backend API.
 *
 * Creates the account via POST /auth/signup, waits for the verification email
 * in Mailpit, and confirms the token via GET /auth/verify-email.  Returns the
 * credentials that can be used to log in via the UI.
 *
 * Call `clearMailpit()` before this helper when running in a suite that might
 * have stale emails in the inbox.
 */
export async function seedTeacher(
  tag: string,
): Promise<{ email: string; password: string }> {
  const email = testEmail(tag);
  const password = "JourneyPass1!";

  const signupRes = await fetch(`${API_BASE}/api/v1/auth/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      first_name: "E2E",
      last_name: "Teacher",
      email,
      password,
      school_name: "E2E Test School",
    }),
  });
  if (!signupRes.ok) {
    throw new Error(`Signup failed: ${signupRes.status}`);
  }

  // Verify email via Mailpit
  const { body } = await waitForEmail(email, "verify", 20_000);
  const verifyUrl = extractLinkFromEmail(body);
  const token = new URL(verifyUrl).searchParams.get("token");
  if (!token) {
    throw new Error("Verification token not found in email link");
  }
  const verifyRes = await fetch(
    `${API_BASE}/api/v1/auth/verify-email?token=${encodeURIComponent(token)}`,
  );
  if (!verifyRes.ok) {
    throw new Error(`Email verification failed: ${verifyRes.status}`);
  }

  return { email, password };
}

/** Wait for the backend health endpoint to be reachable. Useful after compose up. */
export async function waitForBackend(
  apiBase = "http://localhost:8000",
  timeoutMs = 30_000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${apiBase}/api/v1/health`);
      if (res.ok) return;
    } catch {
      // not ready yet
    }
    await new Promise((r) => setTimeout(r, 1_000));
  }
  throw new Error(`Backend at ${apiBase} did not become healthy within ${timeoutMs}ms`);
}

/** Assert the page has no obvious accessibility violations (title, main landmark). */
export async function assertBasicA11y(page: Page): Promise<void> {
  await expect(page.locator("main, [role='main']").first()).toBeVisible();
  const title = await page.title();
  expect(title.length).toBeGreaterThan(0);
}
