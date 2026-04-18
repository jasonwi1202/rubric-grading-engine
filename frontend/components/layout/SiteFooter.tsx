import Link from "next/link";
import { PRODUCT_NAME } from "@/lib/constants";

const FOOTER_NAV_LINKS = [
  { label: "Product", href: "/product" },
  { label: "Pricing", href: "/pricing" },
  { label: "How It Works", href: "/how-it-works" },
  { label: "About", href: "/about" },
  { label: "AI Transparency", href: "/ai" },
] as const;

const LEGAL_LINKS = [
  { label: "Terms of Service", href: "/legal/terms" },
  { label: "Privacy Policy", href: "/legal/privacy" },
  { label: "FERPA Notice", href: "/legal/ferpa" },
  { label: "Data Processing Agreement", href: "/legal/dpa" },
  { label: "AI Use Policy", href: "/legal/ai-policy" },
] as const;

/**
 * Public site footer — rendered on all marketing pages.
 *
 * Accessibility:
 * - Uses <footer> with role="contentinfo" (implicit).
 * - Two nav landmarks, each with a distinct aria-label, so screen-reader
 *   users can navigate between them.
 */
export function SiteFooter() {
  const year = new Date().getFullYear();

  return (
    <footer className="border-t border-gray-200 bg-white" role="contentinfo">
      <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 gap-8 md:grid-cols-3">
          {/* Brand */}
          <div>
            <p className="text-lg font-bold text-gray-900">{PRODUCT_NAME}</p>
            <p className="mt-2 text-sm text-gray-500">
              AI-assisted grading for K-12 writing instruction. Teachers are
              always in control.
            </p>
          </div>

          {/* Site nav */}
          <nav aria-label="Footer navigation">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-400">
              Navigate
            </h2>
            <ul className="mt-4 space-y-2" role="list">
              {FOOTER_NAV_LINKS.map(({ label, href }) => (
                <li key={href}>
                  <Link
                    href={href}
                    className="text-sm text-gray-600 transition-colors hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                  >
                    {label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>

          {/* Legal nav */}
          <nav aria-label="Legal and compliance">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-400">
              Legal
            </h2>
            <ul className="mt-4 space-y-2" role="list">
              {LEGAL_LINKS.map(({ label, href }) => (
                <li key={href}>
                  <Link
                    href={href}
                    className="text-sm text-gray-600 transition-colors hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                  >
                    {label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </div>

        {/* Bottom bar */}
        <div className="mt-8 border-t border-gray-200 pt-8">
          <p className="text-sm text-gray-400">
            &copy; {year} {PRODUCT_NAME}. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  );
}
