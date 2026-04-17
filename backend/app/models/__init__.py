"""SQLAlchemy ORM models package.

Import all models here so that Alembic's autogenerate can detect every
mapped table from a single import point::

    from app.models import base  # noqa: F401 — populates Base.metadata

and so application code can import individual models cleanly::

    from app.models.contact import ContactInquiry
    from app.models.dpa_request import DpaRequest
"""

from app.models import contact as contact  # noqa: F401 — registers mapped class
from app.models import dpa_request as dpa_request  # noqa: F401 — registers mapped class

__all__ = ["contact", "dpa_request"]
