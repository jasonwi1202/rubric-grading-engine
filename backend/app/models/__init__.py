"""SQLAlchemy ORM models package.

Import all models here so that Alembic's autogenerate can detect every
mapped table from a single import point::

    from app.models import base  # noqa: F401 ΓÇö populates Base.metadata

and so application code can import individual models cleanly::

    from app.models.contact import ContactInquiry
    from app.models.dpa_request import DpaRequest
    from app.models.user import User
    from app.models.audit_log import AuditLog
    from app.models.class_ import Class
    from app.models.student import Student
    from app.models.class_enrollment import ClassEnrollment
    from app.models.rubric import Rubric, RubricCriterion
    from app.models.assignment import Assignment
    from app.models.essay import Essay, EssayVersion
    from app.models.grade import Grade, CriterionScore
    from app.models.comment_bank import CommentBankEntry
    from app.models.integrity_report import IntegrityReport, IntegrityReportStatus
    from app.models.media_comment import MediaComment
    from app.models.regrade_request import RegradeRequest, RegradeRequestStatus
    from app.models.student_skill_profile import StudentSkillProfile
"""

from app.models import assignment as assignment  # noqa: F401 ΓÇö registers mapped class
from app.models import audit_log as audit_log  # noqa: F401 ΓÇö registers mapped class
from app.models import class_ as class_  # noqa: F401 ΓÇö registers mapped class
from app.models import class_enrollment as class_enrollment  # noqa: F401 ΓÇö registers mapped class
from app.models import comment_bank as comment_bank  # noqa: F401 ΓÇö registers mapped class
from app.models import contact as contact  # noqa: F401 ΓÇö registers mapped class
from app.models import dpa_request as dpa_request  # noqa: F401 ΓÇö registers mapped class
from app.models import essay as essay  # noqa: F401 ΓÇö registers mapped class
from app.models import grade as grade  # noqa: F401 ΓÇö registers mapped class
from app.models import integrity_report as integrity_report  # noqa: F401 ΓÇö registers mapped class
from app.models import media_comment as media_comment  # noqa: F401 — registers mapped class
from app.models import regrade_request as regrade_request  # noqa: F401 — registers mapped class
from app.models import rubric as rubric  # noqa: F401 ΓÇö registers mapped class
from app.models import student as student  # noqa: F401 ΓÇö registers mapped class
from app.models import student_skill_profile as student_skill_profile  # noqa: F401 — registers mapped class
from app.models import user as user  # noqa: F401 ΓÇö registers mapped class

__all__ = [
    "assignment",
    "audit_log",
    "class_",
    "class_enrollment",
    "comment_bank",
    "contact",
    "dpa_request",
    "essay",
    "grade",
    "integrity_report",
    "media_comment",
    "regrade_request",
    "rubric",
    "student",
    "student_skill_profile",
    "user",
]
