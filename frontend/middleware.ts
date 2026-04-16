/**
 * Next.js middleware — route protection for the (dashboard) route group.
 *
 * Strategy:
 * - Protected routes: everything that is NOT an auth page, a Next.js
 *   internal path, or a static asset.
 * - The backend sets an httpOnly Secure SameSite=Strict cookie named
 *   `refresh_token` after a successful login. Middleware can read this
 *   cookie from the incoming request to determine whether the browser has
 *   a valid session (a present cookie is a necessary — though not
 *   sufficient — condition for a valid session; the backend validates the
 *   token itself on every authenticated API call).
 * - If the cookie is absent on a protected route the request is redirected
 *   to /login.
 *
 * Limitations:
 * - Middleware runs on the Edge runtime and cannot call the backend to
 *   validate the refresh token on every navigation. The first API call
 *   after navigation will receive a 401 if the token has been revoked;
 *   the API client then performs a silent refresh or redirects to /login.
 * - Access tokens are stored in module-level memory and are not available
 *   to middleware (different runtime/process). Only the httpOnly cookie is
 *   accessible here.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/** Cookie name set by the backend on successful login. */
const REFRESH_TOKEN_COOKIE = "refresh_token";

/** Paths that are always publicly accessible — no session required. */
const PUBLIC_PATHS = ["/login"];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );
}

export function middleware(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;

  // Always allow public paths (login) through.
  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  // Check for the refresh-token cookie. Its presence indicates the browser
  // completed a successful login and the backend set a session cookie.
  const hasSession = request.cookies.has(REFRESH_TOKEN_COOKIE);

  if (!hasSession) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    // Preserve the original destination so we can redirect back after login.
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  /**
   * Run middleware on all routes except:
   * - Next.js internals (_next/static, _next/image)
   * - The favicon
   * - API routes (handled by the backend, not the frontend)
   *
   * This covers the entire (dashboard) route group which maps to `/`,
   * `/classes`, `/rubrics`, `/worklist`, and all their sub-paths.
   */
  matcher: [
    "/((?!_next/static|_next/image|favicon\\.ico).*)",
  ],
};
