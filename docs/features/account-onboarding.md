# Feature: Account Sign-Up and Onboarding

**Phase:** 0 — Scaffold / Pre-launch
**Status:** Planned

---

## Purpose

Get a teacher from "I want to try this" to "I've graded my first essay" as fast as possible. Onboarding is the bridge between the marketing site and the application. A good onboarding flow converts trial sign-ups into active users; a bad one loses teachers before they see the product's value.

---

## Routes

| Route | Page |
|---|---|
| `/signup` | Sign-up form (start trial) |
| `/signup/verify` | Email verification holding page |
| `/onboarding` | Onboarding wizard (post-verification, pre-dashboard) |
| `/onboarding/class` | Step 1: Create your first class |
| `/onboarding/rubric` | Step 2: Build or import a rubric |
| `/onboarding/done` | Completion — link to dashboard |

After completing onboarding, user lands at `/dashboard`.

`/login` is the returning user flow — not documented here.

---

## Sign-Up Page (`/signup`)

### Form fields

| Field | Type | Notes |
|---|---|---|
| First name | Text | Required |
| Last name | Text | Required |
| Work email | Email | Required — must not be a personal domain (gmail, yahoo, hotmail, etc.) if school account verification is desired; configurable |
| School or organization name | Text | Required |
| Grade levels taught | Multi-select | e.g., 6th, 7th, 8th, 9th, 10th, 11th, 12th — optional, used for onboarding personalization |
| Password | Password | Min 12 chars |
| Agree to Terms of Service and Privacy Policy | Checkbox | Required — must include links to both |

### Behavior

- On submit: create unverified teacher account, send verification email, redirect to `/signup/verify`
- If email already registered: show "An account with this email already exists. [Sign in]"
- No credit card required at sign-up — trial starts immediately after email verification
- Query param `?plan={tier}` pre-selects the plan (passed from pricing page CTA)
- Query param `?source={value}` captured for attribution — stored on the account record, never displayed to users and never used for anything except internal product analytics

### Email verification

- Verification link is time-limited (24 hours), single-use
- On click: mark account as verified, create session, redirect to `/onboarding`
- If link expired: offer to resend
- Resend limited to 3 times per hour per email address

---

## Onboarding Wizard (`/onboarding`)

A focused 2-step wizard before the teacher reaches the full dashboard. The goal is to get them to their first class and first rubric — the minimum required to grade anything.

**Design principles:**
- Skip is always available (both steps) — don't force completion
- Progress indicator (e.g., "Step 1 of 2")
- No sidebar navigation visible yet — the wizard is its own full-screen experience
- Each step completes a real database action (not just collecting data to submit later)

### Step 1: Create your first class (`/onboarding/class`)

**Fields:**
- Class name (e.g., "Period 3 English")
- Grade level (select)
- Academic year (e.g., "2025–26")

On submit: creates the class record and redirects to Step 2.
Skip link: "I'll set up my class later" → proceeds to Step 2 without creating a class.

### Step 2: Build or import a rubric (`/onboarding/rubric`)

Three options presented as cards:

1. **Build from scratch** — Opens the rubric builder inline (simplified version: name, 3 criteria with default 1–5 scale). Teacher can finish building later — saving a partial rubric is fine.
2. **Start from a template** — Show 3–4 rubric templates (e.g., "5-Paragraph Essay", "Argumentative Writing", "Literary Analysis"). Selecting one pre-fills the rubric builder.
3. **Skip for now** — "I'll create a rubric when I set up my first assignment"

On complete or skip: redirect to `/onboarding/done`.

### Completion page (`/onboarding/done`)

- "You're ready." heading
- Summary of what was created (class name, rubric name, or skip messages)
- Single CTA: "Go to my dashboard" → `/dashboard`
- Secondary: "Invite a co-teacher" (if school tier) — deferred to later
- Trial status reminder: "Your free trial is active. You have 30 days to explore."

---

## Trial State and Upgrade Prompts

### During trial
- Trial expiry date shown in the dashboard header (subtle — e.g., "Trial: 14 days left")
- No feature restrictions during trial — full access
- At 7 days remaining: email notification + in-app banner with upgrade CTA
- At 1 day remaining: email + more prominent banner

### Trial expiry
- Grading and upload are paused — teacher can view existing grades but cannot run new batches
- Data is fully preserved — nothing is deleted at trial end
- Upgrade prompt replaces the "Grade" button in the UI
- Teacher has 90 days after trial end to upgrade before data deletion warning is shown

### Upgrade flow
- "Upgrade" → `/billing/upgrade` (separate billing flow, not documented here)
- Stripe checkout via a dedicated billing page
- On success: plan updated, trial status cleared, confirmation email sent

---

## Email Notifications in Onboarding Flow

| Trigger | Email |
|---|---|
| Sign-up | Verification email with link |
| Verification complete | Welcome email with "your first steps" links |
| 7 days before trial end | Trial expiry reminder + upgrade CTA |
| 1 day before trial end | Final trial reminder |
| Trial ended | "Your trial has ended" + upgrade CTA |
| Subscription started | Confirmation with receipt link |

All emails must:
- Be plain HTML — no fancy design that renders poorly in school email clients
- Include an unsubscribe link for marketing emails (transactional emails are exempt)
- Never include student PII — only teacher name, plan details, and dates

---

## Acceptance Criteria

### Sign-up
- [ ] Form validates all required fields client-side (Zod) and server-side (Pydantic) before submission
- [ ] Password field has a show/hide toggle — no character count requirements displayed
- [ ] Terms of Service and Privacy Policy links open in a new tab
- [ ] `?plan` and `?source` query params are captured and stored on the account record
- [ ] Verification email is sent within 10 seconds of form submission
- [ ] Duplicate email registration returns a clear message without exposing account existence to an attacker (see security.md — auth endpoint behavior)
- [ ] Rate limiting on sign-up: 5 sign-up attempts per IP per hour

### Onboarding
- [ ] Both steps are skippable — no dead ends
- [ ] Partial rubric saves correctly (incomplete rubric is valid — it can be finished later)
- [ ] On returning to `/onboarding` after partial completion, the wizard resumes at the incomplete step
- [ ] Onboarding can be re-entered from the dashboard if a teacher skipped steps ("Complete your setup" prompt)
- [ ] No student data is collected or required during onboarding

### Trial and billing
- [ ] Trial end date is computed from verification time, not sign-up time
- [ ] All trial email notifications are sent via background task (Celery) — not synchronously in the request
- [ ] Upgrade flow redirects through Stripe and returns to the dashboard with plan status updated

---

## Non-Goals

- No social login (Google / Clever SSO) at launch — email/password only
- No team/school invitation flow at launch (that is a School tier feature, Phase 2)
- No in-product tutorial overlay or coach marks at launch — the wizard is the onboarding
- No mobile app — web only
