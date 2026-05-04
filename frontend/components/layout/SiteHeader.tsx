"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Menu, X } from "lucide-react";
import { PRODUCT_NAME } from "@/lib/constants";

/** Primary navigation links shown in the site header. */
const NAV_LINKS = [
  { label: "Product", href: "/product" },
  { label: "How It Works", href: "/how-it-works" },
  { label: "Pricing", href: "/pricing" },
  { label: "AI", href: "/ai" },
  { label: "About", href: "/about" },
] as const;

/**
 * Auth / CTA links.  Defined once and shared between the desktop header and
 * the mobile drawer so labels, hrefs, and future tracking params stay in sync.
 */
const AUTH_LINKS = [
  { label: "Sign in", href: "/login", variant: "text" as const },
  { label: "Start free trial", href: "/signup", variant: "primary" as const },
] as const;

/**
 * Public site header — rendered on all marketing pages.
 *
 * Accessibility:
 * - The outer element uses <header> with role="banner" (implicit from <header>).
 * - The nav element uses role="navigation" with an aria-label to distinguish it
 *   from other nav landmarks on the same page.
 * - The "Sign in" and "Start free trial" links are standard <a> elements and are
 *   fully keyboard-reachable in document order.
 * - The mobile menu toggle uses aria-expanded and aria-controls so screen-reader
 *   users know the state of the disclosure.
 * - Focus returns to the toggle button when the mobile drawer closes via a nav
 *   link click (keyboard / screen-reader UX).
 * - Pressing Escape while the drawer is open closes it and returns focus to the
 *   toggle button.
 */
export function SiteHeader() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);

  // Close on Escape and return focus to the toggle button.
  useEffect(() => {
    if (!mobileMenuOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMobileMenuOpen(false);
        toggleRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [mobileMenuOpen]);

  /** Close the mobile drawer and return focus to the toggle button. */
  function closeMobileMenu() {
    setMobileMenuOpen(false);
    // Return focus to the toggle button so keyboard/SR users are not stranded.
    toggleRef.current?.focus();
  }

  return (
    <header className="sticky top-0 z-40 w-full border-b border-gray-200 bg-white/95 backdrop-blur supports-[backdrop-filter]:bg-white/60">
      <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        {/* Logo / brand */}
        <Link
          href="/"
          className="text-xl font-bold text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
          aria-label={`${PRODUCT_NAME} home`}
        >
          {PRODUCT_NAME}
        </Link>

        {/* Primary navigation — hidden below md */}
        <nav aria-label="Main navigation" className="hidden md:block">
          <ul className="flex items-center gap-6" role="list">
            {NAV_LINKS.map(({ label, href }) => (
              <li key={href}>
                <Link
                  href={href}
                  className="text-sm font-medium text-gray-600 transition-colors hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                >
                  {label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        {/* Auth actions + mobile toggle */}
        <div className="flex items-center gap-3">
          {AUTH_LINKS.map(({ label, href, variant }) => (
            <Link
              key={href}
              href={href}
              className={
                variant === "primary"
                  ? "hidden rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 md:inline-flex"
                  : "hidden text-sm font-medium text-gray-600 transition-colors hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 md:inline-flex"
              }
            >
              {label}
            </Link>
          ))}

          {/* Mobile menu toggle — visible below md only */}
          <button
            ref={toggleRef}
            type="button"
            className="inline-flex items-center justify-center rounded-md p-2 text-gray-600 hover:bg-gray-100 hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 md:hidden"
            aria-label={mobileMenuOpen ? "Close menu" : "Open menu"}
            aria-expanded={mobileMenuOpen}
            aria-controls="mobile-nav"
            onClick={() => setMobileMenuOpen((open) => !open)}
          >
            {mobileMenuOpen ? (
              <X className="h-6 w-6" aria-hidden="true" />
            ) : (
              <Menu className="h-6 w-6" aria-hidden="true" />
            )}
          </button>
        </div>
      </div>

      {/* Mobile navigation drawer */}
      {mobileMenuOpen && (
        <nav
          id="mobile-nav"
          aria-label="Mobile navigation"
          className="border-t border-gray-200 bg-white md:hidden"
        >
          <ul className="space-y-1 px-4 py-3" role="list">
            {NAV_LINKS.map(({ label, href }) => (
              <li key={href}>
                <Link
                  href={href}
                  className="block rounded-md px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
                  onClick={closeMobileMenu}
                >
                  {label}
                </Link>
              </li>
            ))}
          </ul>
          <div className="border-t border-gray-100 px-4 py-3">
            {AUTH_LINKS.map(({ label, href, variant }) => (
              <Link
                key={href}
                href={href}
                className={
                  variant === "primary"
                    ? "mt-2 block rounded-md bg-blue-600 px-3 py-2 text-center text-sm font-semibold text-white hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                    : "block rounded-md px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
                }
                onClick={closeMobileMenu}
              >
                {label}
              </Link>
            ))}
          </div>
        </nav>
      )}

      {/*
       * No-JS fallback: when hydration has not yet run (or is disabled) the
       * toggle button above is inert.  This <noscript> block renders a static
       * drawer that is always visible for mobile viewports, giving users
       * without JavaScript a way to reach every public page and the auth CTAs.
       */}
      <noscript>
        <nav
          aria-label="Mobile navigation (no-JS fallback)"
          className="border-t border-gray-200 bg-white md:hidden"
        >
          <ul className="space-y-1 px-4 py-3" role="list">
            {NAV_LINKS.map(({ label, href }) => (
              <li key={href}>
                <a
                  href={href}
                  className="block rounded-md px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
                >
                  {label}
                </a>
              </li>
            ))}
          </ul>
          <div className="border-t border-gray-100 px-4 py-3">
            {AUTH_LINKS.map(({ label, href, variant }) => (
              <a
                key={href}
                href={href}
                className={
                  variant === "primary"
                    ? "mt-2 block rounded-md bg-blue-600 px-3 py-2 text-center text-sm font-semibold text-white hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                    : "block rounded-md px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
                }
              >
                {label}
              </a>
            ))}
          </div>
        </nav>
      </noscript>
    </header>
  );
}
