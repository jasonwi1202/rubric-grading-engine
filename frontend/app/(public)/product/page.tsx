import type { Metadata } from "next";
import { PRODUCT_NAME } from "@/lib/constants";

export const metadata: Metadata = {
  title: `Product — ${PRODUCT_NAME}`,
  description:
    "A deep dive into every feature of the rubric-based AI grading engine built for K-12 writing teachers.",
};

/**
 * Product overview page.
 *
 * {TODO: insert feature deep-dive sections with screenshots}
 * {TODO: insert trust and compliance callout}
 */
export default function ProductPage() {
  return (
    <section className="mx-auto max-w-4xl px-4 py-16 sm:px-6 lg:px-8">
      <h1 className="text-4xl font-extrabold text-gray-900">Product</h1>
      <p className="mt-4 text-xl text-gray-500">
        {/* {TODO: insert product overview copy} */}
        Everything {PRODUCT_NAME} can do — explained for teachers doing due
        diligence.
      </p>
    </section>
  );
}
