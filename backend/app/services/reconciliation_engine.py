"""
Core reconciliation engine.
Matching key: InternalTransaction.transaction_id == BankSettlement.transaction_ref
as_of_date: explicit cutoff date — never datetime.now()

Classification priority:
  1. Duplicate detection (pre-processing)
  2. Failed transaction exclusion; settlements for failed txns -> UNMATCHED_SETTLEMENT with note
  3. Carry-forward outstanding entries matched first
  4. Orphan refund check before amount matching
  5. TIMING_DIFFERENCE: days_since_cutoff <= settlement_window, no settlement found
  6. MISSING_SETTLEMENT: days_since_cutoff > settlement_window, no settlement found
  7. CURRENCY_MISMATCH: currencies differ
  8. MATCHED: abs_diff == 0
  9. ROUNDING_DIFFERENCE: 0 < diff <= tolerance  (NEVER classified as MATCHED)
  10. PARTIAL_SETTLEMENT: diff > tolerance, settled < amount
  11. AMOUNT_MISMATCH: diff > tolerance, other pattern
  12. MULTIPLE_SETTLEMENTS: 2+ distinct-id settlements; sums Decimal; determines outcome
  13. UNMATCHED_SETTLEMENT: no internal transaction found
"""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import List, Dict, Optional, Tuple, Set
import uuid

from app.models.domain import (
    InternalTransaction, BankSettlement, DiscrepancyRecord,
    CarryForwardEntry, ReconciliationResult, SystemConfig,
)
from app.services.duplicate_detector import mark_duplicate_transactions, mark_duplicate_settlements

ZERO = Decimal("0")


