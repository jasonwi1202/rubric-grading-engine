# UI Component Implementation Audit — M8-06

**Date:** 2026-05-04  
**Scope:** `frontend/components/`, `frontend/app/`  
**Status:** Complete  

---

## Audit Methodology

Systematic review of all client components for:

1. **React hook-rule compliance** — no conditional/looped hooks, correct dependency arrays, no stale closures
2. **Prop interface consistency** — `interface` over `type` for object props, explicit optional vs required, no inlined large objects
3. **State-management correctness** — derived state avoided, no redundant `useEffect+fetch`, controlled inputs remain controlled
4. **Accessibility semantics** — ARIA roles and labels, keyboard navigation, focus management, screen-reader announcements
5. **Error boundary placement** — isolated failure surfaces for complex panels

---

## Resolved Findings

### F-01 · No Error Boundaries Anywhere (CRITICAL)

**Files:** `frontend/app/layout.tsx`, `frontend/app/(dashboard)/layout.tsx`  
**Symptom:** Any JavaScript throw during the React render phase — from a bad API response shape, null-dereference, or unexpected prop value — crashed the entire page with a blank white screen and no user-facing message.  
**Fix:**

1. Created `frontend/components/layout/ErrorBoundary.tsx` — a reusable React class component implementing the error boundary contract (`getDerivedStateFromError` + `componentDidCatch`).  
   - Default fallback: `role="alert"` panel with a "Try again" button that resets `hasError` state.  
   - Accepts an optional `fallback` prop for custom surfaces.  
   - Security: `error.message` is **never** logged or rendered (it may contain student PII from unexpected template-literal values). Only `error.name` is logged in `development` mode.

2. Applied to the root layout (`app/layout.tsx`) inside the React Query `<Providers>` wrapper — all pages are protected.

3. Applied to the dashboard layout (`app/(dashboard)/layout.tsx`) around the `<main>` content — complex dashboard views fail in isolation without disrupting the trial banner or navigation chrome.

**Tests added:** `tests/unit/error-boundary.test.tsx` (5 tests):
- Renders children normally when no error occurs
- Shows default fallback when a child throws
- Shows custom fallback when provided
- "Try again" resets error state and re-renders children
- Fallback UI does not expose the raw error message

---

### F-02 · ProgressBar ARIA Semantics (MEDIUM)

**File:** `frontend/components/grading/BatchGradingPanel.tsx` — `ProgressBar` component  
**Symptom:** Two issues with the existing implementation:

1. `aria-valuenow`, `aria-valuemin`, and `aria-valuemax` were set as explicit DOM attributes on a native `<progress>` element. These are redundant because the HTML specification maps the `value` and `max` attributes to the same accessibility properties automatically. The duplicate explicit attributes produced warnings in some accessibility trees and created maintenance risk (the DOM attribute and the computed value could drift).

2. The outer `<div aria-label="Grading progress: N%">` had no role, meaning the `aria-label` was attached to a non-landmark, non-widget element where assistive technologies ignore it. The progress bar itself had no accessible name.

**Fix:**  
- Removed `aria-valuenow`, `aria-valuemin`, and `aria-valuemax` from `<progress>` (the browser supplies these from `value`/`max`).  
- Moved the `aria-label="Grading progress: N%"` directly onto the `<progress>` element so screen readers announce the label together with the native progress value.  
- Removed the `aria-label` from the outer `<div>` (a plain `<div>` does not expose labels to the accessibility tree).

**Tests updated:** `tests/unit/batch-grading.test.tsx` — three progress-bar assertions updated from `aria-valuenow` attribute checks to the native `value` and `max` attribute checks, plus a new assertion that the `aria-label` is present on the `<progress>` element.

---

## No-Action Findings (Deferred or Accepted)

### N-01 · `InterventionsPanel` prop-sync `useEffect`

The `useEffect(() => setStatusFilter(initialStatus), [initialStatus])` pattern in `InterventionsPanel` to mirror an external `initialStatus` prop into local state is a known controlled/uncontrolled synchronisation idiom. While derived state can sometimes be avoided, this specific case — syncing state when same-route navigation updates a query-param-derived prop — requires the effect. No hook rules are violated. Deferred to a future refactor toward URL-driven state.

### N-02 · `CriterionCard` multiple sync `useEffect` hooks

`EssayReviewPanel.tsx` contains two `useEffect` hooks in `CriterionCard` that sync displayed `scoreInput` and `feedbackInput` when the persisted server values change (e.g. after a successful save returns a server-clamped value). These are intentional and correct — the comment in the code explains why a direct derivation is avoided (overwriting unsaved local edits on background refetch). Hook rules are not violated. No action required.

### N-03 · `<ul role="list">` in `WorklistPanel` and `InterventionsPanel`

Both panels use `<ul role="list">`. This is the recommended Tailwind CSS/VoiceOver workaround where Tailwind's `list-none` CSS removes native list semantics in Safari + VoiceOver; the explicit `role="list"` restores them. This is a documented, intentional, correct pattern. No action required.

### N-04 · Next.js App Router `error.tsx` files

No `error.tsx` files exist in any route segment. The React error boundary added at the root and dashboard layouts provides an equivalent safety net for all routes. Dedicated per-route `error.tsx` files can be added if route-level recovery UI is needed in a future milestone; this is out of scope for M8-06.

### N-05 · shadcn/ui `Dialog` wrapper

Several modals (`AddStudentDialog`, `RemoveStudentDialog`, `CsvImportDialog`) use raw `<div>` implementations rather than Radix UI / shadcn `Dialog`. The focus-trap, Escape-close, and portal behaviours are hand-rolled. These components pass the existing test suite and the hand-rolled implementations correctly implement the required baseline (focus-in on open, Escape close, focus-back on close). Migrating to Radix `Dialog` is deferred to a future shadcn/ui component pass.

---

## Summary

| Finding | Severity | Status |
|---|---|---|
| F-01: No error boundaries | Critical | ✅ Fixed |
| F-02: ProgressBar ARIA semantics | Medium | ✅ Fixed |
| N-01: `InterventionsPanel` prop-sync effect | Low | Deferred |
| N-02: `CriterionCard` sync effects | Low | Accepted (intentional) |
| N-03: `<ul role="list">` | Informational | Accepted (correct pattern) |
| N-04: Next.js `error.tsx` files | Low | Deferred |
| N-05: Modal shadcn/ui migration | Low | Deferred |

All critical and medium issues are resolved. No security or FERPA-compliance deficiencies were introduced or left unaddressed.
