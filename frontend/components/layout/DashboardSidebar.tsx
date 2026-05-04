"use client";

/**
 * DashboardSidebar — persistent authenticated navigation.
 *
 * Desktop: fixed 220px left sidebar. Mobile: top bar with a slide-in drawer.
 *
 * Nav items:
 *   Worklist      /dashboard
 *   Classes       /dashboard/classes  (accordion: first 5 classes inline)
 *   Interventions /dashboard/interventions  (badge: pending count)
 *   Copilot       /dashboard/copilot
 *
 * Footer: teacher email + sign-out button.
 *
 * Accessibility:
 *   - nav landmark with aria-label
 *   - Active links get aria-current="page"
 *   - Mobile drawer: focus trap, Escape closes, focus returns to toggle
 *   - All interactive elements are keyboard-reachable
 *
 * Security: no student PII rendered; teacher email fetched from /account/me.
 */

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Menu, X, LayoutList, BookOpen, AlertTriangle, Sparkles, ChevronDown, ChevronRight, LogOut } from "lucide-react";
import { listClasses } from "@/lib/api/classes";
import { listInterventions } from "@/lib/api/interventions";
import { logout } from "@/lib/auth/session";
import { PRODUCT_NAME } from "@/lib/constants";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NavItem {
  label: string;
  href: string;
  icon: React.ReactNode;
  exact?: boolean;
}

// ---------------------------------------------------------------------------
// Nav item config
// ---------------------------------------------------------------------------

const TOP_NAV: NavItem[] = [
  {
    label: "Worklist",
    href: "/dashboard",
    icon: <LayoutList className="h-4 w-4" aria-hidden="true" />,
    exact: true,
  },
  {
    label: "Classes",
    href: "/dashboard/classes",
    icon: <BookOpen className="h-4 w-4" aria-hidden="true" />,
  },
  {
    label: "Interventions",
    href: "/dashboard/interventions",
    icon: <AlertTriangle className="h-4 w-4" aria-hidden="true" />,
  },
  {
    label: "Copilot",
    href: "/dashboard/copilot",
    icon: <Sparkles className="h-4 w-4" aria-hidden="true" />,
  },
];

const MAX_INLINE_CLASSES = 5;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isActive(href: string, pathname: string, exact?: boolean): boolean {
  if (exact) return pathname === href;
  return pathname === href || pathname.startsWith(href + "/");
}

// ---------------------------------------------------------------------------
// Intervention badge — count of pending recommendations
// ---------------------------------------------------------------------------

