"""Tests for deterministic risk scoring. No mocking needed — pure functions,
no I/O — so these are plain assertions against constructed inputs."""

import pytest

from app.services.risk_scoring import (
    compute_compliance_signals,
    compute_financial_signals,
    score_company,
)


def signal(signals, key):
    return next(s for s in signals if s.key == key)


# ---- financial signals ----

def test_accounts_overdue_triggers():
    profile = {"accounts": {"overdue": True}, "confirmation_statement": {"overdue": False}, "company_status": "active"}
    sigs = compute_financial_signals(profile, [], [], None)
    assert signal(sigs, "accounts_overdue").triggered is True


def test_accounts_not_overdue_no_trigger():
    profile = {"accounts": {"overdue": False}, "confirmation_statement": {"overdue": False}, "company_status": "active"}
    sigs = compute_financial_signals(profile, [], [], None)
    assert signal(sigs, "accounts_overdue").triggered is False


@pytest.mark.parametrize("status", ["liquidation", "administration", "receivership", "voluntary-arrangement"])
def test_risky_statuses_trigger(status):
    profile = {"accounts": {}, "confirmation_statement": {}, "company_status": status}
    sigs = compute_financial_signals(profile, [], [], None)
    assert signal(sigs, "company_status_risk").triggered is True


def test_active_status_no_trigger():
    profile = {"accounts": {}, "confirmation_statement": {}, "company_status": "active"}
    sigs = compute_financial_signals(profile, [], [], None)
    assert signal(sigs, "company_status_risk").triggered is False


def test_insolvency_history_triggers():
    profile = {"accounts": {}, "confirmation_statement": {}, "company_status": "active"}
    insolvency = {"cases": [{"type": "administration"}]}
    sigs = compute_financial_signals(profile, [], [], insolvency)
    assert signal(sigs, "insolvency_history").triggered is True


def test_no_insolvency_data_no_trigger():
    profile = {"accounts": {}, "confirmation_statement": {}, "company_status": "active"}
    sigs = compute_financial_signals(profile, [], [], None)
    assert signal(sigs, "insolvency_history").triggered is False


def test_outstanding_charges_weight_scales():
    profile = {"accounts": {}, "confirmation_statement": {}, "company_status": "active"}
    one_charge = [{"status": "outstanding"}]
    three_charges = [{"status": "outstanding"}] * 3
    sig_one = signal(compute_financial_signals(profile, [], one_charge, None), "outstanding_charges")
    sig_three = signal(compute_financial_signals(profile, [], three_charges, None), "outstanding_charges")
    assert sig_one.weight == 5
    assert sig_three.weight == 15


def test_outstanding_charges_weight_caps_at_20():
    profile = {"accounts": {}, "confirmation_statement": {}, "company_status": "active"}
    many_charges = [{"status": "outstanding"}] * 10
    sig = signal(compute_financial_signals(profile, [], many_charges, None), "outstanding_charges")
    assert sig.weight == 20


def test_satisfied_charges_dont_count_as_outstanding():
    profile = {"accounts": {}, "confirmation_statement": {}, "company_status": "active"}
    charges = [{"status": "satisfied"}, {"status": "satisfied"}]
    sig = signal(compute_financial_signals(profile, [], charges, None), "outstanding_charges")
    assert sig.triggered is False


def test_no_filings_triggers_stale():
    profile = {"accounts": {}, "confirmation_statement": {}, "company_status": "active"}
    sig = signal(compute_financial_signals(profile, [], [], None), "stale_filings")
    assert sig.triggered is True


def test_recent_filing_no_stale_trigger():
    profile = {"accounts": {}, "confirmation_statement": {}, "company_status": "active"}
    filings = [{"date": "2026-06-01"}]
    sig = signal(compute_financial_signals(profile, filings, [], None), "stale_filings")
    assert sig.triggered is False


