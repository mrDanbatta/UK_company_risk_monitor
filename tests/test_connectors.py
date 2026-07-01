"""Tests for the Companies House connector.

Uses respx to intercept httpx calls — no real network access, no API key
needed to run these.
"""

import httpx
import pytest
import respx

from app.connectors.companies_house import (
    BASE_URL,
    CompaniesHouseClient,
    CompanyNotFoundError,
    RateLimitError,
)
from tests.conftest import load_fixture

COMPANY_NUMBER = "12345678"


@pytest.fixture
async def client():
    async with CompaniesHouseClient(api_key="dummy-key") as ch:
        yield ch


@respx.mock
async def test_get_company_profile_success(client):
    profile = load_fixture("companies_house_profile")
    respx.get(f"{BASE_URL}/company/{COMPANY_NUMBER}").mock(
        return_value=httpx.Response(200, json=profile)
    )

    result = await client.get_company_profile(COMPANY_NUMBER)

    assert result["company_number"] == COMPANY_NUMBER
    assert result["company_status"] == "active"
    assert result["accounts"]["overdue"] is False


@respx.mock
async def test_get_company_profile_not_found_raises(client):
    respx.get(f"{BASE_URL}/company/{COMPANY_NUMBER}").mock(
        return_value=httpx.Response(404)
    )

    with pytest.raises(CompanyNotFoundError) as exc_info:
        await client.get_company_profile(COMPANY_NUMBER)

    assert exc_info.value.company_number == COMPANY_NUMBER


@respx.mock
async def test_get_officers_success(client):
    officers = load_fixture("companies_house_officers")
    respx.get(f"{BASE_URL}/company/{COMPANY_NUMBER}/officers").mock(
        return_value=httpx.Response(200, json=officers)
    )

    result = await client.get_officers(COMPANY_NUMBER)

    assert len(result) == 2
    assert result[0]["name"] == "SMITH, Jane"
    assert result[1]["resigned_on"] == "2025-11-20"


@respx.mock
async def test_get_officers_returns_empty_list_on_404(client):
    respx.get(f"{BASE_URL}/company/{COMPANY_NUMBER}/officers").mock(
        return_value=httpx.Response(404)
    )

    result = await client.get_officers(COMPANY_NUMBER)

    assert result == []


@respx.mock
async def test_get_psc_success(client):
    psc = load_fixture("companies_house_psc")
    respx.get(
        f"{BASE_URL}/company/{COMPANY_NUMBER}/persons-with-significant-control"
    ).mock(return_value=httpx.Response(200, json=psc))

    result = await client.get_psc(COMPANY_NUMBER)

    assert len(result) == 1
    assert "ownership-of-shares-75-to-100-percent" in result[0]["natures_of_control"]


@respx.mock
async def test_get_psc_returns_empty_list_when_none_registered(client):
    respx.get(
        f"{BASE_URL}/company/{COMPANY_NUMBER}/persons-with-significant-control"
    ).mock(return_value=httpx.Response(404))

    result = await client.get_psc(COMPANY_NUMBER)

    assert result == []


@respx.mock
async def test_get_filing_history_success(client):
    filings = load_fixture("companies_house_filing_history")
    respx.get(
        f"{BASE_URL}/company/{COMPANY_NUMBER}/filing-history?items_per_page=100"
    ).mock(return_value=httpx.Response(200, json=filings))

    result = await client.get_filing_history(COMPANY_NUMBER)

    assert len(result) == 3
    assert result[2]["category"] == "mortgage"


@respx.mock
async def test_get_insolvency_returns_none_when_no_history(client):
    respx.get(f"{BASE_URL}/company/{COMPANY_NUMBER}/insolvency").mock(
        return_value=httpx.Response(404)
    )

    result = await client.get_insolvency(COMPANY_NUMBER)

    assert result is None


@respx.mock
async def test_get_insolvency_returns_data_when_present(client):
    insolvency_data = {"cases": [{"type": "administration", "dates": []}]}
    respx.get(f"{BASE_URL}/company/{COMPANY_NUMBER}/insolvency").mock(
        return_value=httpx.Response(200, json=insolvency_data)
    )

    result = await client.get_insolvency(COMPANY_NUMBER)

    assert result is not None
    assert result["cases"][0]["type"] == "administration"


@respx.mock
async def test_get_charges_success(client):
    charges = load_fixture("companies_house_charges")
    respx.get(f"{BASE_URL}/company/{COMPANY_NUMBER}/charges").mock(
        return_value=httpx.Response(200, json=charges)
    )

    result = await client.get_charges(COMPANY_NUMBER)

    assert len(result) == 1
    assert result[0]["status"] == "outstanding"


@respx.mock
async def test_rate_limit_raises_with_retry_after(client):
    respx.get(f"{BASE_URL}/company/{COMPANY_NUMBER}").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"})
    )

    with pytest.raises(RateLimitError) as exc_info:
        await client.get_company_profile(COMPANY_NUMBER)

    assert exc_info.value.retry_after == 30


@respx.mock
async def test_rate_limit_raises_without_retry_after_header(client):
    respx.get(f"{BASE_URL}/company/{COMPANY_NUMBER}").mock(
        return_value=httpx.Response(429)
    )

    with pytest.raises(RateLimitError) as exc_info:
        await client.get_company_profile(COMPANY_NUMBER)

    assert exc_info.value.retry_after is None