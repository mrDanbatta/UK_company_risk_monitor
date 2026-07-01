from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

# Use JSONB on Postgres, plain JSON elsewhere (e.g. SQLite in local dev) —
# same column definition works against both without special-casing queries.
JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class Company(Base):
    """Cached raw responses from Companies House for one company number.

    Storing the raw payloads (not just derived fields) means re-scoring or
    re-prompting the agent later doesn't require hitting the API again.
    """

    __tablename__ = "companies"

    company_number: Mapped[str] = mapped_column(String(16), primary_key=True)

    raw_profile: Mapped[dict] = mapped_column(JSONVariant, nullable=False)
    raw_officers: Mapped[list] = mapped_column(JSONVariant, default=list)
    raw_psc: Mapped[list] = mapped_column(JSONVariant, default=list)
    raw_filing_history: Mapped[list] = mapped_column(JSONVariant, default=list)
    raw_insolvency: Mapped[dict | None] = mapped_column(JSONVariant, nullable=True)
    raw_charges: Mapped[list] = mapped_column(JSONVariant, default=list)

    last_fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )