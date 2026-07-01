"""Agent orchestrator: the tool-calling loop that drives risk analysis."""

from dataclasses import dataclass
from typing import Any, cast

from anthropic import AsyncAnthropic

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import TOOL_SCHEMAS, dispatch_tool_call
from app.connectors.companies_house import CompaniesHouseClient

MODEL = "claude-sonnet-4-6"
MAX_TURNS = 8


@dataclass(frozen=True)
class AgentReport:
    overall_score: int
    category_breakdown: dict
    findings: list[dict]
    confidence: float
    tool_calls_made: int


class AgentDidNotSubmitReportError(Exception):
    """Raised if the loop hits MAX_TURNS without Claude calling submit_report."""


async def run_risk_analysis(
    anthropic_client: AsyncAnthropic,
    ch_client: CompaniesHouseClient,
    company_number: str,
) -> AgentReport:
    # Explicitly Any-typed: this list holds a mix of plain user turns,
    # assistant blocks straight from the SDK, and our own tool_result
    # dicts. The Anthropic SDK's real MessageParam type is far more
    # precise than we need to hand-replicate here.
    messages: list[dict[str, Any]] = [
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
            tools=TOOL_SCHEMAS,  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
        )

        messages.append({"role": "assistant", "content": response.content})

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_use_blocks:
            messages.append(
                {
                    "role": "user",
                    "content": "Please continue the analysis using the available tools, "
                    "or call submit_report if you have enough evidence.",
                }
            )
            continue

        tool_results: list[dict[str, Any]] = []
        submitted_report: AgentReport | None = None

        for block in tool_use_blocks:
            if block.name == "submit_report":
                submitted_report = AgentReport(
                    overall_score=cast(int, block.input["overall_score"]),
                    category_breakdown=cast(dict, block.input["category_breakdown"]),
                    findings=cast(list, block.input["findings"]),
                    confidence=cast(float, block.input["confidence"]),
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