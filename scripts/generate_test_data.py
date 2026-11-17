"""
Deterministic test data generator. Seed = 42.
Produces >=100 internal transactions and >=100 bank settlements covering all scenarios.

Run from project root:
    python scripts/generate_test_data.py
"""
import csv, random, sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

SEED = 42
random.seed(SEED)

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

def d(day, month=1, year=2024):
    return date(year, month, day)

def dt(day, month=1, year=2024, hour=10):
    return datetime(year, month, day, hour, 0, 0).isoformat()

def txn(tid, td, amount, currency="INR", ttype="payment",
        status="success", orig_ref="", merchant="M001", method="card"):
    return dict(transaction_id=tid, transaction_date=str(td),
                transaction_amount=str(amount), currency=currency,
                transaction_type=ttype, status=status,
                original_transaction_ref=orig_ref,
                merchant_id=merchant, payment_method=method)

def stl(sid, tref, sd, amount, currency="INR",
        batch="BATCH001", bank="TestBank", status="settled"):
    return dict(settlement_id=sid, transaction_ref=tref,
                settlement_amount=str(amount), currency=currency,
                settlement_date=str(sd), settlement_timestamp=dt(sd.day, sd.month, sd.year),
                bank_batch_id=batch, bank_name=bank, status=status)

T = []  # transactions
S = []  # settlements

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MANDATORY CASE 1 — TIMING_DIFFERENCE
# Jan 31 transaction; settlement Feb 1
# January run: TIMING_DIFFERENCE (outstanding)
# February run: resolved as MATCHED via carry-forward
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
T.append(txn("TXN-TIMING-JAN31", d(31), Decimal("1500.00")))
S.append(stl("STL-TIMING-FEB01", "TXN-TIMING-JAN31", d(1,2), Decimal("1500.00"), batch="BATCH-FEB"))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MANDATORY CASE 2 — ROUNDING_DIFFERENCE
# 100.505 internal vs 100.50 settled; diff=0.005 < tol=0.01 -> ROUNDING_DIFFERENCE (NOT MATCHED)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
T.append(txn("TXN-ROUNDING-001", d(5), Decimal("100.505")))
S.append(stl("STL-ROUNDING-001", "TXN-ROUNDING-001", d(6), Decimal("100.50")))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MANDATORY CASE 3A — DUPLICATE_SETTLEMENT (by identical settlement_id)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
T.append(txn("TXN-DUP-STL", d(10), Decimal("500.00")))
S.append(stl("STL-DUP-ORIG",  "TXN-DUP-STL", d(11), Decimal("500.00")))
S.append(stl("STL-DUP-ORIG",  "TXN-DUP-STL", d(11), Decimal("500.00"), batch="BATCH002"))  # same ID

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MANDATORY CASE 3B — DUPLICATE_SETTLEMENT by exact-record fingerprint (D-04)
# Different settlement_ids but identical content
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
T.append(txn("TXN-DUP-FP", d(12), Decimal("750.00")))
S.append(stl("STL-DUP-FP-A", "TXN-DUP-FP", d(13), Decimal("750.00"), batch="BATCHX"))
S.append(stl("STL-DUP-FP-B", "TXN-DUP-FP", d(13), Decimal("750.00"), batch="BATCHX"))  # same content

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MANDATORY CASE 4 — ORPHAN_REFUND
# Refund referencing a transaction_id that does not exist
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
T.append(txn("TXN-ORPHAN-REF", d(15), Decimal("200.00"),
             ttype="refund", orig_ref="TXN-DOES-NOT-EXIST"))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AGGREGATE ROUNDING (T-D) — 10 pairs each diff=0.001
# Sum = 0.010 >= tolerance 0.01 -> aggregate_exceeds_tolerance=true
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
for i in range(10):
    tid = f"TXN-AGG-{i:02d}"
    T.append(txn(tid, d(3), Decimal("50.001")))
    S.append(stl(f"STL-AGG-{i:02d}", tid, d(4), Decimal("50.00")))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MULTIPLE_SETTLEMENTS (T-A) — 3 distinct settlements sum to full amount
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
T.append(txn("TXN-MULTI", d(8), Decimal("900.00")))
S.append(stl("STL-MULTI-A", "TXN-MULTI", d(9),  Decimal("300.00"), batch="BATCH-M1"))
S.append(stl("STL-MULTI-B", "TXN-MULTI", d(9),  Decimal("300.00"), batch="BATCH-M2"))
S.append(stl("STL-MULTI-C", "TXN-MULTI", d(10), Decimal("300.00"), batch="BATCH-M3"))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PARTIAL_SETTLEMENT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
T.append(txn("TXN-PARTIAL", d(7), Decimal("1000.00")))
S.append(stl("STL-PARTIAL", "TXN-PARTIAL", d(8), Decimal("600.00")))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CURRENCY_MISMATCH
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
T.append(txn("TXN-CURR", d(14), Decimal("1000.00"), currency="INR"))
S.append(stl("STL-CURR", "TXN-CURR", d(15), Decimal("1000.00"), currency="USD"))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AMOUNT_MISMATCH (significant diff > tolerance)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
T.append(txn("TXN-MISMATCH", d(7), Decimal("800.00")))
S.append(stl("STL-MISMATCH", "TXN-MISMATCH", d(8), Decimal("750.00")))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DUPLICATE_TRANSACTION (by ID)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
T.append(txn("TXN-DUP-TXN", d(16), Decimal("600.00")))
T.append(txn("TXN-DUP-TXN", d(16), Decimal("600.00")))  # duplicate ID
S.append(stl("STL-DUP-TXN", "TXN-DUP-TXN", d(17), Decimal("600.00")))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MISSING_SETTLEMENT (transaction with no settlement, old enough to be missing)
# Use day 2 so days_since_cutoff = 29 on Jan-31 cutoff > window=2
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
for i in range(4):
    T.append(txn(f"TXN-MISSING-{i:02d}", d(2), Decimal(str(round(300+i*50, 2)))))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# UNMATCHED_SETTLEMENT (settlement with no internal transaction)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
