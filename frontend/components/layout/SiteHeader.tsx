import Link from "next/link";
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
 * Public site header — rendered on all marketing pages.
 *
 * Accessibility:
 * - The outer element uses <header> with role="banner" (implicit from <header>).
 * - The nav element uses role="navigation" with an aria-label to distinguish it
 *   from other nav landmarks on the same page.
 * - The "Sign in" and "Start free trial" links are standard <a> elements and are
 *   fully keyboard-reachable in document order.
 * - The mobile menu toggle is not included here — it will be added in a future
 *   milestone once the design is finalised.
 */
export function SiteHeader() {
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

        {/* Primary navigation */}
        <nav aria-label="Main navigation">
          <ul className="hidden items-center gap-6 md:flex" role="list">
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

        {/* Auth actions */}
        <div className="flex items-center gap-3">
          <Link
            href="/login"
            className="text-sm font-medium text-gray-600 transition-colors hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
          >
            Sign in
          </Link>
          <Link
            href="/signup"
            className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
          >
            Start free trial
          </Link>
        </div>
      </div>
    </header>
  );
}
