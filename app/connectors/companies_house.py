"""Async client for the Companies House public data API.

Docs: https://developer-specs.company-information.service.gov.uk/

Auth: HTTP Basic, API key as the username, empty password.
Base URL: https://api.company-information.service.gov.uk
"""

from __future__ import annotations

import httpx

BASE_URL = "https://api.company-information.service.gov.uk"


class CompaniesHouseError(Exception):
    """Base error for Companies House connector failures."""


class CompanyNotFoundError(CompaniesHouseError):
    """Raised when a company number does not exist."""

    def __init__(self, company_number: str) -> None:
        self.company_number = company_number
        super().__init__(f"No company found for number {company_number!r}")


class RateLimitError(CompaniesHouseError):
    """Raised when Companies House returns 429. Carries retry_after if present."""

    def __init__(self, retry_after: int | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(
            f"Companies House rate limit hit"
            + (f", retry after {retry_after}s" if retry_after else "")
        )


class CompaniesHouseClient:
    """Thin async wrapper around the Companies House REST API.

    Usage:
        async with CompaniesHouseClient(api_key="...") as ch:
            profile = await ch.get_company_profile("00000006")
    """

    def __init__(self, api_key: str, timeout: float = 10.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            auth=httpx.BasicAuth(api_key, ""),
            timeout=timeout,
        )

    async def __aenter__(self) -> "CompaniesHouseClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str) -> dict | None:
        """Internal GET with shared error handling.

        Returns None on 404 (caller decides whether that means "not found"
        or "no data of this type exists", since Companies House overloads
        404 for both cases depending on endpoint).
        """
        response = await self._client.get(path)

        if response.status_code == 404:
            return None

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimitError(retry_after=int(retry_after) if retry_after else None)

        response.raise_for_status()
        return response.json()

    async def get_company_profile(self, company_number: str) -> dict:
        """Core company profile: name, status, incorporation date, SIC codes,
        registered office, accounts/confirmation statement due dates.

        Raises CompanyNotFoundError if the number doesn't exist — this is
        the primary lookup, so a 404 here is a real error, not "no data".
        """
        data = await self._get(f"/company/{company_number}")
        if data is None:
            raise CompanyNotFoundError(company_number)
        return data

    async def get_officers(self, company_number: str) -> list[dict]:
        """Current and resigned officers. Empty list if none on record."""
        data = await self._get(f"/company/{company_number}/officers")
        if data is None:
            return []
        return data.get("items", [])

    async def get_psc(self, company_number: str) -> list[dict]:
        """Persons with significant control. Empty list if none registered
        (which is itself a risk signal worth flagging upstream, not an error
        here — a dissolved shell or a company that hasn't filed PSC info
        both come back this way)."""
        data = await self._get(f"/company/{company_number}/persons-with-significant-control")
        if data is None:
            return []
        return data.get("items", [])

    async def get_filing_history(self, company_number: str, items_per_page: int = 100) -> list[dict]:
        """Filing history — used to detect overdue accounts, charges filed,
        and filing cadence."""
        data = await self._get(
            f"/company/{company_number}/filing-history?items_per_page={items_per_page}"
        )
        if data is None:
            return []
        return data.get("items", [])

    async def get_insolvency(self, company_number: str) -> dict | None:
        """Insolvency practitioner cases, if any.

        Companies House returns 404 when a company has NO insolvency
        history — that's the expected, good-news case, so we return None
        rather than raising.
        """
        return await self._get(f"/company/{company_number}/insolvency")

    async def get_charges(self, company_number: str) -> list[dict]:
        """Registered charges (mortgages/debentures) — a financial risk
        signal, especially multiple charges or charges marked unsatisfied."""
        data = await self._get(f"/company/{company_number}/charges")
        if data is None:
            return []
        return data.get("items", [])