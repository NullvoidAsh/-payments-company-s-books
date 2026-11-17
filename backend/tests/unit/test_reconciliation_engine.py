"""
Unit tests for all mandatory discrepancy cases and additional scenarios.
Tests run against the reconciliation engine directly — no HTTP required.
"""
import pytest
from datetime import date
from decimal import Decimal
from app.models.domain import (
    InternalTransaction, BankSettlement, SystemConfig, CarryForwardEntry
)
from app.services.reconciliation_engine import run_reconciliation

CFG = SystemConfig(rounding_tolerance=Decimal("0.01"), settlement_window=2)
JAN31 = date(2024, 1, 31)
FEB1  = date(2024, 2, 1)
JAN5  = date(2024, 1, 5)
JAN6  = date(2024, 1, 6)
JAN2  = date(2024, 1, 2)


def _t(tid, td, amount, currency="INR", ttype="payment",
       status="success", orig_ref=None):
    return InternalTransaction(
        transaction_id=tid, transaction_date=td,
        transaction_amount=Decimal(str(amount)), currency=currency,
        transaction_type=ttype, status=status,
        original_transaction_ref=orig_ref,
        merchant_id="M001", payment_method="card",
    )


def _s(sid, tref, sd, amount, currency="INR", batch="B001", bank="TestBank"):
    from datetime import datetime
    return BankSettlement(
        settlement_id=sid, transaction_ref=tref,
        settlement_amount=Decimal(str(amount)), currency=currency,
        settlement_date=sd,
        settlement_timestamp=datetime(sd.year, sd.month, sd.day, 10, 0, 0),
        bank_batch_id=batch, bank_name=bank, status="settled",
    )


def _run(txns, stls, as_of=JAN31, cfg=CFG, cf=None, known=None):
    result, new_cf, upd_cf = run_reconciliation(
        period_label="2024-01", as_of_date=as_of,
        transactions=txns, settlements=stls,
        carry_forward_entries=cf or [],
        config=cfg, all_known_payment_ids=known,
    )
    return result, new_cf, upd_cf


def cls_map(result):
    return {d.transaction_id or d.settlement_id: d.classification
            for d in result.discrepancy_list}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CASE 1 — TIMING_DIFFERENCE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_timing_difference_january_run():
    """Jan 31 transaction with no January settlement -> TIMING_DIFFERENCE."""
    txns = [_t("T1", JAN31, "1500.00")]
    stls = []  # settlement arrives Feb 1 — not in Jan data
    result, new_cf, _ = _run(txns, stls, as_of=JAN31)
    cm = cls_map(result)
    assert cm["T1"] == "TIMING_DIFFERENCE", f"Expected TIMING_DIFFERENCE, got {cm['T1']}"
    assert len(new_cf) == 1
    assert new_cf[0].transaction_id == "T1"
    assert new_cf[0].status == "outstanding"


def test_timing_difference_february_resolves():
    """Feb run: carry-forward T1 matches Feb 1 settlement -> resolved."""
    from decimal import Decimal as D
    cf_entry = CarryForwardEntry(
        entry_id="cf-001",
        transaction_id="T1",
        originating_period_label="2024-01",
        outstanding_days=0,
        status="outstanding",
        transaction_amount=D("1500.00"),
        transaction_currency="INR",
        created_as_of_date=JAN31.isoformat(),
        last_updated_at="2024-01-31T10:00:00",
        reconciliation_run_id="run-jan",
    )
    # In Feb run we pass the Jan transaction so the engine can look it up
    txns = [_t("T1", JAN31, "1500.00")]
    stls = [_s("S1", "T1", FEB1, "1500.00")]
    result, _, upd_cf = run_reconciliation(
        period_label="2024-02", as_of_date=FEB1,
        transactions=txns, settlements=stls,
        carry_forward_entries=[cf_entry], config=CFG,
    )
    assert any(r["transaction_id"] == "T1" for r in result.resolved_carried_forward), \
        "T1 should appear in resolved_carried_forward"
    resolved = [e for e in upd_cf if e.status == "resolved"]
    assert len(resolved) == 1
    assert resolved[0].resolved_period_label == "2024-02"


