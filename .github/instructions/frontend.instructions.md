---
applyTo: "frontend/**"
---

# Frontend Engineer Review Instructions

When reviewing a PR that touches `frontend/**`, check every item below.

## API Client

- [ ] All API calls go through `lib/api/client.ts` and the typed resource wrappers in `lib/api/` — no raw `fetch()` in components or hooks
- [ ] **API response types in `lib/api/` are verified against the actual Pydantic schemas in `backend/app/schemas/` before merge** — field names, nullability (`string | null` vs `string`), and shape must match exactly. Mismatched types cause runtime errors that TypeScript cannot catch because `apiGet()` returns `data` from the envelope.
- [ ] **All new TypeScript API types are cross-checked against the backend** — run a quick side-by-side comparison of the `Response`/`Request` types here against the Pydantic `Response`/`Request` schemas. Pay specific attention to: optional vs required fields, `null` vs `undefined`, nested object shapes, and fields the backend returns that are not yet on the frontend type.
- [ ] **API helper paths must be relative (no `/api/v1/` prefix)** — `NEXT_PUBLIC_API_URL` already includes `/api/v1`. Using a full path like `/api/v1/contact/inquiry` produces a double-prefix at runtime. All paths passed to `apiGet`/`apiPost` must be relative, e.g., `/contact/inquiry`.
- [ ] No hardcoded API URLs — use `NEXT_PUBLIC_API_URL` environment variable
- [ ] No API keys or secrets in any frontend file — all sensitive operations go through the backend

## Data Fetching (React Query v5)

- [ ] All server state uses `useQuery` / `useMutation` — never `useEffect + fetch`
- [ ] Query keys are structured arrays: `['essays', assignmentId]` not flat strings
- [ ] **Query keys include all parameters that vary the response** — if a query accepts filter params (e.g. `is_archived: false`), those params must be part of the key. A key that omits params causes different filter combinations to share the same cache entry.
- [ ] Mutations include `onError` handler; optimistic updates include `onMutate` rollback
- [ ] `staleTime` set appropriately — grading progress is near-real-time (3s poll); reference data longer
- [ ] Polling (`refetchInterval`) is used only for batch grading progress — and stops when status is `complete` or `failed`
- [ ] **After a mutation, invalidate all affected query keys** — not just the directly mutated entity. For example: adding/removing a student must also invalidate the class detail if it has a `student_count`; a status transition must also invalidate assignment list queries.
- [ ] **Do not wire UI to backend endpoints that do not yet exist** — if a required backend endpoint is not implemented, set `enabled: false` on the query or disable the mutation trigger. A UI that calls a non-existent endpoint will error on load in every environment.
- [ ] No direct cache manipulation outside of `onMutate` / `onSettled` patterns

## Components & Styling

- [ ] All components use **shadcn/ui** primitives from `components/ui/` — no third-party component libraries added
- [ ] All styling via **Tailwind CSS** — no custom CSS files, no inline `style={{}}` props
- [ ] Components in `components/ui/` are purely presentational — no API calls, no business logic
- [ ] No `any` types in TypeScript — use `unknown` + type narrowing if needed
- [ ] No `// @ts-ignore` or `// @ts-expect-error` without inline explanation

## Forms

- [ ] Forms use `react-hook-form` with `zodResolver` — no uncontrolled form state
- [ ] Zod schema defined separately and reused via `useForm({ resolver: zodResolver(schema) })`
- [ ] **Zod validation constraints must match backend Pydantic constraints exactly** — verify field `max_length`, numeric `min`/`max`, and required vs optional against the backend schema. A mismatch produces avoidable 422 errors (frontend accepts input the API rejects) or blocks valid input (frontend is stricter than the API).
- [ ] Clearing a nullable field sends explicit `null` in the request body — never `undefined`
- [ ] Form submission is disabled while mutation is pending

## Teacher-Only UI Enforcement

