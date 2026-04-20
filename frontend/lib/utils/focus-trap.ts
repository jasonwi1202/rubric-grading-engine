/**
 * useFocusTrap — reusable focus-trap hook for modal dialogs.
 *
 * Captures focus on open, traps Tab/Shift+Tab within the dialog, handles
 * Escape-to-close, and restores focus to the previous element on close.
 *
 * Usage:
 *   const { dialogRef, handleKeyDown } = useFocusTrap({ open, onClose });
 *   <div ref={dialogRef} onKeyDown={handleKeyDown} role="dialog" ...>
 */

import { useEffect, useRef } from "react";

/** Selector for all keyboard-focusable elements inside a container. */
export const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

interface UseFocusTrapOptions {
  /** Whether the dialog is currently mounted/visible. */
  open: boolean;
  /** Called when the user presses Escape. */
  onClose: () => void;
}

interface UseFocusTrapResult {
  /** Attach to the dialog panel element (the inner white box, not the backdrop). */
  dialogRef: React.RefObject<HTMLDivElement | null>;
  /** Attach to the dialog panel's onKeyDown prop. */
  handleKeyDown: (e: React.KeyboardEvent<HTMLDivElement>) => void;
}

export function useFocusTrap({
  open,
  onClose,
}: UseFocusTrapOptions): UseFocusTrapResult {
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  // On open: capture the previously focused element and move focus into the dialog.
  // If no focusable child exists (e.g., pending state), focus the panel itself so
  // Escape/Tab handling continues to work.
  // On unmount/close: restore focus to the captured element.
  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement;
    const firstFocusable = dialogRef.current?.querySelector<HTMLElement>(FOCUSABLE);
    if (firstFocusable) {
      firstFocusable.focus();
    } else {
      dialogRef.current?.focus();
    }
    return () => {
      previousFocusRef.current?.focus();
    };
  }, [open]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      onClose();
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

  return { dialogRef, handleKeyDown };
}
