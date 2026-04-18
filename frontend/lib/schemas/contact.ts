import { z } from "zod";

/**
 * Zod schema for the school/district inquiry form on the pricing page.
 * Validated client-side before submission to provide immediate feedback.
 * The backend performs its own independent validation.
 */
export const contactInquirySchema = z.object({
  name: z.string().min(1, "Name is required").max(200, "Name is too long"),
  email: z
    .string()
    .min(1, "Email is required")
    .email("Enter a valid email address"),
  school_name: z
    .string()
    .min(1, "School name is required")
    .max(300, "School name is too long"),
  district: z.string().max(300, "District name is too long").optional(),
  estimated_teachers: z
    .number({ error: "Enter a number" })
    .int("Must be a whole number")
    .min(1, "Must be at least 1")
    .max(100_000, "Value is too large")
    .optional(),
  message: z.string().max(5000, "Message is too long").optional(),
});

export type ContactInquiryFormValues = z.infer<typeof contactInquirySchema>;
