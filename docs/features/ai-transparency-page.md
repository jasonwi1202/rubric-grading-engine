# Feature: AI Transparency Page

**Phase:** 0 — Scaffold / Pre-launch
**Status:** Planned

---

## Purpose

Address the primary trust objection that teachers and administrators have before adopting AI-assisted grading: *"Can I trust what the AI produces? Is it going to replace my judgment? What happens to my students' essays?"*

This page is both a marketing asset and a compliance asset. It is referenced from the pricing page, the product page, FERPA notice, and the AI Use Policy. Teachers in evaluation mode will read it carefully.

---

## Route

`/ai`

Linked from:
- Site nav (secondary item)
- Footer
- `/product` page trust callout section
- `/pricing` FAQ ("Does the AI replace my grading judgment?")
- `/legal/ferpa` and `/legal/ai-use`

---

## Page Sections

### Hero

**Headline:** "AI that assists. Teachers who decide."

Sub-headline: One sentence explaining the human-in-the-loop principle plainly — e.g., "Every grade the AI suggests is reviewed, overrideable, and only final when you lock it."

---

### How the AI Grades

Plain-language explanation of the grading pipeline — no jargon:

1. **You define the rubric.** The AI grades to your criteria, not generic standards.
2. **We send the essay to the AI with your rubric.** The AI reads the essay and scores each criterion with a written justification.
3. **You see the AI's reasoning.** Every score comes with an explanation of why. Not just a number.
4. **You agree, edit, or override.** Change any score. Rewrite any feedback. The AI's version is a starting point, not the answer.
5. **You lock the grade.** Nothing is final until you decide it is.

Visual: A simplified version of the two-panel review UI showing the essay, the AI score, the justification, and the override control.

---

### What the AI Can Do

- Score essays against a rubric criterion-by-criterion with written reasoning
- Generate written feedback grounded in the specific essay text
- Flag low-confidence scores for closer teacher attention
- Identify patterns across a class (which students struggle with which skills)
- Suggest groupings and instructional priorities based on skill profile data

---

### What the AI Cannot Do (and does not try to)

- Make a grade final without teacher review — the system prevents this
- Assess tone, intent, or context that requires knowing the student
- Evaluate content accuracy in subjects outside writing (e.g., whether a cited fact is true)
- Replace the teacher's professional judgment about a student's situation
- Communicate with students — only the teacher can share feedback

---

### The Human-in-the-Loop Guarantee

A dedicated callout box or section, visually distinct:

> **Every grade requires your review.**
>
> AI-generated scores are proposals. They cannot be shared with students, entered into your LMS, or exported until you open each essay, review the reasoning, and lock the grade yourself.
>
> We built it this way on purpose. The AI handles the grading volume. You make the decisions.

---

### What Happens to Student Essays

This section directly addresses the FERPA concern:

- Essays are sent to the AI API for grading. They are not stored by the AI provider for training.
- Essays are stored securely in our system tied to your account, accessible only to you.
- We never use student essay content to train AI models.
- You can delete a student's data at any time. We will delete it within 30 days of your request.
- We act as a "school official" under FERPA — the same category as your gradebook vendor.

Link to `/legal/ferpa` for the full compliance details.

---

### About the AI Model

Plain disclosure:

- We use the **OpenAI API** for grading and feedback generation.
- The model version is configurable and documented in every grade record.
- We use the standard API — not a fine-tuned model trained on student data.
- When we change the model used for grading, we document it and retain the prior model version in historical grade records.

We do not make specific claims about model accuracy that we cannot verify. Rubric-based AI grading is assistive; it is not infallible.

---

### Confidence Scores

When the AI is less certain about a score, it says so. Low-confidence scores appear at the top of the review queue so you can look at them first. The AI tells you *why* it was uncertain — e.g., "The essay addresses the criterion but in an unconventional way."

High-confidence scores can be reviewed quickly. Low-confidence scores deserve closer attention. The teacher always decides.

---

### Questions and Concerns

Brief FAQ:

- **"What if the AI is wrong?"** Override it. The AI's score is a proposal. Your override is permanent.
- **"Is this fair to my students?"** You're the judge. The AI gives you a structured starting point with reasoning. You decide whether it's right.
- **"Does the AI have biases?"** Rubric-based grading inherits the biases in your rubric. The AI grades consistently to your criteria. Review score distributions across your class to catch unexpected patterns.
- **"What if I don't agree with how the AI works?"** Contact us. We want teachers to trust the tool, and we'd rather hear your concern than lose your trust silently.

CTA: "See how it works in practice" → `/how-it-works` or sign-up

---

## Acceptance Criteria

- [ ] Page is accessible without login
- [ ] "Lock the grade" flow is clearly explained — no ambiguity about when a grade becomes final
- [ ] The OpenAI relationship is disclosed accurately — do not claim "we don't use OpenAI" or "your data never leaves our servers"; be accurate
- [ ] All claims about data use are consistent with the Privacy Policy and FERPA Notice — no contradictions
- [ ] Page is reviewed and approved before launch — a product or legal stakeholder signs off that claims are accurate
- [ ] Page is linked from the site nav and footer
- [ ] "Human-in-the-loop" callout is visually prominent — not buried

---

## Non-Goals

- Not a technical explainer of how LLMs work (teachers don't need that)
- Not a research paper on AI grading accuracy
- Not a page that makes guarantees the product can't keep
