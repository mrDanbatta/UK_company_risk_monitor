from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class RiskReport(Base):
    """One synthesized risk report for a company, produced by the agent.

    findings/citations are stored as JSON so the dashboard can render them
    directly without re-parsing agent output.
    """

    __tablename__ = "risk_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_number: Mapped[str] = mapped_column(
        String(16), ForeignKey("companies.company_number"), index=True
    )

    overall_score: Mapped[int] = mapped_column(Integer)  # 0-100
    category_breakdown: Mapped[dict] = mapped_column(JSONVariant)
    # e.g. {"financial": 62, "compliance": 40, "media": 20}

    findings: Mapped[list] = mapped_column(JSONVariant)
    # e.g. [{"category": "financial", "summary": "...", "citation": "..."}]

    confidence: Mapped[float] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )