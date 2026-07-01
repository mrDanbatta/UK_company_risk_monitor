"""Deterministic risk scoring from raw Companies House data.

This module contains no LLM calls. It turns raw API payloads into named,
weighted RiskSignals, then aggregates those into category and overall
scores. Keeping this layer pure and deterministic means a wrong risk flag
is a logic bug you can unit-test — not an unpredictable model output.

The agent (Stage 4) consumes this module's output as evidence; it explains
and contextualizes these signals, it does not invent them.
"""

from dataclasses import dataclass
from datetime import date

RISKY_COMPANY_STATUSES = {
    "liquidation",
    "receivership",
    "administration",
    "voluntary-arrangement",
    "insolvency-proceedings",
}

STALE_FILING_DAYS = 548  # ~18 months


@dataclass(frozen=True)
class RiskSignal:
    """One deterministic risk signal derived from raw Companies House data.

    `weight` is the number of risk points this signal contributes to its
    category score when `triggered` is True. Weights are additive and
    capped at the category level in `score_company`.
    """

    key: str
    category: str  # "financial" or "compliance"
    triggered: bool
    weight: int
    detail: str


def _most_recent_filing_date(filing_history: list[dict]) -> date | None:
    dates = []
    for f in filing_history:
        raw = f.get("date")
        if not raw:
            continue
        try:
            dates.append(date.fromisoformat(raw))
        except ValueError:
            continue
    return max(dates) if dates else None


def compute_financial_signals(
    profile: dict,
    filing_history: list[dict],
    charges: list[dict],
    insolvency: dict | None,
) -> list[RiskSignal]:
    signals: list[RiskSignal] = []

    accounts_overdue = bool(profile.get("accounts", {}).get("overdue", False))
    signals.append(
        RiskSignal(
            key="accounts_overdue",
            category="financial",
            triggered=accounts_overdue,
            weight=25,
            detail="Annual accounts are overdue"
            if accounts_overdue
            else "Accounts filed on time",
        )
    )

    cs_overdue = bool(profile.get("confirmation_statement", {}).get("overdue", False))
    signals.append(
        RiskSignal(
            key="confirmation_statement_overdue",
            category="financial",
            triggered=cs_overdue,
            weight=15,
            detail="Confirmation statement is overdue"
            if cs_overdue
            else "Confirmation statement filed on time",
        )
    )

    status = (profile.get("company_status") or "").lower()
    status_risk = status in RISKY_COMPANY_STATUSES
    signals.append(
        RiskSignal(
            key="company_status_risk",
            category="financial",
            triggered=status_risk,
            weight=50,
            detail=f"Company status is '{status}'",
        )
    )

    has_insolvency = bool(insolvency and insolvency.get("cases"))
    signals.append(
        RiskSignal(
            key="insolvency_history",
            category="financial",
            triggered=has_insolvency,
            weight=40,
            detail="Company has recorded insolvency practitioner cases"
            if has_insolvency
            else "No insolvency history on record",
        )
    )

    outstanding = [c for c in charges if c.get("status") == "outstanding"]
    outstanding_count = len(outstanding)
    # Each outstanding charge adds risk; capped so 4+ charges don't dominate the score
    charge_weight = min(outstanding_count * 5, 20)
    signals.append(
        RiskSignal(
            key="outstanding_charges",
            category="financial",
            triggered=outstanding_count > 0,
            weight=charge_weight,
            detail=f"{outstanding_count} outstanding charge(s) registered"
            if outstanding_count
            else "No outstanding charges",
        )
    )

    most_recent = _most_recent_filing_date(filing_history)
    stale = most_recent is None or (date.today() - most_recent).days > STALE_FILING_DAYS
    signals.append(
        RiskSignal(
            key="stale_filings",
            category="financial",
            triggered=stale,
            weight=10,
            detail="No filings on record"
            if most_recent is None
            else f"Most recent filing was {most_recent.isoformat()}",
        )
    )

    return signals


def compute_compliance_signals(
    psc: list[dict],
    officers: list[dict],
) -> list[RiskSignal]:
    signals: list[RiskSignal] = []

    psc_missing = len(psc) == 0
    signals.append(
        RiskSignal(
            key="psc_missing",
            category="compliance",
            triggered=psc_missing,
            weight=20,
            detail="No persons with significant control registered"
            if psc_missing
            else f"{len(psc)} PSC(s) registered",
        )
    )

    active_officers = [o for o in officers if not o.get("resigned_on")]
    resigned_officers = [o for o in officers if o.get("resigned_on")]
    total = len(active_officers) + len(resigned_officers)
    turnover_rate = (len(resigned_officers) / total) if total else 0.0

    # Require at least 2 officers on record so a single resignation on a
    # 2-person board doesn't read as "rapid turnover"
    rapid_turnover = turnover_rate > 0.5 and total >= 2
    signals.append(
        RiskSignal(
            key="rapid_director_turnover",
            category="compliance",
            triggered=rapid_turnover,
            weight=20,
            detail=f"Director turnover rate is {turnover_rate:.0%}",
        )
    )

    no_active_directors = len(active_officers) == 0
    signals.append(
        RiskSignal(
            key="no_active_directors",
            category="compliance",
            triggered=no_active_directors,
            weight=40,
            detail="No active directors on record"
            if no_active_directors
            else f"{len(active_officers)} active director(s)",
        )
    )

    return signals


@dataclass(frozen=True)
class ScoringResult:
    overall_score: int  # 0-100, higher = riskier
    category_breakdown: dict[str, int]
    signals: list[RiskSignal]


def _category_score(signals: list[RiskSignal], category: str) -> int:
    triggered_weights = [s.weight for s in signals if s.category == category and s.triggered]
    return min(sum(triggered_weights), 100)


def score_company(
    profile: dict,
    officers: list[dict],
    psc: list[dict],
    filing_history: list[dict],
    insolvency: dict | None,
    charges: list[dict],
) -> ScoringResult:
    """Aggregate financial + compliance signals into a single risk score.

    Financial signals are weighted slightly higher than compliance signals
    (0.6 / 0.4) since insolvency and overdue filings tend to be more
    immediately consequential than governance opacity — adjust this split
    if you want to argue the weighting differently in your README.
    """
    financial_signals = compute_financial_signals(profile, filing_history, charges, insolvency)
    compliance_signals = compute_compliance_signals(psc, officers)
    all_signals = financial_signals + compliance_signals

    financial_score = _category_score(all_signals, "financial")
    compliance_score = _category_score(all_signals, "compliance")
    overall_score = round(financial_score * 0.6 + compliance_score * 0.4)

    return ScoringResult(
        overall_score=min(overall_score, 100),
        category_breakdown={"financial": financial_score, "compliance": compliance_score},
        signals=all_signals,
    )