def test_timing_difference_uses_as_of_date_not_clock():
    """Explicit as_of_date controls TIMING_DIFFERENCE, not system clock."""
    txns = [_t("T1", JAN31, "1500.00")]
    stls = []
    # as_of = Jan31, days_since_cutoff = 0, window = 2 -> TIMING_DIFFERENCE
    result, _, _ = _run(txns, stls, as_of=JAN31)
    assert cls_map(result)["T1"] == "TIMING_DIFFERENCE"
    # as_of = Jan5, days_since_cutoff = 26, window = 2 -> MISSING_SETTLEMENT
    result2, _, _ = _run(txns, stls, as_of=date(2024, 1, 4))
    # T1 date=Jan31 but as_of=Jan4 means days=-27 (future), so <= window -> TIMING_DIFFERENCE
    # Actually Jan31 - Jan4 = 27 days. Let's use a txn dated Jan2 and as_of Jan31
    txns2 = [_t("T2", JAN2, "1500.00")]
    result3, _, _ = _run(txns2, [], as_of=JAN31)
    assert cls_map(result3)["T2"] == "MISSING_SETTLEMENT", \
        f"29 days > window=2 should be MISSING_SETTLEMENT, got {cls_map(result3).get('T2')}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CASE 2 — ROUNDING_DIFFERENCE (never MATCHED)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_rounding_difference_case2():
    """100.505 vs 100.50 -> diff=0.005 <= tol=0.01 -> ROUNDING_DIFFERENCE."""
    txns = [_t("T2", JAN5, "100.505")]
    stls = [_s("S2", "T2", JAN6, "100.50")]
    result, _, _ = _run(txns, stls)
    cm = cls_map(result)
    assert cm["T2"] == "ROUNDING_DIFFERENCE", f"Got {cm['T2']}"


def test_rounding_difference_is_not_matched():
    """CRITICAL: a non-zero diff within tolerance must NOT be MATCHED."""
    txns = [_t("T2", JAN5, "100.505")]
    stls = [_s("S2", "T2", JAN6, "100.50")]
    result, _, _ = _run(txns, stls)
    assert cls_map(result)["T2"] != "MATCHED"


def test_rounding_difference_records_exact_diff():
    """individual_difference stored as Decimal('0.005')."""
    txns = [_t("T2", JAN5, "100.505")]
    stls = [_s("S2", "T2", JAN6, "100.50")]
    result, _, _ = _run(txns, stls)
    disc = next(d for d in result.discrepancy_list if d.transaction_id == "T2")
    assert disc.individual_difference == Decimal("0.005")


def test_exact_zero_diff_is_matched():
    """diff=0 -> MATCHED."""
    txns = [_t("T3", JAN5, "500.00")]
    stls = [_s("S3", "T3", JAN6, "500.00")]
    result, _, _ = _run(txns, stls)
    assert cls_map(result)["T3"] == "MATCHED"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CASE 3 — DUPLICATE DETECTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_duplicate_settlement_by_id():
    """Two settlements with same settlement_id -> second is DUPLICATE_SETTLEMENT."""
    txns = [_t("T4", JAN5, "500.00")]
    stls = [
        _s("STL-DUP", "T4", JAN6, "500.00"),
        _s("STL-DUP", "T4", JAN6, "500.00", batch="B002"),  # same ID
    ]
    result, _, _ = _run(txns, stls)
    dup_records = [d for d in result.discrepancy_list if d.classification == "DUPLICATE_SETTLEMENT"]
    assert len(dup_records) == 1
    assert dup_records[0].duplicate_fingerprint.startswith("settlement_id:")


def test_duplicate_settlement_excluded_from_totals():
    """Duplicate settlement amount not counted in bank_settlement_total."""
    txns = [_t("T4", JAN5, "500.00")]
    stls = [
        _s("STL-DUP", "T4", JAN6, "500.00"),
        _s("STL-DUP", "T4", JAN6, "500.00", batch="B002"),
    ]
    result, _, _ = _run(txns, stls)
    # Only one settlement should count -> bank_total = 500
    assert result.bank_settlement_total == Decimal("500.00"), \
        f"Expected 500.00, got {result.bank_settlement_total}"


def test_duplicate_settlement_remains_in_report():
    """Duplicate record visible in discrepancy list, not silently deleted."""
    txns = [_t("T4", JAN5, "500.00")]
    stls = [_s("STL-DUP", "T4", JAN6, "500.00"), _s("STL-DUP", "T4", JAN6, "500.00")]
    result, _, _ = _run(txns, stls)
    all_cls = [d.classification for d in result.discrepancy_list]
    assert "DUPLICATE_SETTLEMENT" in all_cls


