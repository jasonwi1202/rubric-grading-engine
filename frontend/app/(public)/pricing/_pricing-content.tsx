"use client";

/**
 * Pricing page interactive content — /pricing
 *
 * This client component owns the billing toggle state and the inquiry form.
 * The parent page.tsx is a server component that exports metadata for SEO.
 *
 * Sections:
 *   1. Hero + billing toggle (monthly / annual)
 *   2. Tier pricing cards (Trial · Teacher · School · District)
 *   3. Feature comparison table
 *   4. FAQ accessible accordion (<details>/<summary>)
 *   5. School / District inquiry form → POST /api/v1/contact/inquiry
 *   6. Trust signals
 *
 * NOTE: All price points use [PRICE] placeholders. This page must not be
 * deployed to production with literal "[PRICE]" text. Replace with actual
 * prices before launch.
 */

import React, { useState } from "react";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { CheckIcon } from "lucide-react";

import { submitContactInquiry } from "@/lib/api/contact";
import {
  contactInquirySchema,
  type ContactInquiryFormValues,
} from "@/lib/schemas/contact";
import { ApiError } from "@/lib/api/errors";

// ---------------------------------------------------------------------------
// Pricing data
// ---------------------------------------------------------------------------

type BillingPeriod = "monthly" | "annual";

interface TierFeature {
  label: string;
  included: boolean | string;
}

interface PricingTier {
  id: string;
  name: string;
  badge?: string;
  description: string;
  monthlyPrice: string;
  annualPrice: string;
  annualSavings?: string;
  cta: string;
  ctaHref: string;
  features: TierFeature[];
  highlight?: boolean;
}

const TIERS: PricingTier[] = [
  {
    id: "trial",
    name: "Free Trial",
    description: "Try everything free for 30 days — no credit card required.",
    monthlyPrice: "Free",
    annualPrice: "Free",
    cta: "Start free trial",
    ctaHref: "/signup?plan=trial",
    features: [
      { label: "Full feature access", included: true },
      { label: "Up to 30 essays", included: true },
      { label: "30-day limit", included: "30 days" },
      { label: "1 teacher", included: true },
      { label: "Email support", included: true },
    ],
  },
  {
    id: "teacher",
    name: "Teacher",
    badge: "Most popular",
    description: "For individual teachers who grade regularly.",
    // TODO [PRICE]: Set final monthly price before production launch.
    monthlyPrice: "[PRICE]/mo",
    // TODO [PRICE]: Set final annual price before production launch.
    annualPrice: "[PRICE]/mo",
    annualSavings: "Save ~20%",
    cta: "Start free trial",
    ctaHref: "/signup?plan=teacher",
    highlight: true,
    features: [
      { label: "Unlimited essays", included: true },
      { label: "1 teacher seat", included: true },
      { label: "All core features", included: true },
      { label: "Student skill profiles", included: true },
      { label: "Email support", included: true },
    ],
  },
  {
    id: "school",
    name: "School",
    description: "For departments and small schools with multiple teachers.",
    // TODO [PRICE]: Set final per-seat price before production launch.
    monthlyPrice: "[PRICE]/teacher/mo",
    // TODO [PRICE]: Set final per-seat annual price before production launch.
    annualPrice: "[PRICE]/teacher/mo",
    annualSavings: "Save ~20%",
    cta: "Contact sales",
    ctaHref: "#inquiry",
    features: [
      { label: "Unlimited essays", included: true },
      { label: "Multiple teacher seats", included: true },
      { label: "All Teacher features", included: true },
      { label: "School admin view", included: true },
      { label: "Priority support", included: true },
      { label: "Data Processing Agreement", included: true },
    ],
  },
  {
    id: "district",
    name: "District",
    description:
      "For district procurement with unlimited seats and LMS support.",
    monthlyPrice: "Custom",
    annualPrice: "Custom",
    cta: "Contact us",
    ctaHref: "#inquiry",
    features: [
      { label: "Unlimited seats", included: true },
      { label: "All School features", included: true },
      { label: "LMS integrations (Phase 2)", included: "Coming" },
      { label: "SSO / SAML", included: "Coming" },
      { label: "Dedicated onboarding", included: true },
      { label: "Invoice & PO payment", included: true },
      { label: "Data Processing Agreement", included: true },
    ],
  },
];

