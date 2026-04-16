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
   * Run middleware on all application routes except Next.js internals,
   * static assets, and the /login page (which must remain publicly accessible
   * so unauthenticated users can sign in). Route groups like (dashboard) are
   * not part of the URL, so this single pattern covers every guarded page.
   */
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|login).*)",
  ],
};
