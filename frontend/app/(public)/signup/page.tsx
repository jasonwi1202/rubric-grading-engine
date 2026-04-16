import type { Metadata } from "next";
import { PRODUCT_NAME } from "@/lib/constants";

export const metadata: Metadata = {
  title: `Start Free Trial — ${PRODUCT_NAME}`,
  description: `Create your ${PRODUCT_NAME} account and start grading smarter today.`,
};

/**
 * Sign-up / trial start page.
 *
 * This is a stub. The registration form and backend integration will be
 * implemented in a later milestone.
 *
 * {TODO: insert registration form}
 */
export default function SignupPage() {
  return (
    <section className="mx-auto max-w-sm px-4 py-16 sm:px-6 lg:px-8">
      <h1 className="text-3xl font-extrabold text-gray-900">
        Start your free trial
      </h1>
      <p className="mt-4 text-gray-500">
        {/* {TODO: insert sign-up form} */}
        Create your {PRODUCT_NAME} account — no credit card required.
      </p>
    </section>
  );
}
