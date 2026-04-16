/**
 * Next.js middleware — route protection stub.
 *
 * Currently a no-op that simply continues all requests. Auth logic will be
 * implemented in a later milestone once the backend auth endpoints are ready.
 *
 * When auth is implemented this middleware will:
 * - Verify the JWT access token from the session cookie on all (dashboard) routes
 * - Redirect unauthenticated requests to /login
 * - Attempt a silent token refresh on 401 responses before redirecting
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(_request: NextRequest): NextResponse {
  // Auth guard will be added here in a future milestone.
  return NextResponse.next();
}

export const config = {
  /**
   * Protect all routes under /(dashboard). Excludes Next.js internals and
   * static assets to avoid unnecessary middleware overhead.
   */
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|login).*)",
  ],
};
