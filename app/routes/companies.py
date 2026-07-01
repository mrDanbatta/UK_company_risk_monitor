"""JSON API for triggering and retrieving company risk analyses."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.orchestrator import AgentDidNotSubmitReportError
from app.connectors.companies_house import CompanyNotFoundError, RateLimitError
from app.db import get_session
from app.services.analysis import perform_analysis

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.post("/{company_number}/analyze")
async def analyze_company(
    company_number: str,
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        report = await perform_analysis(session, company_number)
    except CompanyNotFoundError as e:
        raise HTTPException(
            status_code=404, detail=f"No company found for number {company_number!r}"
        ) from e
    except RateLimitError as e:
        raise HTTPException(
            status_code=429,
            detail=f"Companies House rate limit hit, retry after {e.retry_after}s",
        ) from e
    except AgentDidNotSubmitReportError as e:
        raise HTTPException(
            status_code=502,
            detail="Analysis did not complete — the agent did not submit a report",
        ) from e

    return {
        "id": report.id,
        "company_number": report.company_number,
        "overall_score": report.overall_score,
        "category_breakdown": report.category_breakdown,
        "findings": report.findings,
        "confidence": report.confidence,
        "created_at": report.created_at.isoformat(),
    }