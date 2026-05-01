"""Domain exceptions for the Rubric Grading Engine.

Services raise these typed exceptions; routers (or global exception handlers)
catch them and convert them to structured HTTP responses.  Services must never
raise ``HTTPException`` or reference HTTP status codes directly.
"""


class RubricGradingError(Exception):
    """Base class for all domain exceptions."""

    code: str = "INTERNAL_ERROR"


class NotFoundError(RubricGradingError):
    """Resource does not exist.

    Use this only when the requested resource truly does not exist. Do not use
    it for authorization or tenant-isolation failures; authenticated access
    denials, including cross-tenant access attempts, must raise
    ``ForbiddenError`` instead.
    """

    code = "NOT_FOUND"


class UnauthorizedError(RubricGradingError):
    """Request is missing valid authentication credentials.

    Use this when no credentials are supplied or the supplied token is
    invalid/expired.  Reserve ``ForbiddenError`` for authenticated requests
    that are denied due to insufficient privileges or cross-tenant access.
    """

    code = "UNAUTHORIZED"


class RefreshTokenInvalidError(UnauthorizedError):
    """Refresh token is missing, expired, invalid, or already consumed."""

    code = "REFRESH_TOKEN_INVALID"


class ForbiddenError(RubricGradingError):
    """Authenticated teacher does not have access to this resource.

    This includes cross-tenant access attempts where the resource exists but
    does not belong to the authenticated teacher.
    """

    code = "FORBIDDEN"


class ConflictError(RubricGradingError):
    """Operation conflicts with current resource state."""

    code = "CONFLICT"


class ValidationError(RubricGradingError):
    """Input failed domain-level validation (not Pydantic schema validation)."""

    code = "VALIDATION_ERROR"

    def __init__(self, message: str, field: str | None = None) -> None:
        super().__init__(message)
        self.field: str | None = field


class LLMError(RubricGradingError):
    """LLM call failed or returned an unparseable response."""

    code = "LLM_UNAVAILABLE"


class LLMParseError(LLMError):
    """LLM response failed schema validation after retries."""

    code = "LLM_PARSE_ERROR"


# ---------------------------------------------------------------------------
# ConflictError subclasses
# ---------------------------------------------------------------------------


class GradeLockedError(ConflictError):
    code = "GRADE_LOCKED"


class GradingInProgressError(ConflictError):
    code = "GRADING_IN_PROGRESS"


class AssignmentNotGradeableError(ConflictError):
    code = "ASSIGNMENT_NOT_GRADEABLE"


class RubricInUseError(ConflictError):
    code = "RUBRIC_IN_USE"


# ---------------------------------------------------------------------------
# RateLimitError
# ---------------------------------------------------------------------------


class RateLimitError(RubricGradingError):
    """Caller has exceeded a rate limit (e.g. inquiry submissions per IP)."""

    code = "RATE_LIMITED"


# ---------------------------------------------------------------------------
# ValidationError subclasses
# ---------------------------------------------------------------------------


class InvalidStateTransitionError(ValidationError):
    code = "INVALID_STATE_TRANSITION"


class RubricWeightInvalidError(ValidationError):
    code = "RUBRIC_WEIGHT_INVALID"


class FileTooLargeError(ValidationError):
    code = "FILE_TOO_LARGE"


class FileTypeNotAllowedError(ValidationError):
    code = "FILE_TYPE_NOT_ALLOWED"


# ---------------------------------------------------------------------------
# Regrade request ConflictError subclasses
# ---------------------------------------------------------------------------


class RegradeWindowClosedError(ConflictError):
    """Regrade request submission window has passed for this grade."""

    code = "REGRADE_WINDOW_CLOSED"


class RegradeRequestLimitReachedError(ConflictError):
    """Per-grade regrade request limit has been reached."""

    code = "REGRADE_REQUEST_LIMIT_REACHED"


# ---------------------------------------------------------------------------
# Resubmission ConflictError subclasses
# ---------------------------------------------------------------------------


class ResubmissionDisabledError(ConflictError):
    """Resubmission is not enabled for this assignment."""

    code = "RESUBMISSION_DISABLED"


class ResubmissionLimitReachedError(ConflictError):
    """Per-assignment resubmission limit has been reached."""

    code = "RESUBMISSION_LIMIT_REACHED"