const COMPARISON_FEATURES: {
  category: string;
  rows: { label: string; values: (boolean | string)[] }[];
}[] = [
  {
    category: "Grading",
    rows: [
      { label: "AI grading per criterion", values: [true, true, true, true] },
      { label: "Written justifications", values: [true, true, true, true] },
      { label: "Teacher score override", values: [true, true, true, true] },
      { label: "Grade locking", values: [true, true, true, true] },
      { label: "Unlimited essays", values: [false, true, true, true] },
    ],
  },
  {
    category: "Insights",
    rows: [
      { label: "Student skill profiles", values: [true, true, true, true] },
      { label: "Instructional priorities", values: [true, true, true, true] },
    ],
  },
  {
    category: "Administration",
    rows: [
      { label: "School admin view", values: [false, false, true, true] },
      { label: "Multiple teacher seats", values: [false, false, true, true] },
      { label: "SSO / SAML", values: [false, false, false, "Coming"] },
      { label: "LMS integrations", values: [false, false, false, "Coming"] },
    ],
  },
  {
    category: "Support & Compliance",
    rows: [
      { label: "Email support", values: [true, true, true, true] },
      { label: "Priority support", values: [false, false, true, true] },
      {
        label: "Data Processing Agreement",
        values: [false, false, true, true],
      },
      {
        label: "Dedicated onboarding",
        values: [false, false, false, true],
      },
    ],
  },
];

const FAQ_ITEMS = [
  {
    question: "Do I need a credit card to start the trial?",
    answer:
      "No. The 30-day free trial requires no credit card. You can grade up to 30 essays with full feature access. If you want to continue after the trial, you choose a plan then.",
  },
  {
    question: "What happens when my trial ends?",
    answer:
      "Your essays, rubrics, and grades are preserved — nothing is deleted. Grading new essays and uploading files are paused until you subscribe. You can resume at any time.",
  },
  {
    question: "Can I switch plans later?",
    answer:
      "Yes. You can upgrade or downgrade at any time. Upgrades take effect immediately; downgrades take effect at the end of your current billing period.",
  },
  {
    question: "Does my school need to pay, or can I pay personally?",
    answer:
      "Either. The Teacher tier is fully self-serve and can be paid personally by card. The School and District tiers can be invoiced to your school's accounts payable — no personal card required.",
  },
  {
    question: "Is student data safe?",
    answer:
      "Yes. GradeWise is FERPA-compliant. Student essay content and grades are education records that are never used to train AI models and never shared with third parties without a signed Data Processing Agreement.",
  },
  {
    question: "Does the AI replace my grading judgment?",
    answer:
      "No — and this is by design. The AI prepares a draft grade for each criterion; you review, override, and approve every grade before it is recorded. No grade is ever recorded without your explicit approval.",
  },
  {
    question: "What integrations are available?",
    answer:
      "Currently: manual file upload (PDF, DOCX, TXT). Google Classroom and Canvas integrations are planned for Phase 2 (District tier).",
  },
  {
    question: "What if I need a Data Processing Agreement?",
    answer:
      "A DPA is available on the School and District tiers. Reach out via the inquiry form below and we will send you a signed DPA within 48 hours.",
  },
];

// ---------------------------------------------------------------------------
// Small shared components
// ---------------------------------------------------------------------------

function FeatureValue({ value }: { value: boolean | string }) {
  if (value === true)
    return (
      <CheckIcon
        className="mx-auto h-5 w-5 text-blue-600"
        aria-label="Included"
      />
    );
  if (value === false)
    return (
      <span className="text-gray-300" aria-label="Not included">
        —
      </span>
    );
  return <span className="text-xs font-medium text-blue-500">{value}</span>;
}

// ---------------------------------------------------------------------------
// Inquiry form
// ---------------------------------------------------------------------------

