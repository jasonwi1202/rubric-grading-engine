import type { Metadata } from "next";
import Link from "next/link";
import {
  ClipboardList,
  FileText,
  Upload,
  Zap,
  PenLine,
  Lock,
  TrendingUp,
} from "lucide-react";
import { PRODUCT_NAME } from "@/lib/constants";

export const metadata: Metadata = {
  title: `How It Works — ${PRODUCT_NAME}`,
  description:
    "Step-by-step walkthrough of the full AI grading cycle — from rubric creation to student feedback.",
};

const STEPS = [
  {
    step: 1,
    icon: ClipboardList,
    title: "Build your rubric",
    body: "Create criteria, set weights, and add anchor descriptions. Or start from a template.",
  },
  {
    step: 2,
    icon: FileText,
    title: "Create an assignment",
    body: "Attach your rubric, set a due date, and open for submissions.",
  },
  {
    step: 3,
    icon: Upload,
    title: "Upload essays",
    body: "Drag and drop PDF, DOCX, or plain text files. The system auto-assigns them to your student roster.",
  },
  {
    step: 4,
    icon: Zap,
    title: "Trigger AI grading",
    body: "One click. AI grades each essay against your rubric with per-criterion scores and written justifications.",
  },
  {
    step: 5,
    icon: PenLine,
    title: "Review and override",
    body: "Open any essay. Read the AI's reasoning. Agree, edit, or override any score or feedback.",
  },
  {
    step: 6,
    icon: Lock,
    title: "Lock and share",
    body: "Lock approved grades. Export PDFs to share with students. Pass grades back to your LMS.",
  },
  {
    step: 7,
    icon: TrendingUp,
    title: "See the patterns",
    body: "Skill profiles update automatically. See who needs help and what to teach next.",
  },
] as const;

/**
 * How It Works page — step-by-step workflow explainer with visual timeline.
 */
export default function HowItWorksPage() {
  return (
    <>
      {/* Page intro */}
      <section className="bg-white px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <h1 className="text-4xl font-extrabold tracking-tight text-gray-900 sm:text-5xl">
            How it works
          </h1>
          <p className="mt-6 text-xl text-gray-500">
            The full grading cycle — from rubric to insights — in seven steps.
          </p>
        </div>
      </section>

      {/* Visual timeline */}
      <section className="bg-gray-50 px-4 pb-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl">
          {/* Workflow stage labels */}
          <div
            aria-hidden="true"
            className="mb-10 hidden items-center justify-between gap-2 text-xs font-semibold uppercase tracking-widest text-blue-600 sm:flex"
          >
            {["Upload", "Assign", "Grade", "Review", "Export"].map((label) => (
              <span
                key={label}
                className="rounded-full bg-blue-100 px-3 py-1"
              >
                {label}
              </span>
            ))}
          </div>

          <ol className="space-y-0" role="list">
            {STEPS.map(({ step, icon: Icon, title, body }, index) => (
              <li key={step} className="relative flex gap-6">
                {/* Vertical connector line — hidden after the last step */}
                {index < STEPS.length - 1 && (
                  <div
                    aria-hidden="true"
                    className="absolute left-5 top-10 h-full w-0.5 bg-blue-200"
                  />
                )}

                {/* Step number bubble */}
                <div
                  aria-hidden="true"
                  className="relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white shadow-sm"
                >
                  {step}
                </div>

                {/* Step content */}
                <div className="pb-10">
                  <div className="flex items-center gap-2">
                    <Icon
                      className="h-5 w-5 text-blue-600"
                      aria-hidden="true"
                    />
                    <h2 className="text-lg font-semibold text-gray-900">
                      {title}
                    </h2>
                  </div>
                  <p className="mt-1 text-gray-500">{body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Bottom CTA */}
      <section className="bg-blue-600 px-4 py-16 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-2xl text-center">
          <h2 className="text-3xl font-bold text-white">
            Ready to try it yourself?
          </h2>
          <p className="mt-4 text-lg text-blue-100">
            Start a free trial and run your first grading session today.
          </p>
          <Link
            href="/signup?source=how_it_works_cta"
            className="mt-8 inline-block rounded-md bg-white px-8 py-3 text-base font-semibold text-blue-600 shadow-sm hover:bg-blue-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-blue-600"
          >
            Start free trial
          </Link>
        </div>
      </section>
    </>
  );
}