def run_reconciliation(
    period_label: str,
    as_of_date: date,
    transactions: List[InternalTransaction],
    settlements: List[BankSettlement],
    carry_forward_entries: List[CarryForwardEntry],
    config: SystemConfig,
    all_known_payment_ids: Optional[Set[str]] = None,
) -> Tuple[ReconciliationResult, List[CarryForwardEntry], List[CarryForwardEntry]]:
    """
    Returns (result, new_cf_entries, updated_cf_entries).
    new_cf_entries: TIMING_DIFFERENCE items to persist as new carry-forward rows.
    updated_cf_entries: existing carry-forward rows whose status changed.
    """
    run_id = str(uuid.uuid4())
    run_ts = datetime.utcnow().isoformat()
    tol = config.rounding_tolerance
    win = config.settlement_window

    known_payment_ids: Set[str] = set(all_known_payment_ids or set())
    discrepancies: List[DiscrepancyRecord] = []
    new_cf: List[CarryForwardEntry] = []
    updated_cf: List[CarryForwardEntry] = []
    resolved_cf: List[dict] = []

    # Step 1: duplicate detection
    orig_txns, dup_txns = mark_duplicate_transactions(transactions)
    orig_stls, dup_stls = mark_duplicate_settlements(settlements)

    for d in dup_txns:
        r = d["record"]
        discrepancies.append(DiscrepancyRecord(
            transaction_id=r.transaction_id,
            classification="DUPLICATE_TRANSACTION",
            transaction_amount=r.transaction_amount,
            currency=r.currency, period_label=period_label,
            rule_id=d["rule"], duplicate_fingerprint=d["fingerprint"],
            resolution_note="Duplicate excluded from matching and totals",
        ))
    for d in dup_stls:
        r = d["record"]
        discrepancies.append(DiscrepancyRecord(
            settlement_id=r.settlement_id,
            classification="DUPLICATE_SETTLEMENT",
            settlement_amount=r.settlement_amount,
            currency=r.currency, period_label=period_label,
            rule_id=d["rule"], duplicate_fingerprint=d["fingerprint"],
            resolution_note="Duplicate excluded from matching and totals",
        ))

    # Step 1b: filter settlements to those on or before as_of_date (period scope)
    # Settlements after as_of_date are for future periods — not included in this run
    orig_stls = [s for s in orig_stls if s.settlement_date <= as_of_date]

    # Step 2: separate failed transactions
    failed_ids = {t.transaction_id for t in orig_txns if t.status == "failed"}
    active_txns = [t for t in orig_txns if t.status != "failed"]

    # Build settlement pool; flag settlements for failed transactions
    settlement_pool: List[BankSettlement] = []
    for s in orig_stls:
        if s.transaction_ref in failed_ids:
            discrepancies.append(DiscrepancyRecord(
                settlement_id=s.settlement_id,
                classification="UNMATCHED_SETTLEMENT",
                settlement_amount=s.settlement_amount,
                currency=s.currency, period_label=period_label,
                rule_id="R-08b",
                resolution_note=f"Settlement for failed transaction {s.transaction_ref}",
            ))
        else:
            settlement_pool.append(s)

    # Step 3: index settlements by transaction_ref
    stl_index: Dict[str, List[BankSettlement]] = defaultdict(list)
    for s in settlement_pool:
        stl_index[s.transaction_ref].append(s)

    # Step 4: collect known payment IDs from current period
    for t in orig_txns:
        if t.transaction_type == "payment":
            known_payment_ids.add(t.transaction_id)

    # Step 5: carry-forward matching
    txn_lookup = {t.transaction_id: t for t in transactions}
    for entry in carry_forward_entries:
        group = stl_index.get(entry.transaction_id, [])
        orig_txn = txn_lookup.get(entry.transaction_id)
        txn_amount = (orig_txn.transaction_amount if orig_txn
                      else entry.transaction_amount)
        txn_currency = (orig_txn.currency if orig_txn
                        else entry.transaction_currency or "INR")

        if group:
            group = list(group)  # copy before mutating the index
            del stl_index[entry.transaction_id]  # remove entire key
            outcome = _classify_group(
                entry.transaction_id, txn_amount, txn_currency,
                group, tol, period_label,
            )
            prefix = f"Carry-forward resolved from {entry.originating_period_label}. "
            outcome.resolution_note = prefix + (outcome.resolution_note or "")
            discrepancies.append(outcome)
            entry.status = "resolved"
            entry.resolved_period_label = period_label
            entry.last_updated_at = datetime.utcnow().isoformat()
            updated_cf.append(entry)
            resolved_cf.append({
                "entry_id": entry.entry_id,
                "transaction_id": entry.transaction_id,
                "originating_period_label": entry.originating_period_label,
                "resolved_period_label": period_label,
                "classification": outcome.classification,
            })
        else:
            days = (as_of_date - date.fromisoformat(entry.created_as_of_date)).days
            entry.outstanding_days = days
            entry.last_updated_at = datetime.utcnow().isoformat()
            if days > win:
                entry.status = "escalated"
                discrepancies.append(DiscrepancyRecord(
                    transaction_id=entry.transaction_id,
                    classification="MISSING_SETTLEMENT",
                    transaction_amount=txn_amount,
                    currency=txn_currency,
                    period_label=period_label, rule_id="R-06-cf",
                    resolution_note=f"Escalated from carry-forward: {days} days since {entry.originating_period_label}",
                ))
            updated_cf.append(entry)

    # Step 6: match active transactions
    for txn in active_txns:
        # Orphan refund check
        if txn.transaction_type == "refund":
            if not txn.original_transaction_ref or txn.original_transaction_ref not in known_payment_ids:
                discrepancies.append(DiscrepancyRecord(
                    transaction_id=txn.transaction_id,
                    classification="ORPHAN_REFUND",
                    transaction_amount=txn.transaction_amount,
                    currency=txn.currency, period_label=period_label,
                    rule_id="R-09",
                    resolution_note=f"original_transaction_ref '{txn.original_transaction_ref}' not found in known payments",
                ))
                continue

        group = stl_index.pop(txn.transaction_id, [])
        if group:
            outcome = _classify_group(
                txn.transaction_id, txn.transaction_amount, txn.currency,
                group, tol, period_label,
            )
            discrepancies.append(outcome)
        else:
            days = (as_of_date - txn.transaction_date).days
            if days <= win:
                discrepancies.append(DiscrepancyRecord(
                    transaction_id=txn.transaction_id,
                    classification="TIMING_DIFFERENCE",
                    transaction_amount=txn.transaction_amount,
                    currency=txn.currency, period_label=period_label,
                    rule_id="R-05",
                    resolution_note=f"Date {txn.transaction_date}; cutoff {as_of_date}; {days}d <= window {win}d",
                ))
                new_cf.append(CarryForwardEntry(
                    transaction_id=txn.transaction_id,
                    originating_period_label=period_label,
                    outstanding_days=days, status="outstanding",
                    transaction_amount=txn.transaction_amount,
                    transaction_currency=txn.currency,
                    created_as_of_date=as_of_date.isoformat(),
                    last_updated_at=datetime.utcnow().isoformat(),
                    reconciliation_run_id=run_id,
                ))
            else:
                discrepancies.append(DiscrepancyRecord(
                    transaction_id=txn.transaction_id,
                    classification="MISSING_SETTLEMENT",
                    transaction_amount=txn.transaction_amount,
                    currency=txn.currency, period_label=period_label,
                    rule_id="R-06",
                    resolution_note=f"{days}d since cutoff > window {win}d",
                ))

    # Step 7: remaining unmatched settlements
    for ref, group in stl_index.items():
        for s in group:
            discrepancies.append(DiscrepancyRecord(
                settlement_id=s.settlement_id,
                classification="UNMATCHED_SETTLEMENT",
                settlement_amount=s.settlement_amount,
                currency=s.currency, period_label=period_label,
                rule_id="R-07",
                resolution_note=f"No internal transaction for ref {ref}",
            ))

    # Step 8: financial totals
    dup_txn_ids = {d["record"].transaction_id for d in dup_txns}
    # Use Python id() to track the exact duplicate objects — avoids excluding originals
    # that happen to share the same settlement_id as their duplicate
    dup_stl_objects = {id(d["record"]) for d in dup_stls}

    gross = sum(
        (t.transaction_amount for t in orig_txns
         if t.transaction_type == "payment" and t.status != "failed"
         and t.transaction_id not in dup_txn_ids), ZERO)
    refund_total = sum(
        (t.transaction_amount for t in orig_txns
         if t.transaction_type == "refund" and t.transaction_id not in dup_txn_ids), ZERO)
    net = gross - refund_total
    bank_total = sum(
        (s.settlement_amount for s in orig_stls), ZERO)  # orig_stls already excludes duplicates
    outstanding = sum(
        (d.transaction_amount for d in discrepancies
         if d.classification in ("TIMING_DIFFERENCE", "MISSING_SETTLEMENT")
         and d.transaction_amount), ZERO)
    variance = net - bank_total
    agg_rounding = sum(
        (d.individual_difference for d in discrepancies
         if d.classification == "ROUNDING_DIFFERENCE" and d.individual_difference), ZERO)
    exceeds = agg_rounding >= tol

    matched = sum(1 for d in discrepancies if d.classification == "MATCHED")
    disc_count = sum(1 for d in discrepancies if d.classification != "MATCHED")

    result = ReconciliationResult(
        run_id=run_id, period_label=period_label,
        as_of_date=as_of_date.isoformat(),
        run_status="completed", run_timestamp=run_ts,
        configuration_snapshot={"rounding_tolerance": str(tol), "settlement_window": win},
        gross_transaction_value=gross, refund_total=refund_total,
        net_transaction_value=net, bank_settlement_total=bank_total,
        outstanding_amount=outstanding, reconciliation_variance=variance,
        aggregate_rounding_difference=agg_rounding,
        aggregate_exceeds_tolerance=exceeds,
        total_transactions=len(transactions), total_settlements=len(settlements),
        matched_count=matched, discrepancy_count=disc_count,
        discrepancy_list=discrepancies, resolved_carried_forward=resolved_cf,
    )
    return result, new_cf, updated_cf