function InquiryForm() {
  const [submitState, setSubmitState] = useState<
    "idle" | "submitting" | "success" | "error"
  >("idle");
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ContactInquiryFormValues>({
    resolver: zodResolver(contactInquirySchema),
  });

  const onSubmit = async (values: ContactInquiryFormValues) => {
    setServerError(null);
    setSubmitState("submitting");
    try {
      await submitContactInquiry(values);
      setSubmitState("success");
      reset();
    } catch (err) {
      setSubmitState("error");
      if (err instanceof ApiError && err.code === "RATE_LIMITED") {
        setServerError(
          "Too many submissions from your network. Please try again later.",
        );
      } else {
        setServerError("Submission failed. Please try again.");
      }
    }
  };

  if (submitState === "success") {
    return (
      <div className="rounded-lg bg-green-50 p-8 text-center">
        <CheckIcon
          className="mx-auto mb-4 h-12 w-12 text-green-500"
          aria-hidden="true"
        />
        <h3 className="text-xl font-semibold text-gray-900">
          We received your inquiry!
        </h3>
        <p className="mt-2 text-gray-600">
          {"We'll be in touch within one business day to set up your DPA and onboarding."}
        </p>
      </div>
    );
  }

  const inputClass =
    "mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50";
  const labelClass = "block text-sm font-medium text-gray-700";
  const errorClass = "mt-1 text-sm text-red-600";

  return (
    <form
      id="inquiry"
      onSubmit={handleSubmit(onSubmit)}
      noValidate
      className="space-y-5"
      aria-label="School and district inquiry form"
    >
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        {/* Name */}
        <div>
          <label htmlFor="inq-name" className={labelClass}>
            Your name <span aria-hidden="true">*</span>
          </label>
          <input
            id="inq-name"
            type="text"
            autoComplete="name"
            className={inputClass}
            aria-describedby={errors.name ? "inq-name-error" : undefined}
            aria-invalid={!!errors.name}
            aria-required="true"
            disabled={isSubmitting}
            {...register("name")}
          />
          {errors.name && (
            <p id="inq-name-error" className={errorClass} role="alert">
              {errors.name.message}
            </p>
          )}
        </div>

        {/* Email */}
        <div>
          <label htmlFor="inq-email" className={labelClass}>
            Work email <span aria-hidden="true">*</span>
          </label>
          <input
            id="inq-email"
            type="email"
            autoComplete="email"
            className={inputClass}
            aria-describedby={errors.email ? "inq-email-error" : undefined}
            aria-invalid={!!errors.email}
            aria-required="true"
            disabled={isSubmitting}
            {...register("email")}
          />
          {errors.email && (
            <p id="inq-email-error" className={errorClass} role="alert">
              {errors.email.message}
            </p>
          )}
        </div>

        {/* School name */}
        <div>
          <label htmlFor="inq-school" className={labelClass}>
            School name <span aria-hidden="true">*</span>
          </label>
          <input
            id="inq-school"
            type="text"
            autoComplete="organization"
            className={inputClass}
            aria-describedby={
              errors.school_name ? "inq-school-error" : undefined
            }
            aria-invalid={!!errors.school_name}
            aria-required="true"
            disabled={isSubmitting}
            {...register("school_name")}
          />
          {errors.school_name && (
            <p id="inq-school-error" className={errorClass} role="alert">
              {errors.school_name.message}
            </p>
          )}
        </div>

        {/* District */}
        <div>
          <label htmlFor="inq-district" className={labelClass}>
            District{" "}
            <span className="text-gray-400">(optional)</span>
          </label>
          <input
            id="inq-district"
            type="text"
            className={inputClass}
            aria-describedby={
              errors.district ? "inq-district-error" : undefined
            }
            aria-invalid={!!errors.district}
            disabled={isSubmitting}
            {...register("district")}
          />
          {errors.district && (
            <p id="inq-district-error" className={errorClass} role="alert">
              {errors.district.message}
            </p>
          )}
        </div>

        {/* Estimated teachers */}
        <div>
          <label htmlFor="inq-teachers" className={labelClass}>
            Estimated number of teachers{" "}
            <span className="text-gray-400">(optional)</span>
          </label>
          <input
            id="inq-teachers"
            type="number"
            min={1}
            className={inputClass}
            aria-describedby={
              errors.estimated_teachers ? "inq-teachers-error" : undefined
            }
            aria-invalid={!!errors.estimated_teachers}
            disabled={isSubmitting}
            {...register("estimated_teachers", {
              setValueAs: (value) => {
                if (value === "" || value === null || value === undefined) {
                  return undefined;
                }
                const n = Number(value);
                return Number.isNaN(n) ? undefined : n;
              },
            })}
          />
          {errors.estimated_teachers && (
            <p id="inq-teachers-error" className={errorClass} role="alert">
              {errors.estimated_teachers.message}
            </p>
          )}
        </div>
      </div>

      {/* Message */}
      <div>
        <label htmlFor="inq-message" className={labelClass}>
          Message <span className="text-gray-400">(optional)</span>
        </label>
        <textarea
          id="inq-message"
          rows={4}
          className={inputClass}
          aria-describedby={errors.message ? "inq-message-error" : undefined}
          aria-invalid={!!errors.message}
          disabled={isSubmitting}
          placeholder="Tell us about your school's needs, timeline, or any questions."
          {...register("message")}
        />
        {errors.message && (
          <p id="inq-message-error" className={errorClass} role="alert">
            {errors.message.message}
          </p>
        )}
      </div>

      {/* Server error */}
      {submitState === "error" && serverError && (
        <p
          className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700"
          role="alert"
        >
          {serverError}
        </p>
      )}

      <button
        type="submit"
        disabled={isSubmitting}
        className="rounded-md bg-blue-600 px-6 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
      >
        {isSubmitting ? "Sending…" : "Send inquiry"}
      </button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Page content
// ---------------------------------------------------------------------------

export default function PricingContent() {
  const [billing, setBilling] = useState<BillingPeriod>("monthly");

  return (
    <>
      {/* Hero + toggle */}
      <section className="bg-white px-4 py-20 sm:px-6 lg:px-8">
        <div className="mx-auto max-w-3xl text-center">
          <h1 className="text-4xl font-extrabold tracking-tight text-gray-900 sm:text-5xl">
            Simple pricing for teachers.{" "}
            <span className="text-blue-600">No surprises.</span>
          </h1>
          <p className="mt-6 text-xl text-gray-600">
            Start free — no credit card required. Scale up when you&apos;re ready.
          </p>

          {/* Billing toggle */}
          <div
            className="mt-10 inline-flex items-center gap-3 rounded-full border border-gray-200 bg-gray-50 p-1"
            role="group"
            aria-label="Billing period"
          >
            <button
              type="button"
              onClick={() => setBilling("monthly")}
              className={`rounded-full px-5 py-2 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 ${
                billing === "monthly"
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              }`}
              aria-pressed={billing === "monthly"}
            >
              Monthly
            </button>
            <button
              type="button"
              onClick={() => setBilling("annual")}
              className={`rounded-full px-5 py-2 text-sm font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 ${
                billing === "annual"
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              }`}
              aria-pressed={billing === "annual"}
            >
              Annual{" "}
              <span className="ml-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
                Save ~20%
              </span>
            </button>
          </div>
        </div>
      </section>

      {/* Pricing cards */}
      <section
        className="bg-gray-50 px-4 pb-16 sm:px-6 lg:px-8"
        aria-label="Pricing tiers"
      >
        <div className="mx-auto max-w-7xl">
          <div className="grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-4">
            {TIERS.map((tier) => {
              const price =
                billing === "annual" ? tier.annualPrice : tier.monthlyPrice;
              const saving =
                billing === "annual" ? tier.annualSavings : undefined;

              return (
                <div
                  key={tier.id}
                  className={`relative flex flex-col rounded-2xl border bg-white p-8 shadow-sm ${
                    tier.highlight
                      ? "border-blue-600 ring-2 ring-blue-600"
                      : "border-gray-200"
                  }`}
                >
                  {tier.badge && (
                    <span className="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-blue-600 px-4 py-1 text-xs font-semibold text-white">
                      {tier.badge}
                    </span>
                  )}

                  <div className="flex-1">
                    <h2 className="text-lg font-bold text-gray-900">
                      {tier.name}
                    </h2>
                    <p className="mt-1 text-sm text-gray-600">
                      {tier.description}
                    </p>

                    <div className="mt-4">
                      <span
                        className="text-3xl font-extrabold text-gray-900"
                        aria-label={`Price: ${price}`}
                      >
                        {price}
                      </span>
                      {saving && (
                        <span className="ml-2 rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">
                          {saving}
                        </span>
                      )}
                    </div>

                    <ul className="mt-6 space-y-3" aria-label="Features">
                      {tier.features.map((feature) => (
                        <li
                          key={feature.label}
                          className="flex items-start gap-2"
                        >
                          {feature.included === true ? (
                            <CheckIcon
                              className="mt-0.5 h-4 w-4 shrink-0 text-blue-600"
                              aria-hidden="true"
                            />
                          ) : (
                            <span
                              className="mt-0.5 h-4 w-4 shrink-0 text-center text-gray-300"
                              aria-hidden="true"
                            >
                              —
                            </span>
                          )}
                          <span className="text-sm text-gray-600">
                            {feature.label}
                            {typeof feature.included === "string" && (
                              <span className="ml-1 text-xs text-blue-500">
                                ({feature.included})
                              </span>
                            )}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <Link
                    href={tier.ctaHref}
                    className={`mt-8 block rounded-md px-4 py-2.5 text-center text-sm font-semibold shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 ${
                      tier.highlight
                        ? "bg-blue-600 text-white hover:bg-blue-700 focus-visible:ring-blue-600"
                        : "border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 focus-visible:ring-gray-400"
                    }`}
                  >
                    {tier.cta}
                  </Link>
                </div>
              );
            })}
          </div>
          <p className="mt-6 text-center text-xs text-amber-600">
            ⚠️ TODO [PRICE]: Price placeholders above must be replaced before
            production launch.
          </p>
        </div>
      </section>

      {/* Feature comparison table */}
      <section
        className="bg-white px-4 py-16 sm:px-6 lg:px-8"
        aria-label="Feature comparison table"
      >
        <div className="mx-auto max-w-7xl">
          <h2 className="text-center text-2xl font-bold text-gray-900">
            Compare plans
          </h2>

          <div className="mt-8 overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">
                Feature comparison across pricing tiers
              </caption>
              <thead>
                <tr>
                  <th className="w-1/3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-gray-500">
                    Feature
                  </th>
                  {TIERS.map((tier) => (
                    <th
                      key={tier.id}
                      className="px-4 py-3 text-center text-xs font-semibold uppercase tracking-wide text-gray-900"
                      scope="col"
                    >
                      {tier.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {COMPARISON_FEATURES.map((group) => (
                  <React.Fragment key={group.category}>
                    <tr className="bg-gray-50">
                      <td
                        colSpan={TIERS.length + 1}
                        className="py-2 pl-2 text-xs font-semibold uppercase tracking-wide text-gray-500"
                      >
                        {group.category}
                      </td>
                    </tr>
                    {group.rows.map((row) => (
                      <tr key={row.label} className="hover:bg-gray-50">
                        <td className="py-3 text-gray-700">{row.label}</td>
                        {row.values.map((val, idx) => (
                          <td
                            key={TIERS[idx]?.id ?? idx}
                            className="px-4 py-3 text-center"
                          >
                            <FeatureValue value={val} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* FAQ */}
      <section
        className="bg-gray-50 px-4 py-16 sm:px-6 lg:px-8"
        aria-label="Frequently asked questions"
      >
        <div className="mx-auto max-w-3xl">
          <h2 className="text-center text-2xl font-bold text-gray-900">
            Frequently asked questions
          </h2>

          <div className="mt-8 space-y-2">
            {FAQ_ITEMS.map((item) => (
              <details
                key={item.question}
                className="group rounded-lg border border-gray-200 bg-white"
              >
                <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-4 font-medium text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500">
                  <span>{item.question}</span>
                  <span
                    className="ml-4 shrink-0 text-gray-400 transition-transform group-open:rotate-180"
                    aria-hidden="true"
                  >
                    ▾
                  </span>
                </summary>
                <p className="px-5 pb-4 text-sm text-gray-600">
                  {item.answer}
                </p>
              </details>
            ))}
          </div>
        </div>
      </section>

      {/* Inquiry form */}
      <section
        className="bg-white px-4 py-16 sm:px-6 lg:px-8"
        aria-labelledby="inquiry-heading"
      >
        <div className="mx-auto max-w-2xl">
          <h2
            id="inquiry-heading"
            className="text-2xl font-bold text-gray-900"
          >
            School or district inquiry
          </h2>
          <p className="mt-3 text-gray-600">
            Need a purchase order, IT review, custom onboarding, or a Data
            Processing Agreement? Fill in the form below and we&apos;ll get
            back to you within one business day.
          </p>
          <div className="mt-8">
            <InquiryForm />
          </div>
        </div>
      </section>

      {/* Trust signals */}
      <section
        className="bg-blue-600 px-4 py-12 sm:px-6 lg:px-8"
        aria-label="Trust signals"
      >
        <div className="mx-auto max-w-5xl">
          <ul className="grid grid-cols-1 gap-4 text-center text-sm font-medium text-blue-100 sm:grid-cols-2 lg:grid-cols-5">
            {[
              "FERPA compliant",
              "No student data used for AI training",
              "Human-in-the-loop — teacher reviews every grade",
              "Cancel anytime",
              "Runs in your browser — no software to install",
            ].map((signal) => (
              <li
                key={signal}
                className="flex items-center justify-center gap-2"
              >
                <CheckIcon
                  className="h-4 w-4 shrink-0 text-blue-300"
                  aria-hidden="true"
                />
                {signal}
              </li>
            ))}
          </ul>
        </div>
      </section>
    </>
  );
}
