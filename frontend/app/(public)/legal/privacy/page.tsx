import type { Metadata } from "next";
import { PRODUCT_NAME } from "@/lib/constants";

export const metadata: Metadata = {
  title: `Privacy Policy — ${PRODUCT_NAME}`,
};

/** {TODO: insert full Privacy Policy copy} */
export default function PrivacyPage() {
  return (
    <section className="mx-auto max-w-3xl px-4 py-16 sm:px-6 lg:px-8">
      <h1 className="text-4xl font-extrabold text-gray-900">Privacy Policy</h1>
      <p className="mt-4 text-gray-500">
        {/* {TODO: insert Privacy Policy} */}
        Last updated: TBD
      </p>
    </section>
  );
}
