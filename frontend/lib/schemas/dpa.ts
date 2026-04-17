import { z } from "zod";

/**
 * Zod schema for the DPA request form on /legal/dpa.
 * Validated client-side before submission to provide immediate feedback.
 * The backend performs its own independent Pydantic validation.
 *
 * Only school administrator contact info is collected — no student PII.
 */
export const dpaRequestSchema = z.object({
  name: z.string().min(1, "Name is required").max(200, "Name is too long"),
  email: z
    .string()
    .min(1, "Email is required")
    .email("Enter a valid email address"),
  school_name: z
    .string()
    .min(1, "School or district name is required")
    .max(300, "School name is too long"),
  district: z.string().max(300, "District name is too long").optional(),
  message: z
    .string()
    .max(2000, "Message is too long")
    .optional(),
});

export type DpaRequestFormValues = z.infer<typeof dpaRequestSchema>;
