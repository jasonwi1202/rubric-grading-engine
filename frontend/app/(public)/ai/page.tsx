import type { Metadata } from "next";
import Link from "next/link";
import {
  BookOpen,
  SplitSquareVertical,
  FileText,
  MessageSquare,
  CheckCircle,
  AlertTriangle,
} from "lucide-react";
import { PRODUCT_NAME } from "@/lib/constants";

export const metadata: Metadata = {
  title: `AI Transparency — ${PRODUCT_NAME}`,
  description: `How ${PRODUCT_NAME} uses AI, what data it touches, and what the teacher always controls.`,
};

const GRADING_STEPS = [
  {
    step: 1,
    icon: BookOpen,
    title: "Reads your rubric criteria",
    body: "The AI receives your rubric — your criteria, your point values, and your anchor descriptions. It grades to your standard, not a generic one.",
  },
  {
    step: 2,
    icon: SplitSquareVertical,
    title: "Scores each criterion independently",
    body: "Every criterion is evaluated on its own. The AI does not produce a single holistic score — it works through each dimension of your rubric one at a time.",
  },
  {
    step: 3,
    icon: FileText,
    title: "Writes a justification per criterion",
    body: "For each score, the AI writes a plain-language explanation grounded in specific evidence from the essay. Not just a number — a reason.",
  },
  {
    step: 4,
    icon: MessageSquare,
    title: "Generates overall feedback",
    body: "After scoring all criteria, the AI drafts a brief holistic feedback message summarizing the essay's strengths and the clearest area for improvement.",
  },
  {
    step: 5,
    icon: CheckCircle,
    title: "Teacher reviews and approves",
    body: "You see every score and every justification. Agree with them, edit them, or override them entirely. Nothing is final until you lock the grade.",
  },
] as const;

const AI_CAN_DO = [
  "Score essays against a rubric criterion-by-criterion with written reasoning",
  "Generate written feedback grounded in specific essay text",
  "Flag low-confidence scores for closer teacher attention",
  "Identify patterns across a class — which students struggle with which skills",
  "Suggest groupings and instructional priorities based on skill profile data",
] as const;

const AI_CANNOT_DO = [
  "Make a grade final without teacher review — the system prevents this",
  "Assess tone, intent, or context that requires knowing the student",
  "Evaluate content accuracy outside writing craft (e.g., whether a cited fact is true)",
  "Replace the teacher's professional judgment about a student's situation",
  "Communicate with students — only the teacher can share feedback",
] as const;

const FAQ_ITEMS = [
  {
    q: "What if the AI is wrong?",
    a: "Override it. The AI's score is a proposal. Your override is permanent. The system records both the AI score and your final score in the grade history.",
  },
  {
    q: "Is this fair to my students?",
    a: "You're the judge. The AI gives you a structured starting point with reasoning. You decide whether it's right for each student.",
  },
  {
    q: "Does the AI have biases?",
    a: "Rubric-based grading inherits the biases in your rubric. The AI grades consistently to your criteria. Review score distributions across your class to catch unexpected patterns.",
  },
  {
    q: "What if I don't agree with how the AI works?",
    a: "Contact us. We want teachers to trust the tool, and we'd rather hear your concern than lose your trust silently.",
  },
] as const;

/**
 * AI transparency page — explains the AI's role, the 5-step grading pipeline,
 * its limitations, the human-in-the-loop guarantee, data use, and confidence
 * scores.
 *
 * Fully static — no API calls.
 */
