"""Ties together caching, the agent, and persistence into one analysis run.

Both the JSON API (routes/companies.py) and the HTML dashboard
(routes/dashboard.py) call this same function — they only differ in how
they render the result, not in how they produce it.
"""

from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.orchestrator import run_risk_analysis
from app.config import get_settings
from app.connectors.companies_house import CompaniesHouseClient
from app.models.report import RiskReport
from app.services.cache import get_or_refresh_company


async def perform_analysis(session: AsyncSession, company_number: str) -> RiskReport:
    settings = get_settings()

    async with CompaniesHouseClient(api_key=settings.companies_house_api_key) as ch_client:
        # Warm the cache so repeated requests for the same company within
        # the freshness window don't hit Companies House again.
        #
        # Known limitation: the agent's own tool calls (Stage 4) still call
        # ch_client live rather than reading this cached row, so one
        # analysis run currently means up to 6 warm-up calls plus up to 6
        # more agent calls. Worth revisiting in Phase 2 -- refactor
        # agent/tools.py to read from Company.raw_* fields instead of
        # re-fetching live.
        await get_or_refresh_company(session, ch_client, company_number)

        anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        agent_report = await run_risk_analysis(anthropic_client, ch_client, company_number)

    report = RiskReport(
        company_number=company_number,
        overall_score=agent_report.overall_score,
        category_breakdown=agent_report.category_breakdown,
        findings=agent_report.findings,
        confidence=agent_report.confidence,
    )
    session.add(report)
    await session.commit()
    await session.refresh(report)
    return report