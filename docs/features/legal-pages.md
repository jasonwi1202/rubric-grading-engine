# Feature: Legal Pages

**Phase:** 0 — Scaffold / Pre-launch
**Status:** Planned

---

## Purpose

Provide the legally required disclosures, agreements, and notices that schools and teachers need to see before using a product that handles student education records. These pages are **required before any real teacher data is collected** — they are not optional polish.

All legal pages are public, statically rendered, and linked from the site footer.

> **Note:** The actual legal text must be drafted or reviewed by a qualified US attorney before launch. These specs define the page structure, required content areas, and acceptance criteria — not the final legal language. Use `[ATTORNEY DRAFT REQUIRED]` as a placeholder for any section requiring legal review.

---

## Routes

| Route | Page |
|---|---|
| `/legal/terms` | Terms of Service |
| `/legal/privacy` | Privacy Policy |
| `/legal/ferpa` | FERPA and COPPA Notice |
| `/legal/dpa` | Data Processing Agreement |
| `/legal/ai-use` | AI Use Policy |

`/legal` (index) redirects to `/legal/terms` or renders a list of available legal documents.

---

## Terms of Service (`/legal/terms`)

### Required sections

1. **Acceptance** — By using the service, you agree to these terms. Schools agree on behalf of their teachers.
2. **Service description** — What the product does; what it does not do (not a student-facing product, not a replacement for teacher judgment).
3. **Accounts and access** — Teacher is responsible for account security. Sharing credentials is prohibited.
4. **Acceptable use** — Permitted uses (grading student writing for legitimate educational purposes). Prohibited uses (any use that would violate FERPA, any commercial resale, any automated scraping).
5. **Student data** — We act as a "school official" under FERPA. Student data is used solely to provide the grading service. We do not sell student data. We do not use student data to train AI models without explicit written consent. `[ATTORNEY DRAFT REQUIRED]`
6. **AI-generated content** — Grades and feedback are AI-assisted. Teacher reviews and is responsible for final grades. We do not guarantee accuracy. `[ATTORNEY DRAFT REQUIRED]`
7. **Subscription and payment** — Billing terms, auto-renewal, cancellation, refund policy. `[ATTORNEY DRAFT REQUIRED]`
8. **Data retention and deletion** — Default retention period, deletion on account cancellation, how to request deletion.
9. **Intellectual property** — We own the service; you own your rubrics and content. Student essays remain the property of the school/student.
10. **Disclaimers and limitation of liability** `[ATTORNEY DRAFT REQUIRED]`
11. **Governing law** — US law, specific state TBD. `[ATTORNEY DRAFT REQUIRED]`
12. **Changes to terms** — We will notify by email with 30 days notice for material changes.
13. **Contact** — Legal contact email.

---

## Privacy Policy (`/legal/privacy`)

Required by law (CalOPPA, COPPA, various state student privacy laws) and required for trust with schools.

### Required sections

1. **What we collect**
   - Account information: teacher name, email, school name
   - Usage data: feature usage, session data (no student PII in usage analytics)
   - Student data: essay text, grades, feedback — collected on behalf of the school
   - Technical data: IP addresses (for security/audit logs only, not for profiling)

2. **What we do NOT collect**
   - Student email addresses, phone numbers, photos, or demographics (unless explicitly required for a future feature with disclosure)
   - Precise location data
   - Any data for advertising purposes

3. **How we use data**
   - Provide the grading service
   - Improve the service (aggregated, anonymized usage data only — never individual student data)
   - Security and fraud prevention
   - Communicate with account holders (not students)

4. **Student data — special protections**
   - Student data is processed solely to provide the educational service
   - Student data is never sold, rented, or disclosed to third parties except service providers under DPA
   - Student data is never used to train AI models without explicit written school consent
   - We do not build student profiles for advertising or non-educational purposes
   - Reference: FERPA, COPPA, applicable state laws (e.g., SOPIPA, NY Ed Law 2-d)

5. **Who we share data with** (subprocessors)
   - OpenAI (essay processing for grading) — bound by DPA
   - Railway (infrastructure hosting) — data stored in US
   - Payment processor (Stripe) — teacher billing data only; no student data
   - Log/monitoring provider — entity IDs only, no student PII; bound by DPA

6. **Data retention**
   - Active accounts: data retained for duration of subscription + 1 year
   - Deleted accounts: student data deleted within 30 days; teacher account data within 90 days
   - Audit logs: retained for 3 years for compliance purposes

