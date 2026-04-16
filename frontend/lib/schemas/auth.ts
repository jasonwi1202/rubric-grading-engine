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