export default function AiPage() {
  return (
    <>
      {/* ── Hero ────────────────────────────────────────────────────────── */}
      <section className="bg-white px-4 py-24 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <h1 className="text-4xl font-extrabold tracking-tight text-gray-900 sm:text-5xl">
            AI that assists. Teachers who decide.
          </h1>
          <p className="mt-6 text-xl text-gray-500">
            Every grade the AI suggests is reviewed, overrideable, and only
            final when you lock it.
          </p>
        </div>
      </section>

      {/* ── How the AI grades ────────────────────────────────────────────── */}
      <section
        aria-labelledby="how-ai-grades-heading"
        className="bg-gray-50 px-4 py-16 sm:px-6 lg:px-8"
      >
        <div className="mx-auto max-w-3xl">
          <h2
            id="how-ai-grades-heading"
            className="text-3xl font-bold text-gray-900"
          >
            How the AI grades
          </h2>
          <p className="mt-4 text-gray-500">
            Plain-language explanation of the grading pipeline — no jargon.
          </p>

          <ol className="mt-10 space-y-0" role="list">
            {GRADING_STEPS.map(({ step, icon: Icon, title, body }, index) => (
              <li key={step} className="relative flex gap-6">
                {/* Vertical connector */}
                {index < GRADING_STEPS.length - 1 && (
                  <div
                    aria-hidden="true"
                    className="absolute left-5 top-10 h-full w-0.5 bg-blue-200"
                  />
                )}

                {/* Step bubble */}
                <div
                  aria-hidden="true"
                  className="relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white shadow-sm"
                >
                  {step}
                </div>

                {/* Content */}
                <div className="pb-10">
                  <div className="flex items-center gap-2">
                    <Icon
                      className="h-5 w-5 text-blue-600"
                      aria-hidden="true"
                    />
                    <h3 className="text-lg font-semibold text-gray-900">
                      {title}
                    </h3>
                  </div>
                  <p className="mt-1 text-gray-500">{body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* ── What the AI can / cannot do ──────────────────────────────────── */}
      <section
        aria-labelledby="capabilities-heading"
        className="bg-white px-4 py-16 sm:px-6 lg:px-8"
      >
        <div className="mx-auto max-w-5xl">
          <h2
            id="capabilities-heading"
            className="text-3xl font-bold text-gray-900"
          >
            What the AI can and cannot do
          </h2>

          <div className="mt-10 grid grid-cols-1 gap-8 lg:grid-cols-2">
            {/* Can do */}
            <div className="rounded-lg border border-green-100 bg-green-50 p-8">
              <h3 className="text-xl font-semibold text-gray-900">
                What the AI can do
              </h3>
              <ul className="mt-4 space-y-3" role="list">
                {AI_CAN_DO.map((item) => (
                  <li key={item} className="flex items-start gap-3 text-gray-700">
                    <span
                      className="mt-1 h-2 w-2 shrink-0 rounded-full bg-green-500"
                      aria-hidden="true"
                    />
                    {item}
                  </li>
                ))}
              </ul>
            </div>

            {/* Cannot do */}
            <div className="rounded-lg border border-red-100 bg-red-50 p-8">
              <h3 className="text-xl font-semibold text-gray-900">
                What the AI cannot do (and does not try to)
              </h3>
              <ul className="mt-4 space-y-3" role="list">
                {AI_CANNOT_DO.map((item) => (
                  <li key={item} className="flex items-start gap-3 text-gray-700">
                    <span
                      className="mt-1 h-2 w-2 shrink-0 rounded-full bg-red-400"
                      aria-hidden="true"
                    />
                    {item}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* ── HITL guarantee callout ───────────────────────────────────────── */}
      <section
        aria-labelledby="hitl-heading"
        className="bg-blue-600 px-4 py-16 sm:px-6 lg:px-8"
      >
        <div className="mx-auto max-w-3xl">
          <div className="rounded-xl border-2 border-white/30 bg-white/10 p-8 text-white shadow-lg backdrop-blur-sm">
            <h2
              id="hitl-heading"
              className="text-2xl font-bold"
            >
              The human-in-the-loop guarantee
            </h2>
            <blockquote className="mt-4 space-y-3 text-lg text-blue-50">
              <p>
                <strong className="text-white">
                  Every grade requires your review.
                </strong>
              </p>
              <p>
                AI-generated scores are proposals. They cannot be shared with
                students, entered into your LMS, or exported until you open each
                essay, review the reasoning, and lock the grade yourself.
              </p>
              <p>
                We built it this way on purpose. The AI handles the grading
                volume. You make the decisions.
              </p>
            </blockquote>
          </div>
        </div>
      </section>

      {/* ── What happens to student essays ──────────────────────────────── */}
      <section
        aria-labelledby="data-use-heading"
        className="bg-white px-4 py-16 sm:px-6 lg:px-8"
      >
        <div className="mx-auto max-w-3xl">
          <h2
            id="data-use-heading"
            className="text-3xl font-bold text-gray-900"
          >
            What happens to student essays
          </h2>
          <p className="mt-4 text-gray-500">
            We know this is the question that matters most to teachers and
            administrators. Here is a plain-language answer.
          </p>

          <ul className="mt-8 space-y-4" role="list">
            {[
              "Essays are sent to the OpenAI API for grading and are not used to train models.",
              "Essays are stored securely in our system tied to your account, accessible only to you.",
              "We never use student essay content to train AI models — ours or anyone else's.",
              "You can delete a student's data at any time. We will delete it within 30 days of your request.",
              "We act as a \"school official\" under FERPA — the same category as your gradebook vendor.",
            ].map((item) => (
              <li key={item} className="flex items-start gap-3 text-gray-700">
                <span
                  className="mt-1 h-2 w-2 shrink-0 rounded-full bg-blue-500"
                  aria-hidden="true"
                />
                {item}
              </li>
            ))}
          </ul>

          <p className="mt-8 text-sm text-gray-500">
            See our current{" "}
            <Link
              href="/legal/ferpa"
              className="text-blue-600 underline hover:text-blue-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              FERPA Notice
            </Link>{" "}
            and{" "}
            <Link
              href="/legal/privacy"
              className="text-blue-600 underline hover:text-blue-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              Privacy Policy
            </Link>
            {" "}for compliance details.
          </p>
        </div>
      </section>

      {/* ── About the AI model ───────────────────────────────────────────── */}
      <section
        aria-labelledby="model-heading"
        className="bg-gray-50 px-4 py-16 sm:px-6 lg:px-8"
      >
        <div className="mx-auto max-w-3xl">
          <h2
            id="model-heading"
            className="text-3xl font-bold text-gray-900"
          >
            About the AI model
          </h2>

          <ul className="mt-6 space-y-4" role="list">
            {[
              "We use the OpenAI API for grading and feedback generation.",
              "The model version is configurable and documented in every grade record — you can always see which model produced a given grade.",
              "We use the standard API — not a fine-tuned model trained on student data.",
              "When we change the model used for grading, we document it and retain the prior model version in historical grade records.",
            ].map((item) => (
              <li key={item} className="flex items-start gap-3 text-gray-700">
                <span
                  className="mt-1 h-2 w-2 shrink-0 rounded-full bg-blue-500"
                  aria-hidden="true"
                />
                {item}
              </li>
            ))}
          </ul>

          <p className="mt-6 text-sm text-gray-500">
            We do not make specific claims about model accuracy that we cannot
            verify. Rubric-based AI grading is assistive; it is not infallible.
          </p>
        </div>
      </section>

      {/* ── Confidence scores ────────────────────────────────────────────── */}
      <section
        aria-labelledby="confidence-heading"
        className="bg-white px-4 py-16 sm:px-6 lg:px-8"
      >
        <div className="mx-auto max-w-3xl">
          <div className="flex items-start gap-4">
            <div
              aria-hidden="true"
              className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-amber-100"
            >
              <AlertTriangle className="h-6 w-6 text-amber-600" />
            </div>
            <div>
              <h2
                id="confidence-heading"
                className="text-3xl font-bold text-gray-900"
              >
                Confidence scores
              </h2>
              <p className="mt-4 text-gray-600">
                When the AI is less certain about a score, it says so.
                Low-confidence scores appear at the top of the review queue so
                you can look at them first. The AI tells you{" "}
                <em>why</em> it was uncertain — for example,{" "}
                <q>
                  The essay addresses the criterion but in an unconventional
                  way.
                </q>
              </p>
              <p className="mt-4 text-gray-600">
                High-confidence scores can be reviewed quickly.
                Low-confidence scores deserve closer attention. The teacher
                always decides.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── FAQ ──────────────────────────────────────────────────────────── */}
      <section
        aria-labelledby="faq-heading"
        className="bg-gray-50 px-4 py-16 sm:px-6 lg:px-8"
      >
        <div className="mx-auto max-w-3xl">
          <h2
            id="faq-heading"
            className="text-3xl font-bold text-gray-900"
          >
            Questions and concerns
          </h2>

          <dl className="mt-8 space-y-6">
            {FAQ_ITEMS.map(({ q, a }) => (
              <div key={q}>
                <dt className="text-base font-semibold text-gray-900">
                  &ldquo;{q}&rdquo;
                </dt>
                <dd className="mt-2 text-gray-600">{a}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* ── Bottom CTA ───────────────────────────────────────────────────── */}
      <section className="bg-white px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-bold text-gray-900">
            See how it works in practice
          </h2>
          <p className="mt-4 text-lg text-gray-500">
            Start a free trial and run your first grading session today.
          </p>
          <div className="mt-8 flex flex-col items-center gap-4 sm:flex-row sm:justify-center">
            <Link
              href="/signup?source=ai_transparency_cta"
              className="rounded-md bg-blue-600 px-8 py-3 text-base font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
            >
              Start free trial
            </Link>
            <Link
              href="/how-it-works"
              className="rounded-md border border-gray-300 bg-white px-8 py-3 text-base font-semibold text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
            >
              See the full workflow
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
