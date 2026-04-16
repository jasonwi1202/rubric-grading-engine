import type { Metadata } from "next";
import { PRODUCT_NAME } from "@/lib/constants";

export const metadata: Metadata = {
  title: `FERPA & COPPA Notice — ${PRODUCT_NAME}`,
};

/** {TODO: insert full FERPA + COPPA notice copy} */
export default function FerpaPage() {
  return (
    <section className="mx-auto max-w-3xl px-4 py-16 sm:px-6 lg:px-8">
      <h1 className="text-4xl font-extrabold text-gray-900">
        FERPA &amp; COPPA Notice
      </h1>
      <p className="mt-4 text-gray-500">
        {/* {TODO: insert FERPA + COPPA notice} */}
        {PRODUCT_NAME} is committed to protecting student privacy under FERPA
        and COPPA. This notice explains how we handle student education records.
      </p>
    </section>
  );
}
