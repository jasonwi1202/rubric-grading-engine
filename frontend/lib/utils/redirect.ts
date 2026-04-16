/**
 * Validates that a redirect target is a safe relative path within this
 * application.
 *
 * Rejects:
 * - Empty strings
 * - Paths that do not start with `/` (would be interpreted as relative)
 * - Protocol-relative URLs (`//example.com`) that browsers treat as absolute
 * - Paths containing backslashes (`\`) that some runtimes normalise to `/`
 *   and could be exploited for open-redirect on Windows-style path handling
 *
 * Used by both middleware.ts and the login page to defend against open-redirect
 * attacks when consuming the `next` query parameter.
 */
export function isSafeRedirectPath(path: string): boolean {
  return (
    path.length > 0 &&
    path.startsWith("/") &&
    !path.startsWith("//") &&
    !path.includes("\\")
  );
}