def test_duplicate_settlement_exact_record_fingerprint():
    """Different settlement_ids but same content -> DUPLICATE_SETTLEMENT via D-04."""
    txns = [_t("T5", JAN5, "750.00")]
    stls = [
        _s("STL-FP-A", "T5", JAN6, "750.00", batch="BATCHX"),
        _s("STL-FP-B", "T5", JAN6, "750.00", batch="BATCHX"),  # same content
    ]
    result, _, _ = _run(txns, stls)
    dup = [d for d in result.discrepancy_list if d.classification == "DUPLICATE_SETTLEMENT"]
    assert len(dup) == 1
    assert dup[0].duplicate_fingerprint.startswith("exact_record:")


def test_duplicate_transaction_by_id():
    """Two transactions with same ID -> second is DUPLICATE_TRANSACTION."""
    txns = [_t("T6", JAN5, "600.00"), _t("T6", JAN5, "600.00")]
    stls = [_s("S6", "T6", JAN6, "600.00")]
    result, _, _ = _run(txns, stls)
    dup = [d for d in result.discrepancy_list if d.classification == "DUPLICATE_TRANSACTION"]
    assert len(dup) == 1


def test_multiple_settlements_not_duplicate():
    """3 distinct-ID settlements for 1 transaction -> MULTIPLE_SETTLEMENTS, no DUPLICATE_SETTLEMENT.
    Each settlement has a distinct batch_id to avoid exact-record fingerprint collision."""
    txns = [_t("T7", JAN5, "900.00")]
    stls = [
        _s("S7A", "T7", JAN6, "300.00", batch="BATCH-A"),
        _s("S7B", "T7", JAN6, "300.00", batch="BATCH-B"),
        _s("S7C", "T7", JAN6, "300.00", batch="BATCH-C"),
    ]
    result, _, _ = _run(txns, stls)
    cm = cls_map(result)
    assert cm["T7"] == "MULTIPLE_SETTLEMENTS", f"Expected MULTIPLE_SETTLEMENTS got {cm.get('T7')}"
    dup = [d for d in result.discrepancy_list if d.classification == "DUPLICATE_SETTLEMENT"]
    assert len(dup) == 0, "No DUPLICATE_SETTLEMENT for legitimate multi-settlements"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CASE 4 — ORPHAN_REFUND
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_orphan_refund():
    """Refund referencing non-existent original_transaction_ref -> ORPHAN_REFUND."""
    txns = [_t("REFUND-1", JAN5, "200.00", ttype="refund", orig_ref="TXN-NONEXISTENT")]
    result, _, _ = _run(txns, [])
    assert cls_map(result)["REFUND-1"] == "ORPHAN_REFUND"


def test_valid_refund_matched():
    """Refund with valid original_transaction_ref + matching settlement -> MATCHED."""
    txns = [
        _t("ORIG-PAY", JAN5, "350.00"),
        _t("REF-1", date(2024,1,20), "350.00", ttype="refund", orig_ref="ORIG-PAY"),
    ]
    stls = [
        _s("S-ORIG", "ORIG-PAY", JAN6, "350.00"),
        _s("S-REF",  "REF-1",    date(2024,1,21), "350.00"),
    ]
    result, _, _ = _run(txns, stls)
    cm = cls_map(result)
    assert cm["ORIG-PAY"] == "MATCHED"
    assert cm["REF-1"] == "MATCHED"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AGGREGATE ROUNDING (T-D)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_aggregate_rounding_exceeds_tolerance():
    """10 pairs each diff=0.001 -> aggregate=0.010 >= tol=0.01 -> flag=true."""
    txns = [_t(f"AGG-{i}", JAN5, "50.001") for i in range(10)]
    stls = [_s(f"SAGG-{i}", f"AGG-{i}", JAN6, "50.00") for i in range(10)]
    result, _, _ = _run(txns, stls)
    assert result.aggregate_rounding_difference == Decimal("0.010"), \
        f"Expected 0.010 got {result.aggregate_rounding_difference}"
    assert result.aggregate_exceeds_tolerance is True


def test_aggregate_rounding_each_individually_classified():
    """Each of the 10 pairs appears individually as ROUNDING_DIFFERENCE."""
    txns = [_t(f"AGG-{i}", JAN5, "50.001") for i in range(10)]
    stls = [_s(f"SAGG-{i}", f"AGG-{i}", JAN6, "50.00") for i in range(10)]
    result, _, _ = _run(txns, stls)
    rounding_records = [d for d in result.discrepancy_list
                        if d.classification == "ROUNDING_DIFFERENCE"]
    assert len(rounding_records) == 10


