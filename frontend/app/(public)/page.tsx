import type { Metadata } from "next";
import Link from "next/link";
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
          <h1 className="text-4xl font-extrabold tracking-tight text-gray-900 sm:text-5xl">
            {/* {TODO: insert hero headline} */}
            Grade smarter. Teach better.
          </h1>
          <p className="mt-6 text-xl text-gray-500">
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
          <p className="mt-4 text-sm text-gray-400">
            {/* {TODO: insert social proof signal} */}
            No credit card required.
          </p>
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
                title: "AI grading with transparent reasoning",
                body: "Each criterion scored individually with a written justification you can read and verify.",
              },
              {
                title: "Student skill profiles",
                body: "Persistent skill tracking across assignments surfaces gaps before they widen.",
              },
              {
                title: "Teacher-guided instruction",
                body: "Instructional priorities surfaced from real student data — not gut feel.",
              },
              {
                title: "Human-in-the-loop, always",
                body: "AI prepares; you decide. No grade is recorded until you approve it.",
              },
            ].map(({ title, body }) => (
              <div key={title} className="rounded-lg bg-white p-6 shadow-sm">
                <h3 className="font-semibold text-gray-900">{title}</h3>
                <p className="mt-2 text-sm text-gray-500">{body}</p>
              </div>
            ))}
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