- [ ] No student-facing views, routes, or components — this is a teacher-only interface
- [ ] No student account creation, student login, or student-accessible endpoints are referenced in the frontend
- [ ] Student data (essays, grades, profiles) is rendered in teacher-controlled contexts only

## FERPA / Student Data Display

- [ ] Student names and essay content never appear in: `console.log`, `localStorage`, `sessionStorage`, URL query params, error toast messages
- [ ] Error messages shown to users never include raw API error details that might contain student data
- [ ] No student PII is stored in client-side state beyond what is needed for the current view

## Grade Integrity

- [ ] Grade display always uses `final_score` (`teacher_score ?? ai_score`) — never `ai_score` alone
- [ ] Locked grades (`is_locked: true`) render all edit controls as disabled
- [ ] Score overrides trigger an optimistic update and invalidate the grade query key on settlement
- [ ] Unsaved changes in the review interface are tracked — navigating away prompts confirmation

## Loading & Error States

- [ ] Every data-fetching component handles `isLoading` → skeleton, `isError` → user-friendly message
- [ ] **Never render `error.message` or server-supplied error text directly to users** — server error strings can be unstable, expose internal details, or include student PII. Map to a small set of safe UI strings based on `err.code` or HTTP status (e.g., `'invalid_credentials'` → "Email or password is incorrect", generic fallback otherwise).
- [ ] Mutation errors are visible without obstruction — if a modal/overlay closes on error, the error state remains visible in the underlying screen context
- [ ] Skeleton components use `shadcn/ui Skeleton` for consistency
- [ ] Empty states (zero results) are explicitly handled and not left blank

## Accessibility (WCAG 2.1 AA)

- [ ] All interactive elements reachable by keyboard (Tab, Enter, Space, Arrow keys for menus)
- [ ] No icon-only buttons without `aria-label`
- [ ] Form errors linked to inputs via `aria-describedby`
- [ ] **Every new modal/dialog must implement the full accessibility baseline** — use the shared dialog primitive or verify all four properties are present: (1) focus moves into the dialog on open, (2) focus is trapped inside while open (Tab/Shift-Tab cycle within), (3) Escape closes the dialog, (4) focus returns to the triggering element on close. Radix UI / shadcn `Dialog` handles this automatically — do not override `onOpenAutoFocus`, `onCloseAutoFocus`, or `onEscapeKeyDown` in ways that disable these behaviors.
- [ ] Dialog keyboard handlers are scoped to the dialog container (no global `window` listeners for Escape/Tab focus management)
- [ ] Repeated interactive controls use unique `id` values and, where applicable, matching `aria-controls` / `aria-labelledby` attributes
- [ ] **`role="listbox"` / `role="option"` require matching keyboard semantics** — Arrow key navigation and `aria-activedescendant` or roving tabindex. If keyboard semantics are not implemented, use `role="list"` / `role="listitem"` with plain buttons instead.
- [ ] Color is not the only means of conveying state (score badges, status indicators include text)
- [ ] Real-time updates (grading progress) announced via `aria-live="polite"` region

## Next.js Route Groups & Middleware

- [ ] **Route group names (`(auth)`, `(dashboard)`, `(public)`) do not produce URL path segments** — `app/(dashboard)/page.tsx` is served at `/`, not `/dashboard`. Middleware `matcher` patterns must target the actual URL, not the folder name. Verify that `matcher` in `middleware.ts` fires for all routes that need protection.
- [ ] When adding a new protected route, confirm the middleware matcher pattern covers it and test an unauthenticated request manually.

## Tests Required

- [ ] Vitest + React Testing Library test for every new component
- [ ] Test covers: renders correctly, loading state, error state, key user interactions
- [ ] New user journeys added to `frontend/tests/e2e/` as Playwright specs
- [ ] MSW handlers defined in `frontend/tests/integration/` for any new API endpoints used

## TypeScript

- [ ] TypeScript strict mode — `strict: true` in `tsconfig.json`
- [ ] Component props interfaces are explicitly typed — no implicit object spread types
- [ ] Zod schemas used for form validation use `z.infer<>` to derive the TypeScript type
