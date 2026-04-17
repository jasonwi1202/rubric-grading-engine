"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import Link from "next/link";
import { verifyEmail } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/errors";

type VerifyState = "pending" | "success" | "error";

/**
 * Inner component that reads the `token` query param via useSearchParams.
 * Must be inside a <Suspense> boundary (Next.js 15 requirement).
 */
function VerifyContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const token = searchParams.get("token") ?? "";
  const [state, setState] = useState<VerifyState>("pending");
  const [errorMessage, setErrorMessage] = useState<string>("");

  useEffect(() => {
    if (!token) {
      setState("error");
      setErrorMessage("No verification token found. Please use the link from your email.");
      return;
    }

    let cancelled = false;
    let redirectTimer: ReturnType<typeof setTimeout> | undefined;

    verifyEmail(token)
      .then(() => {
        if (!cancelled) {
          setState("success");
          // Redirect to login after a short delay so the user can see the message.
          redirectTimer = setTimeout(() => {
            router.replace("/login?verified=1");
          }, 2500);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && (err.status === 422 || err.status === 400)) {
          setErrorMessage(
            "This verification link is invalid or has expired. Please request a new one.",
          );
        } else {
          setErrorMessage("Verification failed. Please try again.");
        }
        setState("error");
      });

    return () => {
      cancelled = true;
      clearTimeout(redirectTimer);
    };
  }, [token, router]);

  if (state === "pending") {
    return (
      <div className="space-y-4 text-center">
        <div
          className="mx-auto h-12 w-12 animate-spin rounded-full border-4 border-blue-200 border-t-blue-600"
          aria-label="Verifying…"
          role="status"
        />
        <p className="text-sm text-gray-600">Verifying your email…</p>
      </div>
    );
  }

  if (state === "success") {
    return (
      <div className="space-y-4 text-center">
        <div
          aria-hidden="true"
          className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-green-50 text-3xl"
        >
          ✅
        </div>
        <h1 className="text-2xl font-bold text-gray-900">Email verified!</h1>
        <p className="text-sm text-gray-600">
          Your account is now active. Redirecting you to sign in…
        </p>
        <p className="text-sm text-gray-500">
          Not redirecting?{" "}
          <Link
            href="/login"
            className="font-medium text-blue-600 hover:text-blue-700"
          >
            Click here to sign in
          </Link>
        </p>
      </div>
    );
  }

  // error state
  return (
    <div className="space-y-4 text-center">
      <div
        aria-hidden="true"
        className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-red-50 text-3xl"
      >
        ❌
      </div>
      <h1 className="text-2xl font-bold text-gray-900">Verification failed</h1>
      <p className="text-sm text-gray-600" role="alert">
        {errorMessage}
      </p>
      <div className="pt-2 space-y-2">
        <p className="text-sm text-gray-600">
          <Link
            href="/signup/verify"
            className="font-medium text-blue-600 hover:text-blue-700"
          >
            Resend the verification email
          </Link>
        </p>
        <p className="text-sm text-gray-500">
          Need help?{" "}
          <Link href="/contact" className="font-medium text-blue-600 hover:text-blue-700">
            Contact support
          </Link>
        </p>
      </div>
    </div>
  );
}

/**
 * /verify — email verification landing page.
 *
 * Reads the `?token=` query parameter set by the verification email link,
 * calls the backend verify endpoint, and shows success or an error with a
 * resend option. On success the user is redirected to /login.
 *
 * Note: this file lives at `app/(auth)/verify/page.tsx`. The `(auth)` route
 * group is not included in the URL, so the public route is `/verify`, not
 * `/auth/verify`. Backend-generated verification links must therefore target
 * `/verify`.
 *
 * Security notes:
 * - The token is consumed server-side (single-use, 24 h TTL).
 * - On expiry a clear error with a resend link is shown.
 * - No student PII is processed here.
 */
export default function AuthVerifyPage() {
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
