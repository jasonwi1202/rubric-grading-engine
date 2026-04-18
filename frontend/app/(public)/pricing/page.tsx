import type { Metadata } from "next";

import { PRODUCT_NAME } from "@/lib/constants";
import PricingContent from "./_pricing-content";

export const metadata: Metadata = {
  title: `Pricing — ${PRODUCT_NAME}`,
  description:
    "Simple, transparent pricing for K-12 writing teachers. Start free — no credit card required. Scale up with School or District plans.",
};

export default function PricingPage() {
  return <PricingContent />;
}
