"use client";

/**
 * DPA request form — /legal/dpa
 *
 * Collects school administrator contact info and submits a DPA request to
 * POST /api/v1/contact/dpa-request. Only school admin contact info is
 * collected — no student PII.
 *
 * This is a client component; the parent page.tsx is a server component.
 */

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";

import { submitDpaRequest } from "@/lib/api/dpa";
import { dpaRequestSchema, type DpaRequestFormValues } from "@/lib/schemas/dpa";
import { ApiError } from "@/lib/api/errors";

export default function DpaRequestForm() {
  const [submitted, setSubmitted] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<DpaRequestFormValues>({
    resolver: zodResolver(dpaRequestSchema),
  });

  async function onSubmit(values: DpaRequestFormValues) {
    setServerError(null);
    try {
      await submitDpaRequest(values);
      setSubmitted(true);
    } catch (err) {
      if (err instanceof ApiError) {
        setServerError(err.message ?? "Something went wrong. Please try again.");
      } else {
        setServerError("Something went wrong. Please try again.");
      }
    }
  }

  if (submitted) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="rounded-lg border border-green-200 bg-green-50 p-6"
      >
        <h3 className="text-lg font-semibold text-green-800">
          Request received!
        </h3>
        <p className="mt-2 text-sm text-green-700">
          Thank you for your request. We will review it and respond within 2
          business days with a draft DPA for your review.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-10 rounded-lg border border-gray-200 bg-gray-50 p-6 print:hidden">
      <h2 className="text-xl font-semibold text-gray-900">Request a DPA</h2>
      <p className="mt-1 text-sm text-gray-600">
        Fill out the form below and we will respond within 2 business days with
        a draft DPA for your district&apos;s review.
      </p>

      {serverError && (
        <div
          role="alert"
          className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700"
        >
          {serverError}
        </div>
      )}

      <form
        onSubmit={handleSubmit(onSubmit)}
        noValidate
        className="mt-6 space-y-4"
      >
        {/* Name */}
        <div>
          <label
            htmlFor="dpa-name"
            className="block text-sm font-medium text-gray-700"
          >
            Your name <span aria-hidden="true">*</span>
          </label>
          <input
            id="dpa-name"
            type="text"
            autoComplete="name"
            aria-required="true"
            aria-describedby={errors.name ? "dpa-name-error" : undefined}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
            {...register("name")}
          />
          {errors.name && (
            <p id="dpa-name-error" role="alert" className="mt-1 text-xs text-red-600">
              {errors.name.message}
            </p>
          )}
        </div>

        {/* Email */}
        <div>
          <label
            htmlFor="dpa-email"
            className="block text-sm font-medium text-gray-700"
          >
            Work email <span aria-hidden="true">*</span>
          </label>
          <input
            id="dpa-email"
            type="email"
            autoComplete="email"
            aria-required="true"
            aria-describedby={errors.email ? "dpa-email-error" : undefined}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
            {...register("email")}
          />
          {errors.email && (
            <p id="dpa-email-error" role="alert" className="mt-1 text-xs text-red-600">
              {errors.email.message}
            </p>
          )}
        </div>

        {/* School name */}
        <div>
          <label
            htmlFor="dpa-school"
            className="block text-sm font-medium text-gray-700"
          >
            School or district name <span aria-hidden="true">*</span>
          </label>
          <input
            id="dpa-school"
            type="text"
            autoComplete="organization"
            aria-required="true"
            aria-describedby={errors.school_name ? "dpa-school-error" : undefined}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
            {...register("school_name")}
          />
          {errors.school_name && (
            <p id="dpa-school-error" role="alert" className="mt-1 text-xs text-red-600">
              {errors.school_name.message}
            </p>
          )}
        </div>

        {/* District (optional) */}
        <div>
          <label
            htmlFor="dpa-district"
            className="block text-sm font-medium text-gray-700"
          >
            District{" "}
            <span className="font-normal text-gray-400">(optional)</span>
          </label>
          <input
            id="dpa-district"
            type="text"
            autoComplete="organization"
            aria-describedby={errors.district ? "dpa-district-error" : undefined}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
            {...register("district")}
          />
          {errors.district && (
            <p id="dpa-district-error" role="alert" className="mt-1 text-xs text-red-600">
              {errors.district.message}
            </p>
          )}
        </div>

        {/* Message (optional) */}
        <div>
          <label
            htmlFor="dpa-message"
            className="block text-sm font-medium text-gray-700"
          >
            Additional notes{" "}
            <span className="font-normal text-gray-400">(optional)</span>
          </label>
          <p className="mt-0.5 text-xs text-gray-500">
            Include any specific requirements, your state&apos;s standard DPA
            template, or questions.
          </p>
          <textarea
            id="dpa-message"
            rows={4}
            aria-describedby={errors.message ? "dpa-message-error" : undefined}
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
            {...register("message")}
          />
          {errors.message && (
            <p id="dpa-message-error" role="alert" className="mt-1 text-xs text-red-600">
              {errors.message.message}
            </p>
          )}
        </div>

        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-md bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isSubmitting ? "Submitting…" : "Request a DPA"}
        </button>
      </form>
    </div>
  );
}
