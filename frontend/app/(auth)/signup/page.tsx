"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { signup } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/errors";
import { signupSchema, type SignupFormValues } from "@/lib/schemas/auth";

/**
 * Teacher sign-up page — creates a new unverified account.
 *
 * On success the backend enqueues a verification email and the user is
 * redirected to /signup/verify (the "check your email" holding page).
 *
 * Security notes:
 * - No student PII is collected here.
 * - Password is sent over HTTPS only and is never logged or stored
 *   in browser storage.
 * - The sign-up endpoint is rate-limited server-side (5/hour per IP).
 */
export default function SignupPage() {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<SignupFormValues>({
    resolver: zodResolver(signupSchema),
  });

  const onSubmit = async (values: SignupFormValues) => {
    setServerError(null);
    try {
      await signup(values);
      // Redirect to the email-verification holding page.
      router.replace(`/signup/verify?email=${encodeURIComponent(values.email)}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setServerError(
          "An account with this email already exists. Please sign in instead.",
        );
      } else if (err instanceof ApiError && err.status === 429) {
        setServerError(
          "Too many sign-up attempts. Please try again in an hour.",
        );
      } else {
        setServerError("Sign-up failed. Please try again.");
      }
    }
  };

  return (
    <div className="w-full max-w-md rounded-lg bg-white p-8 shadow-md">
      <h1 className="mb-2 text-2xl font-bold text-gray-900">
        Create your account
      </h1>
      <p className="mb-6 text-sm text-gray-600">
        Start your free trial — no credit card required.
      </p>

      <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
        {/* First name / Last name side-by-side */}
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label
              htmlFor="first_name"
              className="block text-sm font-medium text-gray-700"
            >
              First name
            </label>
            <input
              id="first_name"
              type="text"
              autoComplete="given-name"
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              aria-describedby={errors.first_name ? "first-name-error" : undefined}
              aria-invalid={!!errors.first_name}
              disabled={isSubmitting}
              {...register("first_name")}
            />
            {errors.first_name && (
              <p
                id="first-name-error"
                className="mt-1 text-sm text-red-600"
                role="alert"
              >
                {errors.first_name.message}
              </p>
            )}
          </div>

          <div>
            <label
              htmlFor="last_name"
              className="block text-sm font-medium text-gray-700"
            >
              Last name
            </label>
            <input
              id="last_name"
              type="text"
              autoComplete="family-name"
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              aria-describedby={errors.last_name ? "last-name-error" : undefined}
              aria-invalid={!!errors.last_name}
              disabled={isSubmitting}
              {...register("last_name")}
            />
            {errors.last_name && (
              <p
                id="last-name-error"
                className="mt-1 text-sm text-red-600"
                role="alert"
              >
                {errors.last_name.message}
              </p>
            )}
          </div>
        </div>

        {/* Email */}
        <div>
          <label
            htmlFor="email"
            className="block text-sm font-medium text-gray-700"
          >
            Work email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
            aria-describedby={errors.email ? "email-error" : undefined}
            aria-invalid={!!errors.email}
            disabled={isSubmitting}
            {...register("email")}
          />
          {errors.email && (
            <p id="email-error" className="mt-1 text-sm text-red-600" role="alert">
              {errors.email.message}
            </p>
          )}
        </div>

        {/* School name */}
        <div>
          <label
            htmlFor="school_name"
            className="block text-sm font-medium text-gray-700"
          >
            School or organisation name
          </label>
          <input
            id="school_name"
            type="text"
            autoComplete="organization"
            className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
            aria-describedby={errors.school_name ? "school-name-error" : undefined}
            aria-invalid={!!errors.school_name}
            disabled={isSubmitting}
            {...register("school_name")}
          />
          {errors.school_name && (
            <p
              id="school-name-error"
              className="mt-1 text-sm text-red-600"
              role="alert"
            >
              {errors.school_name.message}
            </p>
          )}
        </div>

        {/* Password */}
        <div>
          <label
            htmlFor="password"
            className="block text-sm font-medium text-gray-700"
          >
            Password
          </label>
          <div className="relative mt-1">
            <input
              id="password"
              type={showPassword ? "text" : "password"}
              autoComplete="new-password"
              className="block w-full rounded-md border border-gray-300 px-3 py-2 pr-10 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              aria-describedby={errors.password ? "password-error" : undefined}
              aria-invalid={!!errors.password}
              disabled={isSubmitting}
              {...register("password")}
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              className="absolute inset-y-0 right-0 flex items-center px-3 text-gray-500 hover:text-gray-700 focus:outline-none"
              aria-label={showPassword ? "Hide password" : "Show password"}
            >
              {showPassword ? "Hide" : "Show"}
            </button>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            At least 8 characters, with at least one letter and one digit.
          </p>
          {errors.password && (
            <p
              id="password-error"
              className="mt-1 text-sm text-red-600"
              role="alert"
            >
              {errors.password.message}
            </p>
          )}
        </div>

        {/* Server-side error */}
        {serverError && (
          <p
            className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700"
            role="alert"
          >
            {serverError}
          </p>
        )}

        {/* Submit */}
        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
        >
          {isSubmitting ? "Creating account…" : "Create account"}
        </button>
      </form>

      {/* Footer links */}
      <p className="mt-6 text-center text-sm text-gray-600">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-blue-600 hover:text-blue-700">
          Sign in
        </Link>
      </p>
    </div>
  );
}
