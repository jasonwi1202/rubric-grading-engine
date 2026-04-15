# Frontend Architecture

## Overview

The frontend is a Next.js 14+ application using the App Router. It is a teacher-facing interface only — no student-facing views. The frontend communicates exclusively with the FastAPI backend; it has no direct database access and makes no LLM calls.

---

## Directory Structure

```
frontend/
├── app/                          # Next.js App Router — routes and layouts
│   ├── layout.tsx                # Root layout (auth shell, global providers)
│   ├── (auth)/
│   │   ├── login/page.tsx
│   │   └── layout.tsx
│   ├── (dashboard)/              # Authenticated teacher area
│   │   ├── layout.tsx            # Sidebar, nav, session guard
│   │   ├── page.tsx              # Dashboard home (worklist, recent activity)
│   │   ├── classes/
│   │   │   ├── page.tsx          # Class list
│   │   │   └── [classId]/
│   │   │       ├── page.tsx      # Class overview
│   │   │       ├── students/
│   │   │       │   └── [studentId]/page.tsx   # Student profile
│   │   │       └── assignments/
│   │   │           └── [assignmentId]/
│   │   │               ├── page.tsx           # Assignment overview
│   │   │               └── review/
│   │   │                   └── [essayId]/page.tsx  # Essay review
│   │   ├── rubrics/
│   │   │   ├── page.tsx
│   │   │   └── [rubricId]/page.tsx
│   │   └── worklist/
│   │       └── page.tsx
│
├── components/
│   ├── ui/                       # Base primitives (shadcn/ui wrappers)
│   ├── grading/                  # Essay review, score controls, feedback editor
│   ├── rubric/                   # Rubric builder components
│   ├── assignments/              # Assignment creation, submission tracking
│   ├── students/                 # Student profile, skill charts
│   ├── classes/                  # Class roster, heatmap, insights
│   └── layout/                   # Sidebar, nav, breadcrumbs, page shells
│
├── lib/
│   ├── api/                      # Typed API client (fetch wrappers per resource)
│   │   ├── client.ts             # Base fetch with auth headers and error handling
│   │   ├── assignments.ts
│   │   ├── essays.ts
│   │   ├── grades.ts
│   │   └── ...
│   ├── hooks/                    # React Query hooks (useAssignment, useGrade, etc.)
│   ├── schemas/                  # Zod schemas for form validation
│   └── utils/                    # Formatting, date helpers, etc.
│
├── types/                        # Shared TypeScript types (mirrors backend schemas)
├── middleware.ts                 # Auth route protection (Next.js middleware)
├── tailwind.config.ts
└── next.config.ts
```

---

## Routing Model

All authenticated routes live under the `(dashboard)` route group. The root layout for this group:
- Validates the session token via middleware before rendering
- Renders the persistent sidebar and navigation chrome
- Provides the React Query client to the subtree

Route structure mirrors the domain hierarchy:
```
/classes
/classes/[classId]
/classes/[classId]/students/[studentId]
/classes/[classId]/assignments/[assignmentId]
/classes/[classId]/assignments/[assignmentId]/review/[essayId]
/rubrics
/rubrics/[rubricId]
/worklist
```

---

## Data Fetching Strategy

### Server Components (read-heavy, no interactivity)
Used for: class overview, student profile, assignment analytics, worklist
- Fetch data on the server using the API client with the session cookie
- Pass data as props to client components that need interactivity
- Reduces client-side JavaScript and improves initial load

### Client Components + React Query (interactive, real-time)
Used for: essay review interface, batch grading progress, rubric builder
- React Query manages caching, background refetch, and optimistic updates
- Polling used for batch grading progress (every 3 seconds while a batch is running)
- Mutations (score overrides, feedback edits, grade locks) invalidate relevant query keys

### Server Actions
Used for: form submissions (assignment creation, rubric save, class creation)
- Keeps mutation logic close to the form
- Revalidates affected Server Component data via `revalidatePath`

---

## State Management

No global state store. State is managed at three levels:

| Level | Tool | Used for |
|---|---|---|
| Server state | React Query | All data from the API — grades, essays, profiles |
| Form state | React Hook Form + Zod | Rubric builder, assignment creation, feedback editing |
| Local UI state | useState / useReducer | Panels, modals, selection state within a view |

---

## API Client

All backend communication goes through typed fetch wrappers in `lib/api/`. These:
- Attach the auth token from the session cookie automatically
- Normalize error responses into typed error objects
- Are the only place where fetch is called — no inline fetch in components or hooks

```typescript
// Example shape
export async function getEssay(essayId: string): Promise<Essay> {
  return apiGet(`/essays/${essayId}`)
}

export async function updateGrade(essayId: string, payload: UpdateGradePayload): Promise<Grade> {
  return apiPatch(`/essays/${essayId}/grade`, payload)
}
```

---

## Authentication Flow

1. Teacher submits credentials → POST `/auth/login`
2. Backend returns access token + sets httpOnly refresh token cookie
3. Next.js middleware (`middleware.ts`) checks for valid session on all `(dashboard)` routes
4. On 401 responses, the API client attempts a silent token refresh; on failure, redirects to login
5. Logout clears both tokens

---

## Key Component Patterns

### Essay Review Interface
The most complex view. Structure:
- Left panel: essay text with inline highlights (from feedback or integrity flags)
- Right panel: rubric criteria with score controls and feedback text fields
- Score controls are controlled inputs — changes are local until the teacher explicitly saves
- Unsaved changes are tracked; navigating away prompts confirmation

### Rubric Builder
- Fully client-side while editing — no autosave
- Zod schema validates: all criteria named, weights sum to 100%, scale values consistent
- Save triggers a single API call with the full rubric payload

### Batch Progress
- Polling component polls `/assignments/{id}/grading-status` every 3 seconds while status is `processing`
- Renders a progress bar and per-essay status list
- Stops polling when status transitions to `complete` or `failed`

---

## Key Constraints

- No LLM calls from the frontend — ever
- No direct database access — all data through the FastAPI backend
- No `any` types in TypeScript — enforce with `strict: true` in tsconfig
- All API response types are defined in `types/` and kept in sync with backend Pydantic schemas
- Components in `components/ui/` are pure presentational — no API calls, no business logic
