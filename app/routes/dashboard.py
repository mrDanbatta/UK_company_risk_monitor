"""HTML dashboard: search page plus an HTMX endpoint that returns just the
rendered report fragment, swapped into the page without a full reload."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.orchestrator import AgentDidNotSubmitReportError
from app.connectors.companies_house import CompanyNotFoundError, RateLimitError
from app.db import get_session
from app.models.company import Company
from app.services.analysis import perform_analysis
from app.services.cache import list_cached_companies

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def search_page(request: Request, session: AsyncSession = Depends(get_session)):
    recent = await list_cached_companies(session)
    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={"recent_companies": recent},
    )


@router.post("/analyse", response_class=HTMLResponse)
async def analyse_and_render(
    request: Request,
    company_number: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    try:
        report = await perform_analysis(session, company_number)
    except CompanyNotFoundError:
        return templates.TemplateResponse(
            request=request,
            name="report.html",
            context={"error": f"No company found for number '{company_number}'"},
            status_code=404,
        )
    except RateLimitError as e:
        return templates.TemplateResponse(
            request=request,
            name="report.html",
            context={
                "error": f"Companies House rate limit hit, retry after {e.retry_after}s"
            },
            status_code=429,
        )
    except AgentDidNotSubmitReportError:
        return templates.TemplateResponse(
            request=request,
            name="report.html",
            context={"error": "Analysis did not complete — please try again"},
            status_code=502,
        )

    company = await session.get(Company, company_number)
    company_name = company.raw_profile.get("company_name") if company else None

    return templates.TemplateResponse(
        request=request,
        name="report.html",
        context={"report": report, "company_name": company_name},
    )