from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.companies_house import CompaniesHouseClient
from app.models.company import Company

DEFAULT_MAX_AGE = timedelta(hours=24)


async def get_or_refresh_company(
    session: AsyncSession,
    ch_client: CompaniesHouseClient,
    company_number: str,
    max_age: timedelta = DEFAULT_MAX_AGE,
) -> Company:
    """Return cached company data if it's fresh enough, otherwise pull a
    full fresh set from Companies House and upsert it.
    """
    company = await session.get(Company, company_number)

    if company is not None:
        is_fresh = datetime.now(UTC) - company.last_fetched_at.replace(tzinfo=UTC) <= max_age
        if is_fresh:
            return company

    profile = await ch_client.get_company_profile(company_number)
    officers = await ch_client.get_officers(company_number)
    psc = await ch_client.get_psc(company_number)
    filing_history = await ch_client.get_filing_history(company_number)
    insolvency = await ch_client.get_insolvency(company_number)
    charges = await ch_client.get_charges(company_number)

    if company is None:
        company = Company(company_number=company_number)
        session.add(company)

    company.raw_profile = profile
    company.raw_officers = officers
    company.raw_psc = psc
    company.raw_filing_history = filing_history
    company.raw_insolvency = insolvency
    company.raw_charges = charges

    await session.commit()
    await session.refresh(company)
    return company


async def list_cached_companies(session: AsyncSession) -> list[Company]:
    result = await session.execute(select(Company).order_by(Company.last_fetched_at.desc()))
    return list(result.scalars().all())