def test_old_filing_triggers_stale():
    profile = {"accounts": {}, "confirmation_statement": {}, "company_status": "active"}
    filings = [{"date": "2020-01-01"}]
    sig = signal(compute_financial_signals(profile, filings, [], None), "stale_filings")
    assert sig.triggered is True


def test_malformed_filing_date_is_ignored_not_crashed():
    profile = {"accounts": {}, "confirmation_statement": {}, "company_status": "active"}
    filings = [{"date": "not-a-date"}, {"date": "2026-06-01"}]
    sig = signal(compute_financial_signals(profile, filings, [], None), "stale_filings")
    assert sig.triggered is False


# ---- compliance signals ----

def test_psc_missing_triggers():
    sigs = compute_compliance_signals([], [{"name": "A"}])
    assert signal(sigs, "psc_missing").triggered is True


def test_psc_present_no_trigger():
    sigs = compute_compliance_signals([{"name": "PSC"}], [{"name": "A"}])
    assert signal(sigs, "psc_missing").triggered is False


def test_rapid_turnover_triggers_above_50_percent():
    officers = [
        {"name": "A", "resigned_on": "2025-01-01"},
        {"name": "B", "resigned_on": "2025-02-01"},
        {"name": "C"},
    ]
    sig = signal(compute_compliance_signals([], officers), "rapid_director_turnover")
    assert sig.triggered is True


def test_low_turnover_no_trigger():
    officers = [{"name": "A"}, {"name": "B"}, {"name": "C", "resigned_on": "2025-01-01"}]
    sig = signal(compute_compliance_signals([], officers), "rapid_director_turnover")
    assert sig.triggered is False


def test_single_officer_resignation_does_not_count_as_rapid():
    # A 2-person board losing 1 person is 50% turnover but too small a
    # sample to call "rapid" — guards against noisy signal on tiny boards
    officers = [{"name": "A", "resigned_on": "2025-01-01"}, {"name": "B"}]
    sig = signal(compute_compliance_signals([], officers), "rapid_director_turnover")
    assert sig.triggered is False


def test_no_active_directors_triggers():
    officers = [{"name": "A", "resigned_on": "2025-01-01"}]
    sig = signal(compute_compliance_signals([], officers), "no_active_directors")
    assert sig.triggered is True


def test_has_active_directors_no_trigger():
    officers = [{"name": "A"}]
    sig = signal(compute_compliance_signals([], officers), "no_active_directors")
    assert sig.triggered is False


# ---- aggregate scoring ----

def test_score_company_healthy_company_scores_zero():
    profile = {"accounts": {"overdue": False}, "confirmation_statement": {"overdue": False}, "company_status": "active"}
    filings = [{"date": "2026-06-01"}]
    officers = [{"name": "A"}, {"name": "B"}]
    psc = [{"name": "PSC"}]
    result = score_company(profile, officers, psc, filings, None, [])
    assert result.overall_score == 0
    assert result.category_breakdown == {"financial": 0, "compliance": 0}


def test_score_company_worst_case_caps_at_100_per_category():
    profile = {
        "accounts": {"overdue": True},
        "confirmation_statement": {"overdue": True},
        "company_status": "liquidation",
    }
    insolvency = {"cases": [{"type": "liquidation"}]}
    charges = [{"status": "outstanding"}] * 5
    result = score_company(profile, [], [], [], insolvency, charges)
    assert result.category_breakdown["financial"] == 100
    assert result.overall_score <= 100


def test_score_company_overall_is_weighted_average_of_categories():
    # financial=25 (accounts overdue only), compliance=20 (psc missing only)
    profile = {"accounts": {"overdue": True}, "confirmation_statement": {"overdue": False}, "company_status": "active"}
    filings = [{"date": "2026-06-01"}]
    officers = [{"name": "A"}, {"name": "B"}]
    result = score_company(profile, officers, [], filings, None, [])
    assert result.category_breakdown["financial"] == 25
    assert result.category_breakdown["compliance"] == 20
    assert result.overall_score == round(25 * 0.6 + 20 * 0.4)