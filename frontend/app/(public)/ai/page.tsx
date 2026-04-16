import type { Metadata } from "next";
import Link from "next/link";
import { PRODUCT_NAME } from "@/lib/constants";

export const metadata: Metadata = {
  title: `AI Transparency — ${PRODUCT_NAME}`,
  description: `How ${PRODUCT_NAME} uses AI, what data it touches, and what the teacher always controls.`,
};

/**
 * AI transparency page — explains the AI's role, limitations, and the
 * human-in-the-loop guarantee.
 *
 * {TODO: insert model details and versioning}
 * {TODO: insert data usage policy details}
 */
export default function AiPage() {
  return (
    <section className="mx-auto max-w-3xl px-4 py-16 sm:px-6 lg:px-8">
      <h1 className="text-4xl font-extrabold text-gray-900">
        AI Transparency
      </h1>
      <p className="mt-4 text-xl text-gray-500">
        What the AI does, what it does not do, and why the teacher is always in
        control.
      </p>

      <div className="mt-10 space-y-8 text-gray-600">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">
            What the AI does
          </h2>
          <p className="mt-2">
            {/* {TODO: expand} */}
            {PRODUCT_NAME} uses a large language model to score each essay
            criterion-by-criterion against the teacher&apos;s rubric. For every
            criterion, the AI produces a numeric score and a written
            justification explaining its reasoning.
          </p>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-gray-900">
            What the AI does not do
          </h2>
          <ul className="mt-2 list-disc space-y-1 pl-6">
            <li>It does not record, finalise, or share any grade.</li>
            <li>
              It does not use student essay content for model training.
            </li>
            <li>
              It does not make instructional decisions — that is the
              teacher&apos;s role.
            </li>
          </ul>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-gray-900">
            Human-in-the-loop guarantee
          </h2>
          <p className="mt-2">
            Every AI score is a draft. The teacher reviews, can override any
            score or rewrite any feedback, and explicitly locks grades before
            they become final. Nothing is shared with students until the teacher
            approves it.
          </p>
        </div>

        <div>
          <h2 className="text-xl font-semibold text-gray-900">
            FERPA &amp; data privacy
          </h2>
          <p className="mt-2">
            Student essay content is processed only for the purpose of grading.
            It is never used for advertising, analytics sold to third parties,
            or AI fine-tuning. See our{" "}
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
            .
          </p>
        </div>
      </div>
    </section>
  );
}
