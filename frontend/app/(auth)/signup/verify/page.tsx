"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { resendVerification } from "@/lib/api/auth";

/**
 * Inner component that reads the `email` query param via useSearchParams.
 * Must be inside a <Suspense> boundary (Next.js 15 requirement).
 */
function VerifyContent() {
  const searchParams = useSearchParams();
  const emailParam = searchParams.get("email") ?? "";
  // Allow the user to type their email when it isn't pre-filled via URL.
  const [emailInput, setEmailInput] = useState(emailParam);
  const [resendStatus, setResendStatus] = useState<
    "idle" | "pending" | "sent" | "error"
  >("idle");

  const handleResend = async () => {
    if (resendStatus === "pending" || !emailInput.trim()) return;
    setResendStatus("pending");
    try {
      await resendVerification(emailInput.trim());
      setResendStatus("sent");
    } catch {
      setResendStatus("error");
    }
  };

  return (
    <div className="space-y-4 text-center">
      {/* Icon placeholder */}
      <div
        aria-hidden="true"
        className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-blue-50 text-3xl"
      >
        ✉️
      </div>

      <h1 className="text-2xl font-bold text-gray-900">Check your email</h1>

      <p className="text-sm text-gray-600">
        {emailParam ? (
          <>
            We sent a verification link to{" "}
            <strong className="font-medium text-gray-800">{emailParam}</strong>.
            Click the link in that email to verify your account.
          </>
        ) : (
          "Enter your email address below to resend the verification link."
        )}
      </p>

      <p className="text-sm text-gray-500">
        The link expires in 24 hours.
      </p>

      {/* Resend section */}
      <div className="pt-2 space-y-3">
        {resendStatus === "sent" ? (
          <p className="text-sm font-medium text-green-700" role="status">
            Verification email resent — please check your inbox.
          </p>
        ) : resendStatus === "error" ? (
          <p className="text-sm text-red-600" role="alert">
            Could not resend at this time. Please try again later.
          </p>
        ) : (
          <>
            {!emailParam && (
              <div className="text-left">
                <label
                  htmlFor="resend-email"
                  className="block text-sm font-medium text-gray-700"
                >
                  Email address
                </label>
                <input
                  id="resend-email"
                  type="email"
                  value={emailInput}
                  onChange={(e) => setEmailInput(e.target.value)}
                  placeholder="teacher@school.edu"
                  className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                  autoComplete="email"
                />
              </div>
            )}
            <p className="text-sm text-gray-600">
              Didn&apos;t receive the email?{" "}
              <button
                type="button"
                onClick={handleResend}
                disabled={resendStatus === "pending" || !emailInput.trim()}
                className="font-medium text-blue-600 hover:text-blue-700 focus:outline-none focus:underline disabled:opacity-50"
                aria-label="Resend verification email"
              >
                {resendStatus === "pending" ? "Sending…" : "Resend it"}
              </button>
            </p>
          </>
        )}
      </div>

      <p className="pt-2 text-sm text-gray-500">
        Wrong email?{" "}
        <Link
          href="/signup"
          className="font-medium text-blue-600 hover:text-blue-700"
        >
          Start over
        </Link>
      </p>
    </div>
  );
}

/**
 * /signup/verify — "Check your email" holding page.
 *
 * Shown immediately after a successful sign-up (with `?email=` set), or
 * reached directly from an expired-token error page (without `?email=`).
 * When no email param is present, an email input is rendered so the user can
 * request a fresh verification link without starting over.
 *
 * A resend button is provided (rate-limited server-side to 3/hour per email).
 */
export default function SignupVerifyPage() {
  return (
    <div className="w-full max-w-md rounded-lg bg-white p-8 shadow-md">
      <Suspense
        fallback={<div className="h-48 animate-pulse rounded-md bg-gray-100" />}
      >
        <VerifyContent />
      </Suspense>
    </div>
  );
}
