import type { Metadata } from "next";
import { PRODUCT_NAME, SUPPORT_EMAIL } from "@/lib/constants";

export const metadata: Metadata = {
  title: `About — ${PRODUCT_NAME}`,
  description: `The mission, principles, and team behind ${PRODUCT_NAME}.`,
};

/**
 * About page — company background, mission, and principles.
 *
 * {TODO: insert team bios}
 * {TODO: insert mission statement}
 * {TODO: insert contact information}
 */
export default function AboutPage() {
  return (
    <section className="mx-auto max-w-3xl px-4 py-16 sm:px-6 lg:px-8">
      <h1 className="text-4xl font-extrabold text-gray-900">About</h1>

      <div className="mt-8 space-y-6 text-lg text-gray-600">
        <p>
          {/* {TODO: insert mission statement} */}
          {PRODUCT_NAME} exists because teachers spend too much time grading and
          too little time teaching. We built a grading assistant that works the
          way teachers think — rubric-first, criterion-by-criterion, with every
          AI decision explainable and overridable.
        </p>
        <p>
          {/* {TODO: insert team overview} */}
          Human-in-the-loop is not a slogan. No grade is recorded, no feedback
          shared, until the teacher approves it.
        </p>
        <p>
          {/* {TODO: insert contact info} */}
          Questions? Partnership inquiries? Press? Reach us at{" "}
          <a
            href={`mailto:${SUPPORT_EMAIL}`}
            className="text-blue-600 underline hover:text-blue-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            {SUPPORT_EMAIL}
          </a>
          .
        </p>
      </div>
    </section>
  );
}
