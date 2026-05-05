import type { Metadata } from "next";
import Link from "next/link";
import {
  Upload,
  ClipboardCheck,
  BarChart2,
  Lightbulb,
  Zap,
  TrendingUp,
  Target,
  ShieldCheck,
  XCircle,
  CheckCircle2,
} from "lucide-react";
import { PRODUCT_NAME } from "@/lib/constants";

export const metadata: Metadata = {
  title: `${PRODUCT_NAME} — AI-Assisted Grading for K-12 Writing`,
  description:
    "Save hours on essay grading. AI grades each essay against your rubric with per-criterion scores and written justifications. You review, override, and decide.",
};

/**
 * Landing page — the primary acquisition surface for the public marketing site.
 *
 * This is a stub. Full copy, images, and testimonials will be added in a
 * later milestone.
 *
 * {TODO: insert hero copy}
 * {TODO: insert testimonials}
 * {TODO: insert feature screenshots}
 */
export default function LandingPage() {
  return (
    <>
      {/* Hero */}
      <section className="bg-white px-4 py-24 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-blue-100 bg-blue-50 px-4 py-1.5 text-sm font-medium text-blue-700">
            <span className="h-1.5 w-1.5 rounded-full bg-blue-500" aria-hidden="true" />
            Built for K-12 writing teachers
          </div>
          <h1 className="text-4xl font-extrabold tracking-tight text-gray-900 sm:text-5xl">
            {/* {TODO: insert hero headline} */}
            Grade smarter. Teach better.
          </h1>
          <p className="mt-6 text-xl text-gray-600">
            {/* {TODO: insert hero sub-headline} */}
            {PRODUCT_NAME} grades student essays against your rubric in seconds
            — with per-criterion scores and written justifications you can
            review, override, and approve.
          </p>
          <div className="mt-10 flex flex-col items-center gap-4 sm:flex-row sm:justify-center">
            <Link
              href="/signup?source=landing_hero"
              className="rounded-md bg-blue-600 px-8 py-3 text-base font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
            >
              Start free trial
            </Link>
            <Link
              href="/how-it-works"
              className="rounded-md border border-gray-300 bg-white px-8 py-3 text-base font-semibold text-gray-700 shadow-sm hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
            >
              See how it works
            </Link>
          </div>
          <p className="mt-4 text-sm text-gray-600">
            {/* {TODO: insert social proof signal} */}
            No credit card required.
          </p>
        </div>
      </section>

      {/* Problem → Solution */}
      <section className="bg-white px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-7xl">
          <div className="grid grid-cols-1 gap-12 lg:grid-cols-2 lg:gap-16">
            {/* Problem column */}
            <div className="rounded-lg border border-red-100 bg-red-50 p-8">
              <h2 className="text-2xl font-bold text-gray-900">
                The grading loop is broken
              </h2>
              <ul className="mt-6 space-y-4 text-gray-700">
                <li className="flex items-start gap-3">
                  <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" aria-hidden="true" />
                  <span>
                    Teachers spend <strong>4–6 hours per class set</strong>{" "}
                    grading essays — time that cannot be spent on instruction.
                  </span>
                </li>
                <li className="flex items-start gap-3">
                  <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" aria-hidden="true" />
                  <span>
                    Feedback arrives days after submission, when students have
                    already moved on to the next assignment.
                  </span>
                </li>
                <li className="flex items-start gap-3">
                  <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-red-500" aria-hidden="true" />
                  <span>
                    Grading is disconnected from instruction — patterns across a
                    class remain invisible without hours of manual analysis.
                  </span>
                </li>
              </ul>
            </div>

            {/* Solution column */}
            <div className="rounded-lg border border-blue-100 bg-blue-50 p-8">
              <h2 className="text-2xl font-bold text-gray-900">
                {PRODUCT_NAME} breaks the loop
              </h2>
              <ul className="mt-6 space-y-4 text-gray-700">
                <li className="flex items-start gap-3">
                  <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-blue-600" aria-hidden="true" />
                  <span>
                    AI grades every essay against your rubric in seconds —
                    per-criterion scores with written justifications you can
                    read and verify.
                  </span>
                </li>
                <li className="flex items-start gap-3">
                  <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-blue-600" aria-hidden="true" />
                  <span>
                    Review, override, and approve grades on your schedule.
                    Feedback is ready when you are — not when manual grading
                    finally ends.
                  </span>
                </li>
                <li className="flex items-start gap-3">
                  <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-blue-600" aria-hidden="true" />
                  <span>
                    Skill profiles update automatically across every assignment
                    — you see exactly which students need help and what to teach
                    next.
                  </span>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* Feature highlights */}
      <section className="bg-gray-50 px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-7xl">
          <h2 className="text-center text-3xl font-bold text-gray-900">
            {/* {TODO: insert section headline} */}
            Everything you need to grade with confidence
          </h2>
          <div className="mt-12 grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-4">
            {[
              {
                icon: <Zap className="h-6 w-6 text-blue-600" aria-hidden="true" />,
                title: "AI grading with transparent reasoning",
                body: "Each criterion scored individually with a written justification you can read and verify.",
              },
              {
                icon: <TrendingUp className="h-6 w-6 text-blue-600" aria-hidden="true" />,
                title: "Student skill profiles",
                body: "Persistent skill tracking across assignments surfaces gaps before they widen.",
              },
              {
                icon: <Target className="h-6 w-6 text-blue-600" aria-hidden="true" />,
                title: "Teacher-guided instruction",
                body: "Instructional priorities surfaced from real student data — not gut feel.",
              },
              {
                icon: <ShieldCheck className="h-6 w-6 text-blue-600" aria-hidden="true" />,
                title: "Human-in-the-loop, always",
                body: "AI prepares; you decide. No grade is recorded until you approve it.",
              },
            ].map(({ icon, title, body }) => (
              <div key={title} className="rounded-lg bg-white p-6 shadow-sm ring-1 ring-gray-100">
                <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-blue-50">
                  {icon}
                </div>
                <h3 className="mt-4 font-semibold text-gray-900">{title}</h3>
                <p className="mt-2 text-sm text-gray-600">{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works (abbreviated) */}
      <section className="bg-white px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-5xl">
          <h2 className="text-center text-3xl font-bold text-gray-900">
            How it works
          </h2>
          <p className="mt-4 text-center text-lg text-gray-600">
            From upload to insight in four simple steps.
          </p>

          <ol
            className="mt-12 grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-4"
            role="list"
          >
            {[
              {
                icon: (
                  <Upload
                    className="h-8 w-8 text-blue-600"
                    aria-hidden="true"
                  />
                ),
                step: "1",
                title: "Upload essays",
                body: "Drag and drop PDF, DOCX, or plain-text files. The system auto-assigns them to your student roster.",
              },
              {
                icon: (
                  <ClipboardCheck
                    className="h-8 w-8 text-blue-600"
                    aria-hidden="true"
                  />
                ),
                step: "2",
                title: "AI grades against your rubric",
                body: "One click triggers AI grading. Each criterion is scored individually with a written justification.",
              },
              {
                icon: (
                  <BarChart2
                    className="h-8 w-8 text-blue-600"
                    aria-hidden="true"
                  />
                ),
                step: "3",
                title: "Review, override, and approve",
                body: "Read the AI's reasoning. Agree, edit, or override any score or feedback. Lock grades when ready.",
              },
              {
                icon: (
                  <Lightbulb
                    className="h-8 w-8 text-blue-600"
                    aria-hidden="true"
                  />
                ),
                step: "4",
                title: "Act on insights",
                body: "Skill profiles surface class-wide patterns. See who needs help and exactly what to teach next.",
              },
            ].map(({ icon, step, title, body }) => (
              <li key={step} className="flex flex-col items-center text-center">
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-blue-50 ring-1 ring-blue-100">
                  {icon}
                </div>
                <span className="mt-4 text-xs font-semibold uppercase tracking-widest text-blue-700">
                  Step {step}
                </span>
                <h3 className="mt-2 text-base font-semibold text-gray-900">
                  {title}
                </h3>
                <p className="mt-2 text-sm text-gray-600">{body}</p>
              </li>
            ))}
          </ol>

          <div className="mt-10 text-center">
            <Link
              href="/how-it-works"
              className="text-sm font-medium text-blue-700 underline hover:text-blue-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              See the full workflow →
            </Link>
          </div>
        </div>
      </section>

      {/* Bottom CTA */}
      <section className="bg-blue-600 px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-bold text-white">
            {/* {TODO: insert CTA headline} */}
            Ready to get your time back?
          </h2>
          <p className="mt-4 text-lg text-blue-100">
            {/* {TODO: insert CTA body} */}
            Join teachers who spend less time grading and more time teaching.
          </p>
          <Link
            href="/signup?source=landing_cta"
            className="mt-8 inline-block rounded-md bg-white px-8 py-3 text-base font-semibold text-blue-600 shadow-sm hover:bg-blue-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-blue-600"
          >
            Start free trial — no credit card required
          </Link>
        </div>
      </section>
    </>
  );
}
