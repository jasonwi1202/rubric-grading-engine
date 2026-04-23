"use client";

/**
 * RemoveStudentDialog — confirmation dialog before soft-removing a student
 * from the class roster.
 *
 * The student's grade history is preserved; only the enrollment record is
 * soft-deleted.
 */

import { useFocusTrap } from "@/lib/utils/focus-trap";

interface RemoveStudentDialogProps {
  studentName: string;
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  isPending?: boolean;
}

export function RemoveStudentDialog({
  studentName,
  open,
  onClose,
  onConfirm,
  isPending = false,
}: RemoveStudentDialogProps) {
  const { dialogRef, handleKeyDown } = useFocusTrap({ open, onClose });

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="remove-student-title"
        aria-describedby="remove-student-desc"
        className="w-full max-w-sm rounded-lg bg-white p-6 shadow-xl"
        onKeyDown={handleKeyDown}
        tabIndex={-1}
      >
        <h2
          id="remove-student-title"
          className="mb-2 text-lg font-semibold text-gray-900"
        >
          Remove student?
        </h2>
        <p id="remove-student-desc" className="mb-6 text-sm text-gray-600">
          Remove <strong>{studentName}</strong> from this class? Their grade
          history will be preserved.
        </p>

        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={isPending}
            className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isPending}
            className="rounded-md bg-red-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:opacity-50"
          >
            {isPending ? "Removing…" : "Remove student"}
          </button>
        </div>
      </div>
    </div>
  );
}