def test_aggregate_rounding_uses_gte_operator():
    """aggregate_exceeds_tolerance uses >= not >; 0.010 >= 0.01 is True."""
    txns = [_t(f"AGG-{i}", JAN5, "50.001") for i in range(10)]
    stls = [_s(f"SAGG-{i}", f"AGG-{i}", JAN6, "50.00") for i in range(10)]
    result, _, _ = _run(txns, stls)
    # Explicitly verify the boundary condition
    assert result.aggregate_rounding_difference >= Decimal("0.01")
    assert result.aggregate_exceeds_tolerance is True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ADDITIONAL SCENARIOS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def test_missing_settlement():
    """Transaction with no settlement and cutoff days > window -> MISSING_SETTLEMENT."""
    txns = [_t("T-MISS", JAN2, "400.00")]
    result, _, _ = _run(txns, [], as_of=JAN31)  # 29 days > window=2
    assert cls_map(result)["T-MISS"] == "MISSING_SETTLEMENT"


def test_unmatched_settlement():
    """Settlement with no matching internal transaction -> UNMATCHED_SETTLEMENT."""
    stls = [_s("S-GHOST", "TXN-GHOST", JAN6, "300.00")]
    result, _, _ = _run([], stls)
    assert cls_map(result)["S-GHOST"] == "UNMATCHED_SETTLEMENT"


def test_partial_settlement():
    """Settlement covers only 60% of transaction -> PARTIAL_SETTLEMENT."""
    txns = [_t("T-PART", JAN5, "1000.00")]
    stls = [_s("S-PART", "T-PART", JAN6, "600.00")]
    result, _, _ = _run(txns, stls)
    assert cls_map(result)["T-PART"] == "PARTIAL_SETTLEMENT"


def test_currency_mismatch():
    """Different currencies -> CURRENCY_MISMATCH, no amount comparison."""
    txns = [_t("T-CURR", JAN5, "1000.00", currency="INR")]
    stls = [_s("S-CURR", "T-CURR", JAN6, "1000.00", currency="USD")]
    result, _, _ = _run(txns, stls)
    assert cls_map(result)["T-CURR"] == "CURRENCY_MISMATCH"


def test_failed_transaction_excluded_from_totals():
    """Failed transaction not counted in gross_transaction_value."""
    txns = [_t("T-FAIL", JAN5, "500.00", status="failed")]
    result, _, _ = _run(txns, [])
    assert result.gross_transaction_value == Decimal("0")


def test_failed_transaction_with_settlement_flagged():
    """Bank settlement matching a failed transaction -> UNMATCHED_SETTLEMENT with note."""
    txns = [_t("T-FAIL", JAN5, "500.00", status="failed")]
    stls = [_s("S-FAIL", "T-FAIL", JAN6, "500.00")]
    result, _, _ = _run(txns, stls)
    recs = [d for d in result.discrepancy_list if d.settlement_id == "S-FAIL"]
    assert len(recs) == 1
    assert recs[0].classification == "UNMATCHED_SETTLEMENT"
    assert "failed transaction" in (recs[0].resolution_note or "").lower()


def test_financial_totals_decimal_exact():
    """Financial totals computed with Decimal, never float."""
    txns = [
        _t("P1", JAN5, "100.505"),  # payment
        _t("R1", JAN5, "50.00", ttype="refund", orig_ref="P1"),  # refund
    ]
    stls = [
        _s("S-P1", "P1", JAN6, "100.50"),
        _s("S-R1", "R1", JAN6, "50.00"),
    ]
    result, _, _ = _run(txns, stls)
    assert result.gross_transaction_value == Decimal("100.505")
    assert result.refund_total == Decimal("50.00")
    assert result.net_transaction_value == Decimal("50.505")


def test_decimal_never_float():
    """Decimal values in result are Decimal type, not float."""
    txns = [_t("P1", JAN5, "123.45")]
    stls = [_s("S1", "P1", JAN6, "123.45")]
    result, _, _ = _run(txns, stls)
    assert isinstance(result.gross_transaction_value, Decimal)
    assert isinstance(result.bank_settlement_total, Decimal)
    assert isinstance(result.reconciliation_variance, Decimal)

