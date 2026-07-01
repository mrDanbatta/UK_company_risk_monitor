"""Tests for the agent orchestrator's tool-calling loop.

Mocks the Anthropic client entirely — these tests exercise control flow
(does it call the right tools, does it stop on submit_report, does it
survive a tool error) without spending real API credits.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, create_autospec

import pytest

from app.agent.orchestrator import (
    MAX_TURNS,
    AgentDidNotSubmitReportError,
    run_risk_analysis,
)
from app.connectors.companies_house import CompaniesHouseClient, RateLimitError

COMPANY_NUMBER = "12345678"


def make_text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def make_tool_use_block(name: str, input_: dict, block_id: str = "tool_1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=input_)


def make_response(blocks: list) -> SimpleNamespace:
    return SimpleNamespace(content=blocks)


def make_submit_block(
    overall_score=10,
    financial=10,
    compliance=0,
    findings=None,
    confidence=0.9,
    block_id="submit_1",
) -> SimpleNamespace:
    return make_tool_use_block(
        "submit_report",
        {
            "overall_score": overall_score,
            "category_breakdown": {"financial": financial, "compliance": compliance},
            "findings": findings or [],
            "confidence": confidence,
        },
        block_id=block_id,
    )


def make_capturing_create(responses: list):
    """Returns (mock, snapshots). snapshots[i] is a shallow copy of the
    `messages` kwarg exactly as it was AT CALL TIME i — not a reference to
    the live list, which the orchestrator keeps mutating after each call.
    """
    responses = list(responses)
    snapshots: list[list] = []

    async def _create(**kwargs):
        snapshots.append(list(kwargs["messages"]))
        return responses.pop(0)

    return AsyncMock(side_effect=_create), snapshots


@pytest.fixture
def mock_ch_client():
    client = create_autospec(CompaniesHouseClient, instance=True)
    client.get_company_profile.return_value = {"company_status": "active"}
    client.get_officers.return_value = []
    client.get_psc.return_value = []
    client.get_filing_history.return_value = []
    client.get_insolvency.return_value = None
    client.get_charges.return_value = []
    return client


@pytest.fixture
def mock_anthropic_client():
    return SimpleNamespace(messages=SimpleNamespace(create=AsyncMock()))


async def test_immediate_submit_report_returns_report(mock_anthropic_client, mock_ch_client):
    mock_anthropic_client.messages.create.return_value = make_response(
        [make_submit_block(overall_score=42, financial=30, compliance=12)]
    )

    report = await run_risk_analysis(mock_anthropic_client, mock_ch_client, COMPANY_NUMBER)

    assert report.overall_score == 42
    assert report.category_breakdown == {"financial": 30, "compliance": 12}
    assert report.tool_calls_made == 0
    mock_ch_client.get_company_profile.assert_not_awaited()


async def test_calls_data_tool_then_submits(mock_anthropic_client, mock_ch_client):
    mock_anthropic_client.messages.create.side_effect = [
        make_response(
            [make_tool_use_block("get_company_profile", {"company_number": COMPANY_NUMBER})]
        ),
        make_response([make_submit_block()]),
    ]

    report = await run_risk_analysis(mock_anthropic_client, mock_ch_client, COMPANY_NUMBER)

    mock_ch_client.get_company_profile.assert_awaited_once_with(COMPANY_NUMBER)
    assert report.tool_calls_made == 1


async def test_multiple_tool_calls_in_one_turn(mock_anthropic_client, mock_ch_client):
    mock_anthropic_client.messages.create.side_effect = [
        make_response(
            [
                make_tool_use_block(
                    "get_company_profile", {"company_number": COMPANY_NUMBER}, "t1"
                ),
                make_tool_use_block("get_officers", {"company_number": COMPANY_NUMBER}, "t2"),
            ]
        ),
        make_response([make_submit_block()]),
    ]

    report = await run_risk_analysis(mock_anthropic_client, mock_ch_client, COMPANY_NUMBER)

    mock_ch_client.get_company_profile.assert_awaited_once_with(COMPANY_NUMBER)
    mock_ch_client.get_officers.assert_awaited_once_with(COMPANY_NUMBER)
    assert report.tool_calls_made == 2


async def test_tool_error_does_not_crash_loop(mock_ch_client):
    mock_ch_client.get_officers.side_effect = RateLimitError(retry_after=30)

    create_mock, snapshots = make_capturing_create(
        [
            make_response(
                [make_tool_use_block("get_officers", {"company_number": COMPANY_NUMBER})]
            ),
            make_response([make_submit_block(confidence=0.5)]),
        ]
    )
    anthropic_client = SimpleNamespace(messages=SimpleNamespace(create=create_mock))

    report = await run_risk_analysis(anthropic_client, mock_ch_client, COMPANY_NUMBER)

    # the loop kept going after the error and Claude still submitted a report
    assert report.confidence == 0.5

    # snapshots[1] is what the SECOND call actually saw — the tool_result
    # message from the FIRST call's error should be the last thing in it
    messages_seen_at_second_call = snapshots[1]
    tool_results = messages_seen_at_second_call[-1]["content"]
    assert any(r.get("is_error") for r in tool_results)


async def test_text_only_response_gets_nudged_then_continues(mock_ch_client):
    create_mock, snapshots = make_capturing_create(
        [
            make_response([make_text_block("Let me think about this...")]),
            make_response([make_submit_block()]),
        ]
    )
    anthropic_client = SimpleNamespace(messages=SimpleNamespace(create=create_mock))

    report = await run_risk_analysis(anthropic_client, mock_ch_client, COMPANY_NUMBER)

    assert report is not None
    assert len(snapshots) == 2

    # the SECOND call should have seen the nudge message we sent after
    # the first (text-only) response
    messages_seen_at_second_call = snapshots[1]
    last_message = messages_seen_at_second_call[-1]
    assert last_message["role"] == "user"
    assert "submit_report" in last_message["content"]


async def test_raises_if_never_submits_within_max_turns(mock_anthropic_client, mock_ch_client):
    # Every turn just calls get_company_profile again, never submits
    mock_anthropic_client.messages.create.return_value = make_response(
        [make_tool_use_block("get_company_profile", {"company_number": COMPANY_NUMBER})]
    )

    with pytest.raises(AgentDidNotSubmitReportError):
        await run_risk_analysis(mock_anthropic_client, mock_ch_client, COMPANY_NUMBER)

    assert mock_anthropic_client.messages.create.await_count == MAX_TURNS