for i in range(4):
    S.append(stl(f"STL-UNMATCHED-{i:02d}", f"TXN-GHOST-{i:02d}", d(10+i), Decimal(str(200+i*25))))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FAILED_PAYMENT (excluded from totals)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
for i in range(3):
    T.append(txn(f"TXN-FAILED-{i:02d}", d(5+i), Decimal(str(100+i*50)), status="failed"))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# VALID_REFUND
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
T.append(txn("TXN-ORIG-FOR-REFUND", d(5), Decimal("350.00")))
S.append(stl("STL-ORIG-FOR-REFUND", "TXN-ORIG-FOR-REFUND", d(6), Decimal("350.00")))
T.append(txn("TXN-VALID-REFUND", d(20), Decimal("350.00"),
             ttype="refund", orig_ref="TXN-ORIG-FOR-REFUND"))
S.append(stl("STL-VALID-REFUND", "TXN-VALID-REFUND", d(21), Decimal("350.00")))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MATCHED pairs — bulk fill to reach 100+ records
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
for i in range(60):
    amt = Decimal(str(round(random.uniform(100, 5000), 2)))
    day = random.randint(1, 25)
    tid = f"TXN-MATCH-{i:03d}"
    T.append(txn(tid, d(day), amt))
    S.append(stl(f"STL-MATCH-{i:03d}", tid, d(min(day+1,28)), amt))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Write CSV files
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TXN_FIELDS = ["transaction_id","transaction_date","transaction_amount","currency",
               "transaction_type","status","original_transaction_ref","merchant_id","payment_method"]
STL_FIELDS = ["settlement_id","transaction_ref","settlement_amount","currency",
               "settlement_date","settlement_timestamp","bank_batch_id","bank_name","status"]

tp = DATA / "internal_transactions.csv"
sp = DATA / "bank_settlements.csv"

with open(tp, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=TXN_FIELDS)
    w.writeheader()
    for row in T:
        w.writerow({k: row.get(k,"") for k in TXN_FIELDS})

with open(sp, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=STL_FIELDS)
    w.writeheader()
    for row in S:
        w.writerow({k: row.get(k,"") for k in STL_FIELDS})

print(f"Transactions: {len(T)} -> {tp}")
print(f"Settlements:  {len(S)} -> {sp}")
print()
print("Seeded scenarios:")
print("  Case 1 TIMING_DIFFERENCE:    TXN-TIMING-JAN31 (Jan31 txn, Feb1 settlement)")
print("  Case 2 ROUNDING_DIFFERENCE:  TXN-ROUNDING-001 (100.505 vs 100.50)")
print("  Case 3 DUPLICATE_SETTLEMENT: STL-DUP-ORIG appears twice (same ID)")
print("  Case 3 EXACT_RECORD_DUP:     STL-DUP-FP-A/B same content, diff IDs")
print("  Case 4 ORPHAN_REFUND:        TXN-ORPHAN-REF -> TXN-DOES-NOT-EXIST")
print("  T-A MULTIPLE_SETTLEMENTS:    TXN-MULTI x3 settlements sum to 900")
print("  T-D AGGREGATE_ROUNDING:      10 pairs each diff=0.001, sum=0.010")
print("  PARTIAL_SETTLEMENT:          TXN-PARTIAL 1000 settled for 600")
print("  CURRENCY_MISMATCH:           TXN-CURR INR vs USD")
print("  AMOUNT_MISMATCH:             TXN-MISMATCH 800 vs 750")
print("  DUPLICATE_TRANSACTION:       TXN-DUP-TXN appears twice")
print("  MISSING_SETTLEMENT:          TXN-MISSING-00..03 (old, no settlement)")
print("  UNMATCHED_SETTLEMENT:        STL-UNMATCHED-00..03 (no internal txn)")
print("  FAILED_PAYMENT:              TXN-FAILED-00..02")
print("  VALID_REFUND:                TXN-VALID-REFUND -> TXN-ORIG-FOR-REFUND")

