# Feature: Pricing Page

**Phase:** 0 — Scaffold / Pre-launch
**Status:** Planned

---

## Purpose

Convert visitors who are ready to buy — or who need to make a case to their school — into trial sign-ups or inbound purchase inquiries. The pricing page must be clear, honest, and handle the three distinct purchase patterns: individual teacher (self-serve), small school (one buyer, multiple teachers), and district (procurement process).

---

## Route

`/pricing`

---

## Pricing Model

**Per-teacher subscription, billed monthly or annually.**

Exact price points are TBD — use `[PRICE]` placeholders. The tiers below define what is offered at each level; pricing is set by the business.

### Tier Structure

| Tier | Target buyer | Key limits | Key inclusions |
|---|---|---|---|
| **Free Trial** | Individual teacher exploring | 30 days, up to 30 essays total | Full feature access |
| **Teacher** | Individual teacher, self-serve | Unlimited essays, 1 teacher | All core features, email support |
| **School** | Department or small school (up to N teachers) | TBD seat count | All Teacher features + school admin view, priority support |
| **District** | District procurement | Unlimited seats | Everything + LMS integrations, SSO, DPA, dedicated onboarding |

### Billing
- Monthly and annual options; annual at a discount (discount rate TBD)
- Payment via Stripe (card only at launch)
- School/District tier: invoice and PO payment accepted
- Free trial does not require a credit card

---

## Page Sections

### Hero
- Headline: simple and honest ("Simple pricing for teachers. No surprises.")
- Sub-line: reinforce trial offer and no-credit-card requirement

### Pricing Cards (3 columns at desktop, stacked on mobile)

One card per paid tier (Trial can be a banner or footnote, not a full card):

**Each card contains:**
- Tier name
- Price per teacher/month (monthly rate shown; annual shown as "Save X%")
- One-sentence description of who this is for
- Feature list (checkmarks)
- Primary CTA button:
  - Teacher: "Start free trial" → `/signup`
  - School: "Start free trial" or "Contact sales" → `/signup` or mailto/form
  - District: "Contact us" → contact form or `mailto:`
- "Most popular" badge on Teacher tier (or School if that becomes primary)

### Feature comparison table (optional, below the cards)
Full side-by-side feature matrix for buyers doing careful evaluation. Rows = features, columns = tiers. Toggle to show/hide on mobile.

### FAQ

Questions to address:

- **Do I need a credit card to start the trial?** No.
- **What happens when my trial ends?** Essays and grades are preserved; grading and upload are paused until you subscribe.
- **Can I switch plans later?** Yes, upgrade or downgrade anytime.
- **Does my school need to pay, or can I pay personally?** Either. Teacher tier is self-serve. School tier can be invoiced.
- **Is student data safe?** Yes. FERPA-compliant. Student data is never used for AI training. Link to `/legal/ferpa`.
- **Does the AI replace my grading judgment?** No — every grade requires your review and approval. Link to `/ai`.
- **What integrations are available?** Google Classroom (Phase 2), Canvas (Phase 2). Currently manual upload.
- **What if I need a Data Processing Agreement?** Available on School and District tiers. Link to `/legal/dpa`.

### School / District inquiry section
For buyers who need a purchase order, IT review, or a demo:
- Short form: name, school/district name, number of teachers, email
- Or simple "Email us" link
- Emphasize: "We'll set up your DPA and onboarding in 48 hours"

### Trust signals (below FAQ or sidebar)
- "FERPA compliant"
- "No student data used for AI training"
- "Human-in-the-loop — teacher reviews every grade"
- "Cancel anytime"
- "Runs in your browser — no software to install"

---

## Acceptance Criteria

- [ ] Tier cards render correctly at 375px (stacked), 768px (2-up), and 1280px (3-up side by side)
- [ ] All `[PRICE]` placeholders are surfaced as obvious TODOs — page cannot be deployed to production with literal `[PRICE]` text
- [ ] Annual/monthly toggle works and updates displayed price without a page reload
- [ ] "Start free trial" CTA links to `/signup?plan={tier}` so the signup flow can pre-select the tier
- [ ] FAQ items are implemented as an accessible accordion (`<details>` or equivalent with ARIA)
- [ ] School/District inquiry form (if a form, not mailto) POSTs to a backend endpoint that stores the inquiry and sends a notification email — no third-party form service that could capture school data
- [ ] Stripe payment is never initiated on this page — this page only drives to `/signup`; payment collection happens during onboarding
- [ ] No student PII, no auth-required data on this page

---

## Non-Goals

- No Stripe integration on this page — payment flows are in onboarding
- No per-seat calculator at launch
- No "enterprise custom pricing" tier at launch
