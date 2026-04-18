# M2 Release Notes — Business Summary

**Version:** v0.3.0  
**Milestone:** M2 — Public Website & Onboarding  
**Status:** Pending merge to main

---

## What Was Delivered

Milestone 2 delivers the product's public face and the teacher account creation flow. Before this milestone, there was no way for a new teacher to discover the product, create an account, or get started. M2 closes that gap.

### Public Marketing Site

Every public-facing page is now live:

- **Homepage (`/`)** — hero section, feature highlights, how-it-works overview, and trial CTA. Fully static for maximum performance.
- **Product page (`/product`)** — detailed feature walkthrough with screenshot placeholders and a trust/compliance callout (FERPA, no data-selling, human-in-the-loop guarantee).
- **How It Works (`/how-it-works`)** — numbered workflow from essay upload through teacher review and export.
- **About (`/about`)** — mission statement, core principles, and contact.
- **Pricing (`/pricing`)** — four tier cards (Trial, Teacher, School, District) with annual/monthly toggle, feature comparison table, FAQ accordion, and a school/district inquiry form that goes directly to the team inbox.
- **AI Transparency (`/ai`)** — explicit, plain-language explanation of how the AI grades, what it cannot do, the human-in-the-loop guarantee, data use disclosure, and confidence score explainer. This page is a competitive differentiator and a trust signal for FERPA-conscious buyers.

### Legal Compliance Pages

All five required legal pages exist under `/legal/*`:

- Terms of Service
- Privacy Policy
- FERPA/COPPA Notice
- Data Processing Agreement (DPA) info page — includes a request form that goes directly to the team
- AI Use Policy

All pages carry an `[ATTORNEY DRAFT REQUIRED]` banner until reviewed and approved by counsel. The banner is visible in all non-production environments.

### Teacher Account Creation

Teachers can now create accounts end-to-end:

1. Fill out the sign-up form at `/signup` (name, email, password, school name)
2. Receive a verification email with a secure link
3. Click the link to verify their address
4. Land on the login page ready to use the product

Rate limiting prevents abuse (5 sign-up attempts per IP per hour).

### Onboarding Wizard

After first login, teachers are guided through a 2-step wizard:

1. **Create your first class** — name and grade level
2. **Build your first rubric** — simplified builder, template picker, or skip

Both steps can be skipped. The wizard ends at `/onboarding/done` with a clear "Go to Dashboard" CTA. A trial status banner in the dashboard header shows remaining trial days throughout the trial period.

### Trial Lifecycle Emails

Automated emails keep teachers engaged during their trial:

- Welcome email on account creation
- 7-day and 1-day expiry warnings
- Day-0 expiry notice with upgrade call-to-action

All emails are plain HTML sent via SMTP. No student data is included in any email.

---

## What Is Not Included

- **Payment processing** — pricing page is informational only; no checkout flow in M2
- **Legal page text** — all pages carry `[ATTORNEY DRAFT REQUIRED]` placeholders; attorney review required before production launch
- **Upgrade/subscription flow** — tiered access enforcement is deferred to a later milestone
- **Student-facing features** — M2 is entirely teacher/admin facing, consistent with the teacher-only interface principle

---

## Demo Notes

The full public site is accessible at `http://localhost:3000` when running `docker compose up`. Key flows to demonstrate:

| Flow | Steps |
|---|---|
| Discovery | Browse `/`, `/product`, `/how-it-works`, `/pricing`, `/ai` |
| Trust & compliance | View `/legal/ferpa`, `/ai` — HITL guarantee callout |
| Inquiry | Submit school inquiry form on `/pricing` — verify confirmation message |
| Sign-up | `/signup` → verification email (check Mailpit at `http://localhost:8025`) → `/auth/verify` |
| Onboarding | Post-login wizard → create class → build rubric → `/onboarding/done` |
| Trial banner | Dashboard header shows "X days remaining" |
