/**
 * Next.js middleware — route protection stub.
 *
 * Currently a no-op that simply continues all requests. Auth logic will be
 * implemented in a later milestone once the backend auth endpoints are ready.
 *
 * When auth is implemented this middleware should only use information
 * available on the incoming request. A practical flow is:
 * - Check for a secure httpOnly refresh/session cookie on protected routes
 * - If the cookie is present, call the backend to validate the session and/or
 *   rotate an access token before allowing the request to continue
 * - Redirect requests with no valid session to /login
 *
 * Middleware cannot react to downstream 401 API responses. Any 401 returned
 * after navigation must be handled by the frontend API client, which can
 * trigger a refresh flow or redirect to /login as appropriate.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(_request: NextRequest): NextResponse {
  // Auth guard will be added here in a future milestone.
  return NextResponse.next();
}

export const config = {
  /**
   * Limit middleware execution to the dashboard route subtree for now.
   * This keeps the auth stub in place without adding edge/runtime overhead
   * to the rest of the application while auth is not yet implemented.
   */
  matcher: ["/dashboard/:path*"],
};
