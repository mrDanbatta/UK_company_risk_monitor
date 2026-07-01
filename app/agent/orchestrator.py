"""Agent orchestrator: the tool-calling loop that drives risk analysis.

Flow: send the company number to Claude with the tool schemas -> Claude
requests a tool -> we execute it against Companies House -> feed the
result back -> repeat until Claude calls submit_report.
"""

from dataclasses import dataclass

from anthropic import AsyncAnthropic

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import TOOL_SCHEMAS, dispatch_tool_call
from app.connectors.companies_house import CompaniesHouseClient

MODEL = "claude-sonnet-4-6"
MAX_TURNS = 8  # safety cap so a confused agent can't loop forever


@dataclass(frozen=True)
class AgentReport:
    overall_score: int
    category_breakdown: dict
    findings: list[dict]
    confidence: float
    tool_calls_made: int  # useful for logging/debugging, not part of the schema


class AgentDidNotSubmitReportError(Exception):
    """Raised if the loop hits MAX_TURNS without Claude calling submit_report."""


async def run_risk_analysis(
    anthropic_client: AsyncAnthropic,
    ch_client: CompaniesHouseClient,
    company_number: str,
) -> AgentReport:
    messages = [
        {
            "role": "user",
            "content": f"Analyze company number {company_number} and produce a risk report.",
        }
    ]

    tool_calls_made = 0

    for _ in range(MAX_TURNS):
        response = await anthropic_client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_use_blocks:
            # Claude replied with only text and no tool call — nudge it,
            # rather than silently failing the analysis.
            messages.append(
                {
                    "role": "user",
                    "content": "Please continue the analysis using the available tools, "
                    "or call submit_report if you have enough evidence.",
                }
            )
            continue

        tool_results = []
        submitted_report: AgentReport | None = None

        for block in tool_use_blocks:
            if block.name == "submit_report":
                submitted_report = AgentReport(
                    overall_score=block.input["overall_score"],
                    category_breakdown=block.input["category_breakdown"],
                    findings=block.input["findings"],
                    confidence=block.input["confidence"],
                    tool_calls_made=tool_calls_made,
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Report submitted.",
                    }
                )
                continue

            tool_calls_made += 1
            try:
                result = await dispatch_tool_call(ch_client, block.name, block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(result),
                    }
                )
            except Exception as e:
                # Surface the error to Claude rather than crashing the
                # whole analysis — it can adapt (e.g. skip that data source).
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error calling {block.name}: {e}",
                        "is_error": True,
                    }
                )

        if submitted_report is not None:
            return submitted_report

        messages.append({"role": "user", "content": tool_results})

    raise AgentDidNotSubmitReportError(
        f"Agent did not submit a report for {company_number} within {MAX_TURNS} turns"
    )