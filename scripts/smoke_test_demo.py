#!/usr/bin/env python3
"""
Demo smoke test — waits for the demo Docker Compose stack to become ready,
then verifies all services are healthy and responding.

Usage:
    python scripts/smoke_test_demo.py

    # Custom URLs or retry count:
    python scripts/smoke_test_demo.py --retries 40 --retry-delay 5

Exit codes:
    0 — all checks passed
    1 — one or more checks failed (services may still be starting)
"""

import argparse
import sys
import time
from dataclasses import dataclass
from typing import Optional
import urllib.request
import urllib.error

RESET  = "\033[0m"
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
CYAN   = "\033[36m"
BOLD   = "\033[1m"


@dataclass
class Check:
    name: str
    url: str
    method: str = "GET"
    expected_status: int = 200
    body_contains: Optional[str] = None
    timeout: int = 10


@dataclass
class Result:
    check: Check
    passed: bool
    status: Optional[int] = None
    error: Optional[str] = None
    elapsed_ms: float = 0.0


def run_check(c: Check) -> Result:
    start = time.monotonic()
    try:
        req = urllib.request.Request(c.url, method=c.method)
        with urllib.request.urlopen(req, timeout=c.timeout) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", errors="replace")
            elapsed = (time.monotonic() - start) * 1000
            if status != c.expected_status:
                return Result(c, False, status, f"expected {c.expected_status}, got {status}", elapsed)
            if c.body_contains and c.body_contains not in body:
                return Result(c, False, status, f"body missing {c.body_contains!r}", elapsed)
            return Result(c, True, status, elapsed_ms=elapsed)
    except urllib.error.HTTPError as e:
        elapsed = (time.monotonic() - start) * 1000
        return Result(c, c.expected_status == e.code, e.code, str(e), elapsed)
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return Result(c, False, error=str(e), elapsed_ms=elapsed)


def build_checks(api: str, frontend: str, mailpit: str) -> list[Check]:
    return [
        # --- Backend ---
        Check("Backend: health endpoint",           f"{api}/api/v1/health", body_contains='"status"'),
        Check("Backend: OpenAPI schema reachable",  f"{api}/openapi.json",  body_contains='"openapi"'),
        Check("Backend: API docs page",             f"{api}/docs"),

        # --- Frontend public pages ---
        Check("Frontend: homepage (/)",             f"{frontend}/"),
        Check("Frontend: /product",                 f"{frontend}/product"),
        Check("Frontend: /how-it-works",            f"{frontend}/how-it-works"),
        Check("Frontend: /about",                   f"{frontend}/about"),
        Check("Frontend: /pricing",                 f"{frontend}/pricing"),
        Check("Frontend: /legal/terms",             f"{frontend}/legal/terms"),
        Check("Frontend: /legal/privacy",           f"{frontend}/legal/privacy"),
        Check("Frontend: /legal/ferpa",             f"{frontend}/legal/ferpa"),
        Check("Frontend: /legal/dpa",               f"{frontend}/legal/dpa"),
        Check("Frontend: /legal/ai-policy",         f"{frontend}/legal/ai-policy"),
        Check("Frontend: /signup",                  f"{frontend}/signup"),
        Check("Frontend: /login",                   f"{frontend}/login"),
        # /dashboard redirects to /login for unauthenticated users;
        # urllib follows the redirect so we verify it responds, not the status code
        Check("Frontend: /dashboard responds",      f"{frontend}/dashboard"),

        # --- M3 dashboard routes (redirect to /login when unauthenticated — confirms pages are registered) ---
        Check("Frontend: /dashboard/classes responds",              f"{frontend}/dashboard/classes"),
        Check("Frontend: /dashboard/rubrics/new responds",          f"{frontend}/dashboard/rubrics/new"),

        # --- M4 API endpoints (unauthenticated — confirm routes are registered) ---
        Check("Backend: integrity endpoint registered",     f"{api}/api/v1/essays/00000000-0000-0000-0000-000000000000/integrity",  expected_status=401),
        Check("Backend: regrade-requests endpoint registered", f"{api}/api/v1/grades/00000000-0000-0000-0000-000000000000/regrade-requests", expected_status=401),
        Check("Backend: media-comments endpoint registered", f"{api}/api/v1/grades/00000000-0000-0000-0000-000000000000/media-comments", expected_status=401),

        # --- M4 dashboard routes ---
        Check("Frontend: assignment review responds",  f"{frontend}/dashboard/classes/test/assignments/test/review"),

        # --- Mailpit ---
        Check("Mailpit: web UI reachable",          f"{mailpit}/"),
        Check("Mailpit: API messages endpoint",     f"{mailpit}/api/v1/messages", body_contains='"messages"'),
    ]


