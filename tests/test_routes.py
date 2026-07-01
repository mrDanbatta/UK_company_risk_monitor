"""HTTP-layer tests for both the JSON API and the HTML dashboard.

perform_analysis (and list_cached_companies for the dashboard's search
page) are mocked entirely -- these tests check status codes, response
shape, and error mapping, not the pipeline itself (that's covered by
test_connectors.py, test_scoring.py, and test_agent.py).
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.agent.orchestrator import AgentDidNotSubmitReportError
from app.connectors.companies_house import CompanyNotFoundError, RateLimitError
from app.db import get_session
from app.main import app
from app.models.report import RiskReport

COMPANY_NUMBER = "12345678"


def make_fake_report(**overrides) -> RiskReport:
    defaults = dict(
        company_number=COMPANY_NUMBER,
        overall_score=35,
        category_breakdown={"financial": 25, "compliance": 20},
        findings=[
            {
                "category": "financial",
                "summary": "Accounts filed on time",
                "citation": "Companies House profile, accounts.overdue=false",
            }
        ],
        confidence=0.85,
    )
    defaults.update(overrides)
    report = RiskReport(**defaults)
    report.id = 1
    report.created_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
    return report


@pytest.fixture
def client():
    async def _fake_get_session():
        yield MagicMock()

    app.dependency_overrides[get_session] = _fake_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---- JSON API: /api/companies/{number}/analyze ----

def test_analyze_api_success(client):
    fake_report = make_fake_report()
    with patch("app.routes.companies.perform_analysis", new=AsyncMock(return_value=fake_report)):
        response = client.post(f"/api/companies/{COMPANY_NUMBER}/analyze")

    assert response.status_code == 200
    body = response.json()
    assert body["company_number"] == COMPANY_NUMBER
    assert body["overall_score"] == 35
    assert body["category_breakdown"] == {"financial": 25, "compliance": 20}
    assert body["confidence"] == 0.85
    assert body["created_at"] == "2026-06-01T00:00:00+00:00"


def test_analyze_api_company_not_found_returns_404(client):
    error = CompanyNotFoundError(COMPANY_NUMBER)
    with patch("app.routes.companies.perform_analysis", new=AsyncMock(side_effect=error)):
        response = client.post(f"/api/companies/{COMPANY_NUMBER}/analyze")

    assert response.status_code == 404
    assert COMPANY_NUMBER in response.json()["detail"]


def test_analyze_api_rate_limit_returns_429(client):
    error = RateLimitError(retry_after=30)
    with patch("app.routes.companies.perform_analysis", new=AsyncMock(side_effect=error)):
        response = client.post(f"/api/companies/{COMPANY_NUMBER}/analyze")

    assert response.status_code == 429
    assert "30" in response.json()["detail"]


def test_analyze_api_agent_failure_returns_502(client):
    error = AgentDidNotSubmitReportError("agent gave up")
    with patch("app.routes.companies.perform_analysis", new=AsyncMock(side_effect=error)):
        response = client.post(f"/api/companies/{COMPANY_NUMBER}/analyze")

    assert response.status_code == 502


# ---- HTML dashboard: GET / and POST /analyze ----

def test_search_page_renders(client):
    with patch("app.routes.dashboard.list_cached_companies", new=AsyncMock(return_value=[])):
        response = client.get("/")

    assert response.status_code == 200
    assert "UK Company Risk Monitor" in response.text
    assert 'name="company_number"' in response.text


def test_dashboard_analyze_success_renders_report_fragment(client):
    fake_report = make_fake_report(overall_score=60)
    with patch("app.routes.dashboard.perform_analysis", new=AsyncMock(return_value=fake_report)):
        response = client.post("/analyze", data={"company_number": COMPANY_NUMBER})

    assert response.status_code == 200
    assert COMPANY_NUMBER in response.text
    assert "60" in response.text
    # this is a fragment, not a full page -- it should NOT include the shell
    assert "<html" not in response.text.lower()


def test_dashboard_analyze_not_found_renders_error_fragment(client):
    error = CompanyNotFoundError(COMPANY_NUMBER)
    with patch("app.routes.dashboard.perform_analysis", new=AsyncMock(side_effect=error)):
        response = client.post("/analyze", data={"company_number": COMPANY_NUMBER})

    assert response.status_code == 404
    assert "No company found" in response.text


def test_dashboard_analyze_missing_company_number_is_422(client):
    # Form(...) is required -- omitting it entirely should fail validation,
    # not silently pass an empty string through to perform_analysis
    response = client.post("/analyze", data={})

    assert response.status_code == 422