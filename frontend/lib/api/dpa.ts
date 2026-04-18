/**
 * DPA request API calls.
 * All requests go through the typed fetch wrappers in lib/api/client.ts.
 */
import { apiPost } from "@/lib/api/client";
import type { DpaRequestFormValues } from "@/lib/schemas/dpa";

export interface DpaRequestResponse {
  id: string;
  created_at: string;
}

/**
 * POST /contact/dpa-request
 *
 * Submits a DPA request from a school or district administrator.
 * Returns the created record metadata (id, created_at) on success.
 * No student PII is collected.
 */
export function submitDpaRequest(
  payload: DpaRequestFormValues,
): Promise<DpaRequestResponse> {
  return apiPost<DpaRequestResponse>("/contact/dpa-request", payload);
}