def wait_for_stack(api: str, max_wait: int, retry_delay: float) -> bool:
    """Poll the backend health endpoint until it responds or max_wait is exceeded."""
    health_url = f"{api}/api/v1/health"
    deadline = time.monotonic() + max_wait
    attempt = 0
    print(f"{CYAN}⏳ Waiting for backend to be ready (up to {max_wait}s)...{RESET}")
    while time.monotonic() < deadline:
        attempt += 1
        result = run_check(Check("backend health", health_url, timeout=5))
        if result.passed:
            print(f"{GREEN}✓ Backend ready after ~{attempt * retry_delay:.0f}s{RESET}\n")
            return True
        sys.stdout.write(f"\r  Attempt {attempt} — not yet ready, waiting {retry_delay:.0f}s...")
        sys.stdout.flush()
        time.sleep(retry_delay)
    print(f"\n{RED}✗ Backend did not become ready within {max_wait}s.{RESET}")
    print("  Check container logs with:  docker compose -f docker-compose.demo.yml logs backend")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test for the GradeWise demo stack.")
    parser.add_argument("--api-url",      default="http://localhost:8000")
    parser.add_argument("--frontend-url", default="http://localhost:3000")
    parser.add_argument("--mailpit-url",  default="http://localhost:8025")
    parser.add_argument("--max-wait",     type=int,   default=120,
                        help="Max seconds to wait for backend to become healthy (default: 120)")
    parser.add_argument("--retries",      type=int,   default=3,
                        help="Retry each check this many times on failure (default: 3)")
    parser.add_argument("--retry-delay",  type=float, default=3.0,
                        help="Seconds between retries (default: 3)")
    parser.add_argument("--no-wait",      action="store_true",
                        help="Skip the readiness wait loop and run checks immediately")
    args = parser.parse_args()

    print(f"\n{BOLD}GradeWise demo smoke test{RESET}")
    print(f"  API:      {args.api_url}")
    print(f"  Frontend: {args.frontend_url}")
    print(f"  Mailpit:  {args.mailpit_url}\n")

    # Wait for the stack to come up before running checks
    if not args.no_wait:
        ready = wait_for_stack(args.api_url, args.max_wait, args.retry_delay)
        if not ready:
            return 1

    checks = build_checks(args.api_url, args.frontend_url, args.mailpit_url)
    print(f"{BOLD}Running {len(checks)} checks...{RESET}\n")

    results: list[Result] = []
    for check in checks:
        result = run_check(check)
        for attempt in range(args.retries):
            if result.passed:
                break
            time.sleep(args.retry_delay)
            result = run_check(check)

        results.append(result)
        icon       = f"{GREEN}✓{RESET}" if result.passed else f"{RED}✗{RESET}"
        status_str = f"HTTP {result.status}" if result.status else ""
        elapsed    = f"{result.elapsed_ms:.0f}ms"
        extra      = f"  {YELLOW}{result.error}{RESET}" if result.error and not result.passed else ""
        print(f"  {icon}  {check.name:<52} {status_str:<10} {elapsed}{extra}")

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    print(f"\n{BOLD}Results: {GREEN}{passed} passed{RESET}{BOLD}, "
          f"{RED if failed else ''}{failed} failed{RESET}{BOLD} / {len(results)} total{RESET}")

    if failed == 0:
        print(f"\n{GREEN}{BOLD}✓ Demo stack is healthy.{RESET}")
        print(f"  Open the app:       http://localhost:3000")
        print(f"  API docs:           http://localhost:8000/docs")
        print(f"  Mailpit (email UI): http://localhost:8025")
        print(f"  MinIO console:      http://localhost:9001  (minioadmin / minioadmin)\n")
    else:
        print(f"\n{RED}{BOLD}✗ {failed} check(s) failed.{RESET}")
        print("  Inspect logs:  docker compose -f docker-compose.demo.yml logs")
        print("  Restart stack: docker compose -f docker-compose.demo.yml restart\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
