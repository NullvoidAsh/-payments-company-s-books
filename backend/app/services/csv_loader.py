"""Parse and validate CSV files into domain models."""
import csv
import io
from decimal import InvalidOperation
from datetime import datetime
from typing import List, Tuple
from app.models.domain import InternalTransaction, BankSettlement


def load_transactions(content: str) -> Tuple[List[InternalTransaction], List[dict]]:
    """Returns (valid_records, errors). Errors contain row, field, message."""
    records, errors = [], []
    reader = csv.DictReader(io.StringIO(content))
    required = {"transaction_id","transaction_date","transaction_amount","currency",
                 "transaction_type","status","merchant_id","payment_method"}
    for i, row in enumerate(reader, start=2):
        missing = required - set(row.keys())
        if missing:
            errors.append({"row": i, "field": ",".join(missing), "error": "Missing required field"})
            continue
        try:
            rec = InternalTransaction(
                transaction_id=row["transaction_id"].strip(),
                transaction_date=row["transaction_date"].strip(),
                transaction_amount=row["transaction_amount"].strip(),
                currency=row["currency"].strip().upper(),
                transaction_type=row["transaction_type"].strip().lower(),
                status=row["status"].strip().lower(),
                original_transaction_ref=row.get("original_transaction_ref","").strip() or None,
                merchant_id=row.get("merchant_id","").strip(),
                payment_method=row.get("payment_method","").strip(),
            )
            records.append(rec)
        except Exception as e:
            errors.append({"row": i, "field": "schema", "error": str(e)})
    return records, errors


def load_settlements(content: str) -> Tuple[List[BankSettlement], List[dict]]:
    records, errors = [], []
    reader = csv.DictReader(io.StringIO(content))
    required = {"settlement_id","transaction_ref","settlement_amount","currency",
                 "settlement_date","settlement_timestamp","bank_batch_id","bank_name","status"}
    for i, row in enumerate(reader, start=2):
        missing = required - set(row.keys())
        if missing:
            errors.append({"row": i, "field": ",".join(missing), "error": "Missing required field"})
            continue
        try:
            rec = BankSettlement(
                settlement_id=row["settlement_id"].strip(),
                transaction_ref=row["transaction_ref"].strip(),
                settlement_amount=row["settlement_amount"].strip(),
                currency=row["currency"].strip().upper(),
                settlement_date=row["settlement_date"].strip(),
                settlement_timestamp=row["settlement_timestamp"].strip(),
                bank_batch_id=row["bank_batch_id"].strip(),
                bank_name=row["bank_name"].strip(),
                status=row["status"].strip().lower(),
            )
            records.append(rec)
        except Exception as e:
            errors.append({"row": i, "field": "schema", "error": str(e)})
    return records, errors
