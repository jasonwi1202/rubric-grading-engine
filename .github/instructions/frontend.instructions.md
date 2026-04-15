---
applyTo: "frontend/**"
---

# Frontend Engineer Review Instructions

When reviewing a PR that touches `frontend/**`, check every item below.

## API Client

- [ ] All API calls go through `lib/api/client.ts` and the typed resource wrappers in `lib/api/` — no raw `fetch()` in components or hooks
- [ ] API response types are defined in `types/` and kept in sync with backend Pydantic schemas
- [ ] No hardcoded API URLs — use `NEXT_PUBLIC_API_URL` environment variable
- [ ] No API keys or secrets in any frontend file — all sensitive operations go through the backend

## Data Fetching (React Query v5)

- [ ] All server state uses `useQuery` / `useMutation` — never `useEffect + fetch`
- [ ] Query keys are structured arrays: `['essays', assignmentId]` not flat strings
- [ ] Mutations include `onError` handler; optimistic updates include `onMutate` rollback
- [ ] `staleTime` set appropriately — grading progress is near-real-time (3s poll); reference data longer
- [ ] Polling (`refetchInterval`) is used only for batch grading progress — and stops when status is `complete` or `failed`
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
- [ ] Never render `error.message` directly to the user
- [ ] Skeleton components use `shadcn/ui Skeleton` for consistency
- [ ] Empty states (zero results) are explicitly handled and not left blank

## Accessibility (WCAG 2.1 AA)

- [ ] All interactive elements reachable by keyboard (Tab, Enter, Space, Arrow keys for menus)
- [ ] No icon-only buttons without `aria-label`
- [ ] Form errors linked to inputs via `aria-describedby`
- [ ] Modal dialogs trap focus (Radix UI / shadcn handles this — verify not overridden)
- [ ] Color is not the only means of conveying state (score badges, status indicators include text)
- [ ] Real-time updates (grading progress) announced via `aria-live="polite"` region

## Tests Required

- [ ] Vitest + React Testing Library test for every new component
- [ ] Test covers: renders correctly, loading state, error state, key user interactions
- [ ] New user journeys added to `frontend/tests/e2e/` as Playwright specs
- [ ] MSW handlers defined in `frontend/tests/integration/` for any new API endpoints used

## TypeScript

- [ ] TypeScript strict mode — `strict: true` in `tsconfig.json`
- [ ] Component props interfaces are explicitly typed — no implicit object spread types
- [ ] Zod schemas used for form validation use `z.infer<>` to derive the TypeScript type
