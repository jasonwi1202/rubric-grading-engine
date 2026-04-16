import type { Metadata } from "next";
import Link from "next/link";
import { PRODUCT_NAME } from "@/lib/constants";

export const metadata: Metadata = {
  title: `How It Works — ${PRODUCT_NAME}`,
  description:
    "Step-by-step walkthrough of the full AI grading cycle — from rubric creation to student feedback.",
};

const STEPS = [
  {
    step: 1,
    title: "Build your rubric",
    body: "Create criteria, set weights, and add anchor descriptions. Or start from a template.",
  },
  {
    step: 2,
    title: "Create an assignment",
    body: "Attach your rubric, set a due date, and open for submissions.",
  },
  {
    step: 3,
    title: "Upload essays",
    body: "Drag and drop PDF, DOCX, or plain text files. The system auto-assigns to your student roster.",
  },
  {
    step: 4,
    title: "Trigger AI grading",
    body: "One click. AI grades each essay against your rubric with per-criterion scores and written justifications.",
  },
  {
    step: 5,
    title: "Review and override",
    body: "Open any essay. Read the AI's reasoning. Agree, edit, or override any score or feedback.",
  },
  {
    step: 6,
    title: "Lock and share",
    body: "Lock approved grades. Export PDFs to share with students. Pass grades back to your LMS.",
  },
  {
    step: 7,
    title: "See the patterns",
    body: "Skill profiles update automatically. See who needs help and what to teach next.",
  },
] as const;

/**
 * How It Works page — step-by-step workflow explainer.
 *
 * {TODO: insert step illustrations / timeline visuals}
 */
export default function HowItWorksPage() {
  return (
    <section className="mx-auto max-w-4xl px-4 py-16 sm:px-6 lg:px-8">
      <h1 className="text-4xl font-extrabold text-gray-900">How It Works</h1>
      <p className="mt-4 text-xl text-gray-500">
        The full grading cycle — from rubric to insights — in seven steps.
      </p>

      <ol className="mt-12 space-y-10" role="list">
        {STEPS.map(({ step, title, body }) => (
          <li key={step} className="flex gap-6">
            <span
              aria-hidden="true"
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-bold text-white"
            >
              {step}
            </span>
            <div>
              <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
              <p className="mt-1 text-gray-500">{body}</p>
            </div>
          </li>
        ))}
      </ol>

      <div className="mt-16 text-center">
        <Link
          href="/signup?source=how_it_works"
          className="rounded-md bg-blue-600 px-8 py-3 text-base font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
        >
          Start free trial
        </Link>
      </div>
    </section>
  );
}
