/**
 * Contact inquiry API calls.
 * All requests go through the typed fetch wrappers in lib/api/client.ts.
 */
import { apiPost } from "@/lib/api/client";
import type { ContactInquiryFormValues } from "@/lib/schemas/contact";

export interface ContactInquiryResponse {
  id: string;
  created_at: string;
}

/**
 * POST /api/v1/contact/inquiry
 *
 * Submits a school/district purchase inquiry.  Returns the created record
 * metadata (id, created_at) on success.
 */
export function submitContactInquiry(
  payload: ContactInquiryFormValues,
): Promise<ContactInquiryResponse> {
  return apiPost<ContactInquiryResponse>("/api/v1/contact/inquiry", payload);
}
