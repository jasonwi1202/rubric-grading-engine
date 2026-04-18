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

/** Generate a unique test email to avoid collisions between test runs. */
export function testEmail(tag: string): string {
  return `e2e-${tag}-${Date.now()}@example.com`;
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
