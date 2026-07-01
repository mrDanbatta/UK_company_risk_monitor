"""Tool schemas exposed to Claude, and dispatch back to the Stage 1 connector.

The agent doesn't call CompaniesHouseClient directly — it requests a tool
by name with arguments, and the orchestrator loop (orchestrator.py) is what
actually executes it and returns the result. This module owns both halves:
the schema Claude sees, and the function that runs when Claude picks it.
"""

from app.connectors.companies_house import CompaniesHouseClient

TOOL_SCHEMAS = [
    {
        "name": "get_company_profile",
        "description": "Get core company details: status, incorporation date, SIC codes, registered office, accounts and confirmation statement due dates.",
        "input_schema": {
            "type": "object",
            "properties": {"company_number": {"type": "string"}},
            "required": ["company_number"],
        },
    },
    {
        "name": "get_officers",
        "description": "Get current and resigned directors/officers for a company.",
        "input_schema": {
            "type": "object",
            "properties": {"company_number": {"type": "string"}},
            "required": ["company_number"],
        },
    },
    {
        "name": "get_psc",
        "description": "Get persons with significant control (PSC) for a company.",
        "input_schema": {
            "type": "object",
            "properties": {"company_number": {"type": "string"}},
            "required": ["company_number"],
        },
    },
    {
        "name": "get_filing_history",
        "description": "Get the filing history (accounts, confirmation statements, charges filed, etc.) for a company.",
        "input_schema": {
            "type": "object",
            "properties": {"company_number": {"type": "string"}},
            "required": ["company_number"],
        },
    },
    {
        "name": "get_insolvency",
        "description": "Get insolvency practitioner case history for a company, if any.",
        "input_schema": {
            "type": "object",
            "properties": {"company_number": {"type": "string"}},
            "required": ["company_number"],
        },
    },
    {
        "name": "get_charges",
        "description": "Get registered charges (mortgages/debentures) for a company.",
        "input_schema": {
            "type": "object",
            "properties": {"company_number": {"type": "string"}},
            "required": ["company_number"],
        },
    },
    {
        "name": "submit_report",
        "description": "Submit the final structured risk report. Call this once you have gathered enough evidence — it ends the analysis.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "overall_score": {
                    "type": "integer",
                    "description": "Overall risk score from 0 (no risk) to 100 (highest risk).",
                },
                "category_breakdown": {
                    "type": "object",
                    "properties": {
                        "financial": {"type": "integer", "description": "0-100"},
                        "compliance": {"type": "integer", "description": "0-100"},
                    },
                    "required": ["financial", "compliance"],
                    "additionalProperties": False,
                },
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "category": {"type": "string"},
                            "summary": {"type": "string"},
                            "citation": {"type": "string"},
                        },
                        "required": ["category", "summary", "citation"],
                        "additionalProperties": False,
                    },
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence in this report from 0.0 to 1.0.",
                },
            },
            "required": ["overall_score", "category_breakdown", "findings", "confidence"],
            "additionalProperties": False,
        },
    },
]

# Tool name -> connector method name. submit_report is handled separately
# by the orchestrator since it ends the loop rather than fetching data.
_DISPATCH_MAP = {
    "get_company_profile": "get_company_profile",
    "get_officers": "get_officers",
    "get_psc": "get_psc",
    "get_filing_history": "get_filing_history",
    "get_insolvency": "get_insolvency",
    "get_charges": "get_charges",
}


async def dispatch_tool_call(
    ch_client: CompaniesHouseClient, tool_name: str, tool_input: dict
) -> dict | list | None:
    """Execute a data-fetching tool call against the Companies House client.

    Raises KeyError if tool_name is submit_report or unknown — the caller
    (orchestrator) is responsible for handling submit_report before this
    is ever reached.
    """
    method_name = _DISPATCH_MAP[tool_name]
    method = getattr(ch_client, method_name)
    return await method(tool_input["company_number"])