def _classify_group(
    transaction_id: str,
    txn_amount: Optional[Decimal],
    txn_currency: str,
    settlements: List[BankSettlement],
    tol: Decimal,
    period_label: str,
) -> DiscrepancyRecord:
    """Classify one transaction against 1+ settlements."""
    is_multi = len(settlements) > 1
    rule = "R-04" if is_multi else "R-03"
    all_ids = [s.settlement_id for s in settlements]

    # Currency mismatch
    if any(s.currency != txn_currency for s in settlements):
        return DiscrepancyRecord(
            transaction_id=transaction_id,
            settlement_id=settlements[0].settlement_id,
            classification="CURRENCY_MISMATCH",
            transaction_amount=txn_amount,
            settlement_amount=settlements[0].settlement_amount,
            currency=txn_currency, period_label=period_label, rule_id="R-02",
            resolution_note=f"Currency mismatch: internal={txn_currency} bank={settlements[0].currency}",
        )

    total_settled = sum((s.settlement_amount for s in settlements), ZERO)

    if txn_amount is None:
        return DiscrepancyRecord(
            transaction_id=transaction_id, settlement_id=settlements[0].settlement_id,
            classification="MATCHED", currency=txn_currency,
            period_label=period_label, rule_id=rule,
        )

    diff = abs(txn_amount - total_settled)

    if diff == ZERO:
        cls = "MATCHED"
        note = None
    elif diff <= tol:
        cls = "ROUNDING_DIFFERENCE"  # NEVER MATCHED even if tiny
        note = f"Diff {diff} within tolerance {tol}"
    elif total_settled < txn_amount:
        cls = "PARTIAL_SETTLEMENT"
        note = f"Settled {total_settled} < {txn_amount}"
    else:
        cls = "AMOUNT_MISMATCH"
        note = f"Settled {total_settled} != {txn_amount}"

    # For multiple settlements record relationship regardless of financial outcome
    if is_multi:
        ids_str = ", ".join(all_ids)
        note = f"MULTIPLE_SETTLEMENTS [{ids_str}] total={total_settled}. " + (note or cls)
        # Keep financial classification; annotate as MULTIPLE_SETTLEMENTS only when fully matched
        if cls == "MATCHED":
            cls = "MULTIPLE_SETTLEMENTS"
            note = f"MULTIPLE_SETTLEMENTS [{ids_str}] total={total_settled} = {txn_amount} (fully settled)"

    return DiscrepancyRecord(
        transaction_id=transaction_id,
        settlement_id=settlements[0].settlement_id,
        settlement_ids=all_ids if is_multi else None,
        classification=cls,
        transaction_amount=txn_amount, settlement_amount=total_settled,
        individual_difference=diff if diff > ZERO else None,
        currency=txn_currency, period_label=period_label, rule_id=rule,
        resolution_note=note,
    )




