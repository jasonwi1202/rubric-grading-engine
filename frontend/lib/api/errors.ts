/**
 * Shared API error types used by both the API client and the auth session
 * helpers. Kept in a standalone module to avoid circular imports between
 * lib/api/client.ts and lib/auth/session.ts.
 */

export interface ApiErrorBody {
  code: string;
  message: string;
  field?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly field?: string;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.field = body.field;
  }
}
