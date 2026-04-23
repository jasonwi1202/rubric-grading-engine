#!/usr/bin/env python3
"""
Smoke test — verifies the full Docker Compose stack is healthy and responding.

Usage:
    python scripts/smoke_test.py [--base-url http://localhost:8000] [--frontend-url http://localhost:3000]

Exit codes:
    0 — all checks passed
    1 — one or more checks failed

Run this after `docker compose up -d --wait` to confirm the stack is ready
before running Playwright E2E tests or a product demo.
"""

import argparse
import sys
import time
from dataclasses import dataclass, field
from typing import Optional
import urllib.request
import urllib.error


RESET = "\033[0m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
BOLD = "\033[1m"


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
        # --- Backend health ---
        Check("Backend: health endpoint", f"{api}/api/v1/health", body_contains='"status"'),

        # --- Frontend pages ---
        Check("Frontend: homepage (/)", f"{frontend}/"),
        Check("Frontend: /product", f"{frontend}/product"),
        Check("Frontend: /how-it-works", f"{frontend}/how-it-works"),
        Check("Frontend: /about", f"{frontend}/about"),
        Check("Frontend: /pricing", f"{frontend}/pricing"),
        Check("Frontend: /ai", f"{frontend}/ai"),
        Check("Frontend: /legal/terms", f"{frontend}/legal/terms"),
        Check("Frontend: /legal/privacy", f"{frontend}/legal/privacy"),
        Check("Frontend: /legal/ferpa", f"{frontend}/legal/ferpa"),
        Check("Frontend: /legal/dpa", f"{frontend}/legal/dpa"),
        Check("Frontend: /legal/ai-policy", f"{frontend}/legal/ai-policy"),
        Check("Frontend: /signup", f"{frontend}/signup"),
        Check("Frontend: /login", f"{frontend}/login"),
        # /dashboard should redirect unauthenticated users — we just verify it responds
        # (fetch follows redirects so we can't check for 307 directly)
        Check("Frontend: /dashboard responds", f"{frontend}/dashboard"),
        # M3 dashboard routes — confirm pages are registered (redirect to /login when unauthenticated)
        Check("Frontend: /dashboard/classes responds",     f"{frontend}/dashboard/classes"),
        Check("Frontend: /dashboard/rubrics/new responds", f"{frontend}/dashboard/rubrics/new"),

        # --- Mailpit ---
        Check("Mailpit: web UI reachable", f"{mailpit}/"),
        Check("Mailpit: API messages endpoint", f"{mailpit}/api/v1/messages", body_contains='"messages"'),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test the Docker Compose stack.")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--frontend-url", default="http://localhost:3000")
    parser.add_argument("--mailpit-url", default="http://localhost:8025")
    parser.add_argument("--retries", type=int, default=3, help="Retry failed checks this many times")
    parser.add_argument("--retry-delay", type=float, default=2.0, help="Seconds between retries")
    args = parser.parse_args()

    checks = build_checks(args.api_url, args.frontend_url, args.mailpit_url)

    print(f"\n{BOLD}Smoke test — {len(checks)} checks{RESET}")
    print(f"  API:      {args.api_url}")
    print(f"  Frontend: {args.frontend_url}")
    print(f"  Mailpit:  {args.mailpit_url}\n")

    results: list[Result] = []
    for check in checks:
        result = run_check(check)
        # Retry on failure
        for attempt in range(args.retries):
            if result.passed:
                break
            time.sleep(args.retry_delay)
            result = run_check(check)
            if not result.passed and attempt == args.retries - 1:
                break

        results.append(result)
        icon = f"{GREEN}✓{RESET}" if result.passed else f"{RED}✗{RESET}"
        status_str = f"HTTP {result.status}" if result.status else ""
        elapsed_str = f"{result.elapsed_ms:.0f}ms"
        extra = f"  {YELLOW}{result.error}{RESET}" if result.error and not result.passed else ""
        print(f"  {icon}  {check.name:<50} {status_str:<10} {elapsed_str}{extra}")

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    print(f"\n{BOLD}Results: {GREEN}{passed} passed{RESET}{BOLD}, "
          f"{RED if failed else ''}{failed} failed{RESET}{BOLD} / {len(results)} total{RESET}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
