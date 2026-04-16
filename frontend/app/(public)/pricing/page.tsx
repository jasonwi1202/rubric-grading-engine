import type { Metadata } from "next";
import { PRODUCT_NAME } from "@/lib/constants";

export const metadata: Metadata = {
  title: `Pricing — ${PRODUCT_NAME}`,
  description: `Simple, transparent pricing for ${PRODUCT_NAME}. No surprises.`,
};

/**
 * Pricing page.
 *
 * {TODO: insert pricing tiers and feature comparison table}
 * {TODO: insert FAQ section}
 */
export default function PricingPage() {
  return (
    <section className="mx-auto max-w-4xl px-4 py-16 sm:px-6 lg:px-8">
      <h1 className="text-4xl font-extrabold text-gray-900">Pricing</h1>
      <p className="mt-4 text-xl text-gray-500">
        {/* {TODO: insert pricing overview} */}
        Simple, transparent pricing. No surprises.
      </p>
    </section>
  );
}
