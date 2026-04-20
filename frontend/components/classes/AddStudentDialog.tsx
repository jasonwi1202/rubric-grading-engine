"use client";

/**
 * AddStudentDialog — modal for manually enrolling a student in a class.
 *
 * Uses react-hook-form + Zod for validation.  On success the parent is
 * notified via the `onAdded` callback so it can invalidate the roster
 * React Query cache.
 *
 * Security: only the student's name and an optional external ID are
 * collected here — no essay content or grade data.
 */

import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { addStudent } from "@/lib/api/classes";
import type { EnrolledStudentResponse } from "@/lib/api/classes";
import { ApiError } from "@/lib/api/errors";

// Focusable element selector for focus-trapping (matches TemplatePicker)
const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// ---------------------------------------------------------------------------
// Schema
// ---------------------------------------------------------------------------

const addStudentSchema = z.object({
  full_name: z
    .string()
    .min(1, "Student name is required")
    .max(200, "Name is too long"),
  external_id: z.string().max(100, "External ID is too long").optional(),
});

type AddStudentFormValues = z.infer<typeof addStudentSchema>;

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface AddStudentDialogProps {
  classId: string;
  open: boolean;
  onClose: () => void;
  onAdded: (enrolled: EnrolledStudentResponse) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AddStudentDialog({
  classId,
  open,
  onClose,
  onAdded,
}: AddStudentDialogProps) {
  const [serverError, setServerError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<AddStudentFormValues>({
    resolver: zodResolver(addStudentSchema),
    defaultValues: { full_name: "", external_id: "" },
  });

  // Focus management: capture previous focus, move into dialog, restore on close
  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement;
    const firstFocusable = dialogRef.current?.querySelector<HTMLElement>(FOCUSABLE);
    firstFocusable?.focus();
    return () => {
      previousFocusRef.current?.focus();
    };
  }, [open]);

  if (!open) return null;

  const handleClose = () => {
    reset();
    setServerError(null);
    onClose();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      handleClose();
      return;
    }
    if (e.key === "Tab") {
      const focusable = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [],
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
  };

  const onSubmit = async (values: AddStudentFormValues) => {
    setServerError(null);
    try {
      const enrolled = await addStudent(classId, {
        full_name: values.full_name,
        external_id: values.external_id || undefined,
      });
      reset();
      onAdded(enrolled);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setServerError("A student with this name or ID is already enrolled.");
        return;
      }
      setServerError("Failed to add student. Please try again.");
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget) handleClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-student-title"
        className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
        onKeyDown={handleKeyDown}
      >
        <h2
          id="add-student-title"
          className="mb-4 text-lg font-semibold text-gray-900"
        >
          Add student
        </h2>

        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          {/* Full name */}
          <div>
            <label
              htmlFor="full_name"
              className="block text-sm font-medium text-gray-700"
            >
              Full name <span aria-hidden="true">*</span>
            </label>
            <input
              id="full_name"
              type="text"
              autoComplete="off"
              placeholder="e.g. Alex Johnson"
              disabled={isSubmitting}
              aria-describedby={errors.full_name ? "full-name-error" : undefined}
              aria-invalid={!!errors.full_name}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              {...register("full_name")}
            />
            {errors.full_name && (
              <p
                id="full-name-error"
                role="alert"
                className="mt-1 text-sm text-red-600"
              >
                {errors.full_name.message}
              </p>
            )}
          </div>

          {/* External ID (optional) */}
          <div>
            <label
              htmlFor="external_id"
              className="block text-sm font-medium text-gray-700"
            >
              External ID{" "}
              <span className="font-normal text-gray-500">(optional)</span>
            </label>
            <input
              id="external_id"
              type="text"
              autoComplete="off"
              placeholder="Student ID from your SIS"
              disabled={isSubmitting}
              aria-describedby={
                errors.external_id ? "external-id-error" : undefined
              }
              aria-invalid={!!errors.external_id}
              className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
              {...register("external_id")}
            />
            {errors.external_id && (
              <p
                id="external-id-error"
                role="alert"
                className="mt-1 text-sm text-red-600"
              >
                {errors.external_id.message}
              </p>
            )}
          </div>

          {/* Server error */}
          {serverError && (
            <p
              role="alert"
              className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700"
            >
              {serverError}
            </p>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={handleClose}
              disabled={isSubmitting}
              className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50"
            >
              {isSubmitting ? "Adding…" : "Add student"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
