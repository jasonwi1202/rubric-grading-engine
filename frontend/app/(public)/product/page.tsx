import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { ShieldCheck, UserCheck, Zap } from "lucide-react";
import { PRODUCT_NAME } from "@/lib/constants";

export const metadata: Metadata = {
  title: `Product — ${PRODUCT_NAME}`,
  description:
    "A deep dive into every feature of the rubric-based AI grading engine built for K-12 writing teachers.",
};

const FEATURES = [
  {
    id: "ai-grading-engine",
    heading: "AI grading engine",
    body: "Upload a class set and trigger grading with one click. The model reads each essay against your rubric, scores every criterion independently, and writes a justification you can read and verify — before any grade is recorded.",
    imageAlt:
      "Screenshot of the AI grading results panel showing per-criterion scores and written justifications",
    imageWidth: 800,
    imageHeight: 500,
  },
  {
    id: "human-in-the-loop-review",
    heading: "Human-in-the-loop review",
    body: "Every AI-suggested score and piece of feedback is a starting point, not a final answer. Open any essay, read the reasoning, and override any score or edit any feedback in seconds. Grades are only recorded when you lock them.",
    imageAlt:
      "Screenshot of the grade review interface showing override controls and feedback editing",
    imageWidth: 800,
    imageHeight: 500,
  },
  {
    id: "student-skill-profiles",
    heading: "Student skill profiles",
    body: "Skill profiles aggregate every graded criterion across every assignment into a persistent view of each student's growth. See at a glance which skills are improving and which gaps are widening — without touching a spreadsheet.",
    imageAlt:
      "Screenshot of a student skill profile showing trend lines across writing criteria over time",
    imageWidth: 800,
    imageHeight: 500,
  },
  {
    id: "class-insights",
    heading: "Class insights and teacher worklist",
    body: "The class heatmap surfaces patterns across the whole cohort — common errors, score distributions, and criteria where most students struggled. The teacher worklist turns those patterns into prioritised actions so you know exactly what to teach next.",
    imageAlt:
      "Screenshot of the class insights heatmap and teacher worklist showing instructional priorities",
    imageWidth: 800,
    imageHeight: 500,
  },
] as const;

const TRUST_ITEMS = [
  {
    icon: ShieldCheck,
    heading: "FERPA compliant",
    body: "Student records are protected under FERPA. Data is never shared with third parties without a signed DPA, and student essays are never used to train AI models.",
    linkHref: "/legal/ferpa",
    linkLabel: "Read our FERPA notice",
  },
  {
    icon: Zap,
    heading: "No data selling — ever",
    body: "Student data is used exclusively for grading and instruction within your account. It is never sold, licensed, or used for advertising. Full details are in our Privacy Policy.",
    linkHref: "/legal/privacy",
    linkLabel: "Read our Privacy Policy",
  },
  {
    icon: UserCheck,
    heading: "Teacher always in control",
    body: "No grade is recorded, no feedback shared, and no action taken without explicit teacher approval. The AI prepares; you decide. That is enforced in the product, not just claimed in marketing.",
    linkHref: "/ai",
    linkLabel: "Read our AI transparency page",
  },
] as const;

/**
 * Product overview page — feature deep-dives and trust/compliance callout.
 */
export default function ProductPage() {
  return (
    <>
      {/* Page intro */}
      <section className="bg-white px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <h1 className="text-4xl font-extrabold tracking-tight text-gray-900 sm:text-5xl">
            Built for teachers doing due diligence
          </h1>
          <p className="mt-6 text-xl text-gray-500">
            Every feature in {PRODUCT_NAME} exists to reduce grading time and
            improve instructional decisions — not to add complexity.
          </p>
        </div>
      </section>

      {/* Feature deep-dives */}
      <section className="bg-gray-50 px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-7xl space-y-24">
          {FEATURES.map(
            ({ id, heading, body, imageAlt, imageWidth, imageHeight }, index) => (
              <div
                key={id}
                className={`flex flex-col gap-12 lg:flex-row lg:items-center ${
                  index % 2 !== 0 ? "lg:flex-row-reverse" : ""
                }`}
              >
                {/* Text */}
                <div className="flex-1">
                  <h2 className="text-3xl font-bold text-gray-900">{heading}</h2>
                  <p className="mt-4 text-lg text-gray-500">{body}</p>
                </div>

                {/* Screenshot placeholder */}
                <div className="flex-1">
                  <Image
                    src="/placeholder-screenshot.svg"
                    alt={imageAlt}
                    width={imageWidth}
                    height={imageHeight}
                    className="rounded-xl border border-gray-200 shadow-md"
                    priority={index === 0}
                  />
                </div>
              </div>
            ),
          )}
        </div>
      </section>

      {/* Trust and compliance callout */}
      <section className="bg-blue-50 px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-7xl">
          <h2 className="text-center text-3xl font-bold text-gray-900">
            Designed with trust and compliance in mind
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-center text-lg text-gray-500">
            Student data is handled with care. We are transparent about what we
            do — and do not do — with it.
          </p>
          <div className="mt-12 grid grid-cols-1 gap-8 sm:grid-cols-3">
            {TRUST_ITEMS.map(({ icon: Icon, heading, body, linkHref, linkLabel }) => (
              <div
                key={heading}
                className="flex flex-col items-start rounded-xl border border-blue-100 bg-white p-8 shadow-sm"
              >
                <Icon className="h-8 w-8 text-blue-600" aria-hidden="true" />
                <h3 className="mt-4 text-lg font-semibold text-gray-900">
                  {heading}
                </h3>
                <p className="mt-2 text-sm text-gray-500">{body}</p>
                <Link
                  href={linkHref}
                  className="mt-4 text-sm font-medium text-blue-600 underline hover:text-blue-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                >
                  {linkLabel}
                </Link>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Bottom CTA */}
      <section className="bg-blue-600 px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-bold text-white">
            Ready to see it in action?
          </h2>
          <p className="mt-4 text-lg text-blue-100">
            Start a free trial and grade your first class set in under an hour.
          </p>
          <Link
            href="/signup?source=product_cta"
            className="mt-8 inline-block rounded-md bg-white px-8 py-3 text-base font-semibold text-blue-600 shadow-sm hover:bg-blue-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-blue-600"
          >
            Start free trial — no credit card required
          </Link>
        </div>
      </section>
    </>
  );
}
