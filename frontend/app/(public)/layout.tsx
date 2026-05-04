import { SiteHeader } from "@/components/layout/SiteHeader";
import { SiteFooter } from "@/components/layout/SiteFooter";

/**
 * Public site layout — wraps all marketing and informational pages.
 *
 * This layout provides the shared site header (with primary navigation and
 * auth CTAs) and footer (with nav links, legal links, and copyright).
 *
 * It is intentionally separate from the (dashboard) layout, which handles
 * authenticated teacher sessions and renders the app chrome (sidebar, etc.).
 */
export default function PublicLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="public-page flex min-h-screen flex-col">
      <SiteHeader />
      <main className="flex-1">{children}</main>
      <SiteFooter />
    </div>
  );
}