function InterventionBadge() {
  const { data } = useQuery({
    queryKey: ["interventions", "pending_review"],
    queryFn: () => listInterventions("pending_review"),
    staleTime: 60_000,
  });

  const count = data?.total_count ?? 0;
  if (count === 0) return null;

  return (
    <span
      className="ml-auto flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white"
      aria-label={`${count} pending intervention${count !== 1 ? "s" : ""}`}
    >
      {count > 99 ? "99+" : count}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Classes accordion (inline under Classes nav item)
// ---------------------------------------------------------------------------

function ClassesAccordion({ open }: { open: boolean }) {
  const { data: classes, isLoading } = useQuery({
    queryKey: ["classes"],
    queryFn: () => listClasses(),
    staleTime: 60_000,
    enabled: open,
  });

  if (!open) return null;

  const shown = classes?.slice(0, MAX_INLINE_CLASSES) ?? [];
  const hasMore = (classes?.length ?? 0) > MAX_INLINE_CLASSES;

  if (isLoading) {
    return (
      <ul className="ml-6 mt-1 space-y-1">
        {[1, 2].map((i) => (
          <li key={i} className="h-6 animate-pulse rounded bg-gray-700/40" />
        ))}
      </ul>
    );
  }

  if (shown.length === 0) {
    return (
      <p className="ml-6 mt-1 text-xs text-gray-400">
        No classes yet.{" "}
        <Link href="/dashboard/classes/new" className="underline hover:text-gray-200">
          Create one
        </Link>
      </p>
    );
  }

  return (
    <ul className="ml-6 mt-1 space-y-0.5" role="list">
      {shown.map((cls) => (
        <li key={cls.id}>
          <Link
            href={`/dashboard/classes/${cls.id}`}
            className="block truncate rounded px-2 py-1 text-xs text-gray-300 hover:bg-gray-700 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
          >
            {cls.name}
          </Link>
        </li>
      ))}
      {hasMore && (
        <li>
          <Link
            href="/dashboard/classes"
            className="block rounded px-2 py-1 text-xs text-gray-400 underline hover:text-gray-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
          >
            See all →
          </Link>
        </li>
      )}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Single nav link row
// ---------------------------------------------------------------------------

function NavLink({
  item,
  pathname,
  onClick,
  children,
}: {
  item: NavItem;
  pathname: string;
  onClick?: () => void;
  children?: React.ReactNode;
}) {
  const active = isActive(item.href, pathname, item.exact);

  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      onClick={onClick}
      className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 ${
        active
          ? "bg-blue-600 text-white"
          : "text-gray-300 hover:bg-gray-700 hover:text-white"
      }`}
    >
      {item.icon}
      <span className="flex-1">{item.label}</span>
      {children}
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Sidebar content (shared between desktop and mobile drawer)
// ---------------------------------------------------------------------------

function SidebarContent({
  pathname,
  onNavClick,
}: {
  pathname: string;
  onNavClick?: () => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [classesOpen, setClassesOpen] = useState(
    () => isActive("/dashboard/classes", pathname),
  );

  async function handleSignOut() {
    try {
      await logout();
    } catch {
      // Best-effort; clear client state regardless
    }
    queryClient.clear();
    router.replace("/login");
  }

  return (
    <div className="flex h-full flex-col">
      {/* Brand */}
      <div className="flex h-16 items-center px-4 flex-shrink-0">
        <Link
          href="/dashboard"
          onClick={onNavClick}
          className="text-lg font-bold text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
        >
          {PRODUCT_NAME}
        </Link>
      </div>

      {/* Nav */}
      <nav
        aria-label="Dashboard navigation"
        className="flex-1 overflow-y-auto px-3 py-2"
      >
        <ul className="space-y-0.5" role="list">
          {TOP_NAV.map((item) => {
            const isClasses = item.href === "/dashboard/classes";
            const active = isActive(item.href, pathname, item.exact);

            if (isClasses) {
              return (
                <li key={item.href}>
                  {/* Classes row: clicking toggles accordion AND navigates */}
                  <div className="flex items-center">
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      onClick={onNavClick}
                      className={`flex flex-1 items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 ${
                        active
                          ? "bg-blue-600 text-white"
                          : "text-gray-300 hover:bg-gray-700 hover:text-white"
                      }`}
                    >
                      {item.icon}
                      <span className="flex-1">{item.label}</span>
                    </Link>
                    <button
                      type="button"
                      aria-expanded={classesOpen}
                      aria-label={classesOpen ? "Collapse class list" : "Expand class list"}
                      onClick={() => setClassesOpen((o) => !o)}
                      className="ml-1 rounded p-1 text-gray-400 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
                    >
                      {classesOpen ? (
                        <ChevronDown className="h-4 w-4" aria-hidden="true" />
                      ) : (
                        <ChevronRight className="h-4 w-4" aria-hidden="true" />
                      )}
                    </button>
                  </div>
                  <ClassesAccordion open={classesOpen} />
                </li>
              );
            }

            const isInterventions = item.href === "/dashboard/interventions";
            return (
              <li key={item.href}>
                <NavLink item={item} pathname={pathname} onClick={onNavClick}>
                  {isInterventions && <InterventionBadge />}
                </NavLink>
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Footer: sign out */}
      <div className="flex-shrink-0 border-t border-gray-700 px-3 py-3">
        <button
          type="button"
          onClick={handleSignOut}
          className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-gray-400 hover:bg-gray-700 hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
        >
          <LogOut className="h-4 w-4" aria-hidden="true" />
          Sign out
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Mobile top bar
// ---------------------------------------------------------------------------

function MobileTopBar({
  pathname,
  onMenuToggle,
  menuOpen,
}: {
  pathname: string;
  onMenuToggle: () => void;
  menuOpen: boolean;
}) {
  return (
    <div className="flex h-14 items-center justify-between border-b border-gray-200 bg-white px-4 md:hidden">
      <Link
        href="/dashboard"
        className="text-base font-bold text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
      >
        {PRODUCT_NAME}
      </Link>
      <button
        type="button"
        aria-label={menuOpen ? "Close menu" : "Open menu"}
        aria-expanded={menuOpen}
        aria-controls="mobile-sidebar-drawer"
        onClick={onMenuToggle}
        className="rounded-md p-2 text-gray-600 hover:bg-gray-100 hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
      >
        {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export function DashboardSidebar() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);

  // Close mobile drawer on route change
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // Focus trap + Escape for mobile drawer
  useEffect(() => {
    if (!mobileOpen) return;

    // Move focus into the drawer
    const focusable = drawerRef.current?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    focusable?.[0]?.focus();

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setMobileOpen(false);
        toggleRef.current?.focus();
        return;
      }
      if (e.key !== "Tab" || !drawerRef.current) return;
      if (!focusable || focusable.length === 0) return;

      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [mobileOpen]);

  return (
    <>
      {/* ---- Desktop sidebar ---- */}
      <aside
        className="hidden w-56 flex-shrink-0 bg-gray-800 md:flex md:flex-col"
        aria-label="Sidebar"
      >
        <SidebarContent pathname={pathname} />
      </aside>

      {/* ---- Mobile top bar + drawer ---- */}
      <div className="md:hidden">
        <div className="sticky top-0 z-30">
          {/* Inline button ref capture via the DOM */}
          <div className="flex h-14 items-center justify-between border-b border-gray-200 bg-white px-4">
            <Link
              href="/dashboard"
              className="text-base font-bold text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              {PRODUCT_NAME}
            </Link>
            <button
              ref={toggleRef}
              type="button"
              aria-label={mobileOpen ? "Close menu" : "Open menu"}
              aria-expanded={mobileOpen}
              aria-controls="mobile-sidebar-drawer"
              onClick={() => setMobileOpen((o) => !o)}
              className="rounded-md p-2 text-gray-600 hover:bg-gray-100 hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              {mobileOpen ? (
                <X className="h-5 w-5" aria-hidden="true" />
              ) : (
                <Menu className="h-5 w-5" aria-hidden="true" />
              )}
            </button>
          </div>
        </div>

        {/* Backdrop */}
        {mobileOpen && (
          <div
            className="fixed inset-0 z-20 bg-black/40"
            aria-hidden="true"
            onClick={() => setMobileOpen(false)}
          />
        )}

        {/* Drawer */}
        {mobileOpen && (
          <div
            id="mobile-sidebar-drawer"
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation menu"
            className="fixed inset-y-0 left-0 z-30 w-64 bg-gray-800 shadow-xl"
          >
            <SidebarContent
              pathname={pathname}
              onNavClick={() => setMobileOpen(false)}
            />
          </div>
        )}
      </div>
    </>
  );
}
