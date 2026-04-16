import type { Metadata } from "next";
import { PRODUCT_NAME } from "@/lib/constants";

export const metadata: Metadata = {
  title: `Terms of Service — ${PRODUCT_NAME}`,
};

/** {TODO: insert full Terms of Service copy} */
export default function TermsPage() {
  return (
    <section className="mx-auto max-w-3xl px-4 py-16 sm:px-6 lg:px-8">
      <h1 className="text-4xl font-extrabold text-gray-900">
        Terms of Service
      </h1>
      <p className="mt-4 text-gray-500">
        {/* {TODO: insert Terms of Service} */}
        Last updated: {new Date().getFullYear()}
      </p>
    </section>
  );
}
