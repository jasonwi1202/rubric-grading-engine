import { z } from "zod";

/**
 * Zod schema for the login form.
 * Validated client-side before submission to provide immediate feedback.
 */
export const loginSchema = z.object({
  email: z
    .string()
    .min(1, "Email is required")
    .email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});

export type LoginFormValues = z.infer<typeof loginSchema>;

/**
 * Zod schema for the teacher sign-up form.
 * Validated client-side before submission.
 */
export const signupSchema = z.object({
  first_name: z
    .string()
    .min(1, "First name is required")
    .max(100, "First name must be at most 100 characters"),
  last_name: z
    .string()
    .min(1, "Last name is required")
    .max(100, "Last name must be at most 100 characters"),
  email: z
    .string()
    .min(1, "Email is required")
    .email("Enter a valid email address"),
  password: z
    .string()
    .min(8, "Password must be at least 8 characters")
    .max(128, "Password must be at most 128 characters")
    .refine(
      (val) => /[a-zA-Z]/.test(val),
      "Password must contain at least one letter",
    )
    .refine(
      (val) => /[0-9]/.test(val),
      "Password must contain at least one digit",
    ),
  school_name: z
    .string()
    .min(1, "School name is required")
    .max(300, "School name must be at most 300 characters"),
});

export type SignupFormValues = z.infer<typeof signupSchema>;
