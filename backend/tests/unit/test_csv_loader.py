"""Tests for CSV loading and validation."""
import pytest
from app.services.csv_loader import load_transactions, load_settlements

VALID_TXN_CSV = """transaction_id,transaction_date,transaction_amount,currency,transaction_type,status,original_transaction_ref,merchant_id,payment_method
T1,2024-01-05,500.00,INR,payment,success,,M001,card
T2,2024-01-10,100.505,INR,payment,success,,M001,upi
"""

VALID_STL_CSV = """settlement_id,transaction_ref,settlement_amount,currency,settlement_date,settlement_timestamp,bank_batch_id,bank_name,status
S1,T1,500.00,INR,2024-01-06,2024-01-06T10:00:00,B001,TestBank,settled
"""

def test_load_valid_transactions():
    records, errors = load_transactions(VALID_TXN_CSV)
    assert len(errors) == 0
    assert len(records) == 2
    from decimal import Decimal
    assert records[1].transaction_amount == Decimal("100.505")

def test_load_valid_settlements():
    records, errors = load_settlements(VALID_STL_CSV)
    assert len(errors) == 0
    assert len(records) == 1

def test_invalid_amount_returns_error():
    bad = VALID_TXN_CSV.replace("500.00", "not_a_number")
    records, errors = load_transactions(bad)
    assert any("Decimal" in e["error"] or "parse" in e["error"].lower() for e in errors)

def test_refund_without_original_ref_error():
    csv = """transaction_id,transaction_date,transaction_amount,currency,transaction_type,status,original_transaction_ref,merchant_id,payment_method
R1,2024-01-05,100.00,INR,refund,success,,M001,card
"""
    records, errors = load_transactions(csv)
    # pydantic should reject refund without original_transaction_ref
    assert len(errors) > 0
