# Feature: Public Marketing Website

**Phase:** 0 — Scaffold / Pre-launch
**Status:** Planned

---

## Purpose

The public-facing marketing website is the primary acquisition surface. It converts curious teachers and administrators into trial sign-ups. It must communicate the product's value clearly, establish trust, and make it obvious what the product does — before a single login.

The public site lives at the root of the same Next.js project as the app. Public routes are accessible without authentication; app routes under `/(dashboard)` are protected.

---

## Route Structure

| Route | Page |
|---|---|
| `/` | Landing / Home |
| `/product` | Product overview (features in depth) |
| `/how-it-works` | Step-by-step workflow explainer |
| `/pricing` | Pricing page (see `pricing-page.md`) |
| `/about` | About page |
| `/ai` | AI transparency page (see `ai-transparency-page.md`) |
| `/blog` | Blog / resources index (Phase 2+, not needed at launch) |
| `/legal/terms` | Terms of Service |
| `/legal/privacy` | Privacy Policy |
| `/legal/ferpa` | FERPA + COPPA notice |
| `/legal/dpa` | Data Processing Agreement info page |
| `/login` | Login page (redirects to `/dashboard` if already authenticated) |
| `/signup` | Sign-up / trial start |

All public pages share a common layout: site header with nav, footer with legal links. The app's `/(dashboard)` layout is entirely separate.

---

## Landing Page (`/`)

### Purpose
Convert a teacher who has never heard of the product into someone who clicks "Start free trial." Secondary goal: give an administrator enough information to forward the link to their department head.

### Sections

**Hero:**
- Headline: the core value proposition in one sentence (benefits-first, not feature-first)
- Sub-headline: one sentence expanding on how
- Primary CTA: "Start free trial" → `/signup`
- Secondary CTA: "See how it works" → `/how-it-works` or scrolls to demo section
- Social proof signal: e.g., "Used by teachers in X schools across Y states" (placeholder until real numbers)

**Problem → Solution:**
- The grading loop problem framed in teacher language (time, disconnection from instruction)
- How the product breaks the loop
- Keep to 3–4 short paragraphs or a visual before/after

**Feature highlights (3–4 cards):**
- AI grading with transparent reasoning
- Student skill profiles and gap detection
- Teacher-guided instruction priorities
- Human-in-the-loop — teacher always decides

**Social proof / testimonials:**
- 2–3 teacher quotes with name, grade level, and school type (public/private)
- Placeholder section until real testimonials are collected

**How it works (abbreviated):**
- 3-step visual: Upload essays → Review AI grades → Act on insights
- Link to full `/how-it-works` page

**CTA section:**
- Repeat primary CTA with urgency/benefit framing
- "No credit card required" or equivalent trust signal

**Footer:**
- Navigation links: Product, Pricing, About, AI Transparency, Blog
- Legal links: Terms, Privacy, FERPA Notice
- Social links (placeholder)
- Copyright and product name

---

## Product Page (`/product`)

Detailed feature walkthrough for teachers doing due diligence before signing up or requesting a demo for their school.

### Sections

**Feature deep-dives** (one section per major feature area):
1. AI grading engine — rubric-based, criterion-level scores, written justifications
2. Human-in-the-loop review — override any score, edit any feedback, lock when ready
3. Student skill profiles — persistent tracking across assignments, trend detection
4. Class insights — heatmap, common issues, score distribution
5. Teacher worklist — prioritized actions, not a dashboard to explore
6. Export and sharing — PDFs, CSV, clipboard copy

Each section: headline, 2–3 sentences of explanation, and a screenshot or illustration placeholder.

**Trust and compliance callout:**
- FERPA compliance
- No student data used for AI training
- Teacher always in control (HITL principle)
- Link to `/ai` and `/legal/ferpa`

---

## How It Works Page (`/how-it-works`)

For teachers who want to understand the workflow before committing to a trial. Shows the full grading cycle end-to-end.

### Steps (visual timeline or numbered sections)

1. **Build your rubric** — Create criteria, set weights, add anchor descriptions. Or start from a template.
2. **Create an assignment** — Attach your rubric, set a due date, open for submissions.
3. **Upload essays** — Drag and drop PDF, DOCX, or plain text files. The system auto-assigns to your student roster.
4. **Trigger AI grading** — One click. AI grades each essay against your rubric with per-criterion scores and written justifications.
5. **Review and override** — Open any essay. Read the AI's reasoning. Agree, edit, or override any score or feedback.
6. **Lock and share** — Lock approved grades. Export PDFs to share with students. Pass grades back to your LMS.
7. **See the patterns** — Skill profiles update automatically. See who needs help and what to teach next.

**CTA at bottom:** "Start free trial"

---

## About Page (`/about`)

Brief company/project background. Establishes credibility and trust.

### Sections

- **Mission statement** — Why this product exists (the problem in the product vision)
- **Who built it** — Founder/team overview (placeholder until final copy)
- **Principles** — Human-in-the-loop, teacher-first, transparent AI, FERPA-serious
- **Contact** — Email for questions, partnership, press inquiries

---

## Acceptance Criteria

### Landing Page
- [ ] Renders correctly on mobile (375px), tablet (768px), and desktop (1280px)
- [ ] Primary CTA links to `/signup` with `?source=landing_hero` query param for attribution tracking
- [ ] All placeholder sections are clearly marked as `{TODO: insert copy}` so they are not shipped with Lorem Ipsum
- [ ] Page passes Lighthouse accessibility score ≥ 90
- [ ] No student PII, no app-specific data fetched on public pages — static or server-rendered only
- [ ] `<meta>` title and description are set correctly for SEO

### All Public Pages
- [ ] Auth state is checked but never required — unauthenticated users see the page without redirect
- [ ] If user is authenticated, nav shows "Go to dashboard" instead of "Sign in / Start trial"
- [ ] `next/image` used for all images with explicit `width`/`height` to avoid layout shift
- [ ] Footer legal links point to correct `/legal/*` routes
- [ ] No hard-coded product name strings — use a `PRODUCT_NAME` constant from a single config file so the name can be updated in one place

---

## Non-Goals

- No blog CMS at launch — blog route is a placeholder
- No customer case study pages at launch
- No chatbot or live chat widget (adds third-party JavaScript that could capture teacher/student data)
- No analytics SDK that sends data to third-party servers without a privacy review (see `security.md#5`)
