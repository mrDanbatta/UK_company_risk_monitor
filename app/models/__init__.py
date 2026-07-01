from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import models so their tables register on Base.metadata —
# Alembic's autogenerate needs this to see every table.
from app.models.company import Company  # noqa: E402, F401
from app.models.report import RiskReport  # noqa: E402, F401