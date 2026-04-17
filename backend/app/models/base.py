"""Declarative base for all SQLAlchemy ORM models.

All models should inherit from ``Base``::

    from app.models.base import Base

    class MyModel(Base):
        __tablename__ = "my_models"
        ...
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models."""