7. **Your rights**
   - Access your data
   - Request deletion (teacher account or school data)
   - For student data rights: contact your school administrator (we act on school's instruction)

8. **Security**
   - Encryption in transit (TLS) and at rest
   - Access controls and authentication requirements
   - Regular security reviews
   - Breach notification within 72 hours (see incident response policy)

9. **Children's privacy (COPPA)**
   - The product is a teacher tool — we do not collect data directly from students
   - Students do not have accounts; their data is uploaded and managed by teachers on their behalf
   - If a teacher inadvertently creates a student account, contact us to delete it

10. **Changes to this policy** — Email notice 30 days before material changes.
11. **Contact** — Privacy contact email / DPO contact.
12. **Effective date and version number**

---

## FERPA and COPPA Notice (`/legal/ferpa`)

A plain-language, school-friendly page — distinct from the Privacy Policy. School IT directors and administrators will specifically look for this page.

### Sections

**What is FERPA?**
Brief plain-language explanation (2–3 sentences) of what FERPA is and why it matters.

**Our role under FERPA**
We act as a "school official" with a "legitimate educational interest" under 34 CFR §99.31(a)(1). We are not an "authorized representative" for audit/evaluation purposes. We do not have independent rights to student education records — we act solely on the school's instruction. `[ATTORNEY DRAFT REQUIRED]`

**What student data we access**
- Essay text submitted by teachers
- Grades and feedback created by or confirmed by teachers
- We do not receive student names unless a teacher includes them in an essay file

**What we do not do with student data**
- Do not sell or rent student data
- Do not use for advertising
- Do not use to train AI models
- Do not share with third parties except subprocessors listed in our Privacy Policy and DPA

**Data Processing Agreement**
Schools can request a signed DPA for FERPA compliance. The DPA:
- Names us as a school official acting on the school's behalf
- Defines permitted uses of student data
- Defines deletion obligations
- Defines breach notification procedures
Contact email to request a DPA. Link to `/legal/dpa`.

**COPPA**
We do not collect personal information directly from students under 13. The product is a teacher tool; students do not have accounts or direct access.

**State privacy laws**
In addition to FERPA, we comply with applicable state student data privacy laws including:
- California: SOPIPA, AB 1584
- New York: Education Law §2-d
- Other states: reviewed on a case-by-case basis; contact us with specific questions

**Contact for compliance questions**
Dedicated email address for FERPA/privacy questions from school administrators.

---

## Data Processing Agreement (`/legal/dpa`)

Not the DPA document itself (that is sent as a PDF to requesting schools) — this is a page explaining what it is and how to get it.

### Sections

- **What is a DPA?** Brief explanation.
- **When do you need one?** Required if your district or state requires a formal agreement before adopting third-party edtech tools (most districts do).
- **What our DPA covers:** Scope of data processing, permitted uses, deletion obligations, breach notification, subprocessor list, audit rights.
- **How to get one:** Submit a request form (name, school/district, email) — we respond within 2 business days with a draft DPA for review.
- **Pre-signed DPA:** If your district uses a standard DPA template (e.g., the Student Data Privacy Consortium model), we will review and sign it.
- CTA: "Request a DPA" → short form or email link

---

## AI Use Policy (`/legal/ai-use`)

A policy-level document (distinct from the marketing `/ai` transparency page) covering the rules governing AI use in the product. School IT and legal teams will look for this.

### Sections

1. **What AI is used for** — Essay grading, feedback generation, instruction recommendations.
2. **What AI is not used for** — No AI makes final grading decisions. No AI takes action without teacher review and approval. AI does not communicate with students.
3. **Model providers** — OpenAI API. Model version is configurable. We do not use fine-tuned models trained on student data.
4. **Student data and AI training** — Student essay content is sent to OpenAI for grading via their API. OpenAI's API terms prohibit using API inputs for model training by default. We do not opt in to any training data sharing. Cite OpenAI's current data usage policy. `[VERIFY CURRENT OPENAI API TERMS]`
5. **Human oversight requirement** — Every AI-generated grade must be reviewed by the teacher before it is considered final. The system enforces this: grades cannot be shared with students until the teacher locks them.
6. **Accuracy and errors** — AI grading is assistive, not authoritative. The teacher is responsible for all final grades. If the AI produces an error, the teacher's override is the correction mechanism.
7. **Bias and fairness** — AI rubric-based grading is subject to the same biases as the rubric itself. Teachers are responsible for the rubric they define. We do not provide bias detection — teachers should review distributions for unusual patterns.
8. **Updates to AI use** — Material changes to AI providers or use cases will be disclosed with 30 days notice.

---

## Acceptance Criteria

### All legal pages
- [ ] Each page has a visible "Last updated" date and a version number
- [ ] All `[ATTORNEY DRAFT REQUIRED]` and `[VERIFY ...]` placeholders are resolved before production deployment
- [ ] Pages are statically rendered (`generateStaticParams` or equivalent) — no auth required, no API calls
- [ ] Footer links to all legal pages are present on every public page
- [ ] Legal pages are excluded from `robots.txt` disallow (they should be indexable)
- [ ] Each page has a print-friendly CSS class or `@media print` styles (schools will print these for IT review)
- [ ] No cookie consent banner is needed if the only cookies are the httpOnly auth cookie and no tracking pixels — verify this before adding a banner

### Privacy Policy specifically
- [ ] Links to the current OpenAI data processing terms are live links (not dead links)
- [ ] Subprocessor table is kept up to date as new vendors are added

### DPA page specifically
- [ ] Request form stores submissions in the database (not a third-party form service) and sends a notification to the legal/compliance email address
- [ ] Form does not collect student data — school admin contact only

---

## Non-Goals

- The actual legal text is not written in this spec — an attorney drafts that
- No cookie consent wall at launch (evaluate when/if third-party analytics are added)
- No GDPR-specific pages at launch (US-only for Phase 1)
- No automated DPA generation — human reviews all DPA requests
