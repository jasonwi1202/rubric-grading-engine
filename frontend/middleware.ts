/**
 * Next.js middleware — route protection and public-site auth redirects.
 *
 * Strategy:
 * - Public paths (marketing site, login, sign-up) are always accessible
 *   without a session.
 * - Authenticated users visiting /login or /signup are redirected to
 *   /dashboard so they land in the app immediately.
 * - Protected routes (the (dashboard) route group: /dashboard, /classes,
 *   /rubrics, /worklist, …) require a session; unauthenticated requests are
 *   redirected to /login with the original destination preserved.
 *
 * Session detection:
 * - The backend sets an httpOnly Secure SameSite=Strict cookie named
 *   `refresh_token` after a successful login. Middleware can read this
 *   cookie from the incoming request to determine whether the browser has
 *   a valid session (a present cookie is a necessary — though not
 *   sufficient — condition for a valid session; the backend validates the
 *   token itself on every authenticated API call).
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
import { isSafeRedirectPath } from "@/lib/utils/redirect";

/** Cookie name set by the backend on successful login. */
const REFRESH_TOKEN_COOKIE = "refresh_token";

/**
 * Paths under the (public) route group — always accessible without a session.
 * Root "/" is handled separately by the pathname === "/" check below.
 */
const PUBLIC_PATHS = [
  "/login",
  "/signup",
  "/product",
  "/how-it-works",
  "/pricing",
  "/about",
  "/ai",
  "/legal",
];

/**
 * Auth-entry paths: if the user already has a session and visits one of
 * these, redirect them straight to /dashboard.
 */
const AUTH_ENTRY_PATHS = ["/login", "/signup"];

function isPublicPath(pathname: string): boolean {
  if (pathname === "/") return true;
  return PUBLIC_PATHS.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );
}

function isAuthEntryPath(pathname: string): boolean {
  return AUTH_ENTRY_PATHS.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );
}

export function middleware(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;

  // Check for the refresh-token cookie. Its presence indicates the browser
  // completed a successful login and the backend set a session cookie.
  const hasSession = request.cookies.has(REFRESH_TOKEN_COOKIE);

  // Authenticated users visiting /login or /signup should go straight to the
  // dashboard — they have no reason to see the auth entry pages.
  if (hasSession && isAuthEntryPath(pathname)) {
    const dashboardUrl = request.nextUrl.clone();
    dashboardUrl.pathname = "/dashboard";
    dashboardUrl.search = "";
    return NextResponse.redirect(dashboardUrl);
  }

  // Allow all public (marketing) paths through, regardless of session state.
  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  // Everything else is a protected route. Redirect unauthenticated requests
  // to /login, preserving the original destination so we can redirect back
  // after a successful login.
  if (!hasSession) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = "/login";
    // Preserve the original destination (path + query string) so we can
    // redirect back after login.  Only store it if it's a safe relative path
    // (guards against open redirect).
    const { search } = request.nextUrl;
    const destination = search ? `${pathname}${search}` : pathname;
    if (isSafeRedirectPath(destination) && pathname !== "/login") {
      loginUrl.searchParams.set("next", destination);
    }
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  /**
   * Run middleware on all routes except:
   * - Next.js internals (_next/static, _next/image)
   * - API routes proxied to the backend (/api/...)
   * - The favicon
   *
   * This covers both the (public) marketing pages and the (dashboard) app
   * routes so that auth redirects apply everywhere.
   */
  matcher: [
    "/((?!api(?:/|$)|_next/static|_next/image|favicon\\.ico).*)",
  ],
};
