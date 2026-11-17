"""
Duplicate detection.
D-01: DUPLICATE_TRANSACTION by identical transaction_id
D-02: DUPLICATE_TRANSACTION by exact-record fingerprint
D-03: DUPLICATE_SETTLEMENT by identical settlement_id
D-04: DUPLICATE_SETTLEMENT by exact-record fingerprint (settlement_id EXCLUDED)
D-05: Shared transaction_ref with distinct settlement_ids -> MULTIPLE_SETTLEMENTS, not duplicate
"""
from typing import List, Tuple, Dict
from app.models.domain import InternalTransaction, BankSettlement


def _txn_fp(t: InternalTransaction) -> str:
    return "|".join([
        t.transaction_id, str(t.transaction_date),
        str(t.transaction_amount), t.currency,
        t.transaction_type, t.merchant_id,
    ])


def _stl_fp(s: BankSettlement) -> str:
    # settlement_id intentionally excluded so records with same content but
    # different IDs are caught as exact-record duplicates (D-04)
    return "|".join([
        s.transaction_ref, str(s.settlement_amount),
        s.currency, str(s.settlement_timestamp), s.bank_batch_id,
    ])


def mark_duplicate_transactions(
    transactions: List[InternalTransaction],
) -> Tuple[List[InternalTransaction], List[dict]]:
    """Returns (originals, duplicate_info_list)."""
    seen_ids: Dict[str, bool] = {}
    seen_fps: Dict[str, bool] = {}
    originals, duplicates = [], []
    for t in transactions:
        if t.transaction_id in seen_ids:
            duplicates.append({"record": t, "classification": "DUPLICATE_TRANSACTION",
                                "fingerprint": f"transaction_id:{t.transaction_id}", "rule": "D-01"})
            continue
        fp = _txn_fp(t)
        if fp in seen_fps:
            duplicates.append({"record": t, "classification": "DUPLICATE_TRANSACTION",
                                "fingerprint": f"exact_record:{fp}", "rule": "D-02"})
            continue
        seen_ids[t.transaction_id] = True
        seen_fps[fp] = True
        originals.append(t)
    return originals, duplicates


def mark_duplicate_settlements(
    settlements: List[BankSettlement],
) -> Tuple[List[BankSettlement], List[dict]]:
    """Returns (originals, duplicate_info_list)."""
    seen_ids: Dict[str, bool] = {}
    seen_fps: Dict[str, bool] = {}
    originals, duplicates = [], []
    for s in settlements:
        if s.settlement_id in seen_ids:
            duplicates.append({"record": s, "classification": "DUPLICATE_SETTLEMENT",
                                "fingerprint": f"settlement_id:{s.settlement_id}", "rule": "D-03"})
            continue
        fp = _stl_fp(s)
        if fp in seen_fps:
            duplicates.append({"record": s, "classification": "DUPLICATE_SETTLEMENT",
                                "fingerprint": f"exact_record:{fp}", "rule": "D-04"})
            continue
        seen_ids[s.settlement_id] = True
        seen_fps[fp] = True
        originals.append(s)
    return originals, duplicates
