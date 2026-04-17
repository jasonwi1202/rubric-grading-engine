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
  const email = searchParams.get("email") ?? "";
  const [resendStatus, setResendStatus] = useState<
    "idle" | "pending" | "sent" | "error"
  >("idle");

  const handleResend = async () => {
    if (resendStatus === "pending") return;
    setResendStatus("pending");
    try {
      await resendVerification(email);
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
        We sent a verification link to{" "}
        {email ? (
          <strong className="font-medium text-gray-800">{email}</strong>
        ) : (
          "your email address"
        )}
        . Click the link in that email to verify your account.
      </p>

      <p className="text-sm text-gray-500">
        The link expires in 24 hours.
      </p>

      {/* Resend link */}
      <div className="pt-2">
        {resendStatus === "sent" ? (
          <p className="text-sm font-medium text-green-700" role="status">
            Verification email resent — please check your inbox.
          </p>
        ) : resendStatus === "error" ? (
          <p className="text-sm text-red-600" role="alert">
            Could not resend at this time. Please try again later.
          </p>
        ) : (
          <p className="text-sm text-gray-600">
            Didn&apos;t receive the email?{" "}
            <button
              type="button"
              onClick={handleResend}
              disabled={resendStatus === "pending" || !email}
              className="font-medium text-blue-600 hover:text-blue-700 focus:outline-none focus:underline disabled:opacity-50"
              aria-label="Resend verification email"
            >
              {resendStatus === "pending" ? "Sending…" : "Resend it"}
            </button>
          </p>
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
 * Shown immediately after a successful sign-up. The user should click the
 * link sent to their email to complete verification. A resend button is
 * provided (rate-limited server-side to 3/hour per email).
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
