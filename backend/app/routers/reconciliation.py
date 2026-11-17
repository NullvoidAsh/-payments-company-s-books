"""
Reconciliation API routes.
All monetary amounts returned as strings (never JSON numbers).
"""
import csv
import io
import json
from datetime import date
from decimal import Decimal
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.models.domain import SystemConfig
from app.services import database as db
from app.services.csv_loader import load_transactions, load_settlements
from app.services.reconciliation_engine import run_reconciliation

router = APIRouter()

# ── helpers ───────────────────────────────────────────────────────────────────

def _dec(v) -> str:
    """Safely convert to string, handling None."""
    if v is None:
        return None
    return str(v)


def _serialize_result(result) -> dict:
    """Convert ReconciliationResult to JSON-safe dict (Decimals as strings)."""
    discs = []
    for d in result.discrepancy_list:
        discs.append({
            "record_id": d.record_id,
            "transaction_id": d.transaction_id,
            "settlement_id": d.settlement_id,
            "settlement_ids": d.settlement_ids,
            "classification": d.classification,
            "transaction_amount": _dec(d.transaction_amount),
            "settlement_amount": _dec(d.settlement_amount),
            "individual_difference": _dec(d.individual_difference),
            "currency": d.currency,
            "period_label": d.period_label,
            "rule_id": d.rule_id,
            "duplicate_fingerprint": d.duplicate_fingerprint,
            "resolution_note": d.resolution_note,
        })
    return {
        "run_id": result.run_id,
        "period_label": result.period_label,
        "as_of_date": result.as_of_date,
        "run_status": result.run_status,
        "run_timestamp": result.run_timestamp,
        "configuration_snapshot": result.configuration_snapshot,
        "gross_transaction_value": _dec(result.gross_transaction_value),
        "refund_total": _dec(result.refund_total),
        "net_transaction_value": _dec(result.net_transaction_value),
        "bank_settlement_total": _dec(result.bank_settlement_total),
        "outstanding_amount": _dec(result.outstanding_amount),
        "reconciliation_variance": _dec(result.reconciliation_variance),
        "aggregate_rounding_difference": _dec(result.aggregate_rounding_difference),
        "aggregate_exceeds_tolerance": result.aggregate_exceeds_tolerance,
        "total_transactions": result.total_transactions,
        "total_settlements": result.total_settlements,
        "matched_count": result.matched_count,
        "discrepancy_count": result.discrepancy_count,
        "discrepancy_list": discs,
        "resolved_carried_forward": result.resolved_carried_forward,
    }


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.get("/runs")
def list_runs():
    """List all reconciliation runs (most recent first)."""
    runs = db.list_runs()
    for r in runs:
        r["aggregate_exceeds_tolerance"] = bool(r.get("aggregate_exceeds_tolerance"))
    return {"runs": runs}


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    run["aggregate_exceeds_tolerance"] = bool(run.get("aggregate_exceeds_tolerance"))
    return run


@router.get("/runs/{run_id}/export/csv")
def export_csv(run_id: str):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    output = io.StringIO()
    fields = ["record_id","transaction_id","settlement_id","classification",
              "transaction_amount","settlement_amount","individual_difference",
              "currency","period_label","rule_id","duplicate_fingerprint","resolution_note"]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for d in run["discrepancy_list"]:
        writer.writerow(d)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=reconciliation_{run_id}.csv"},
    )


class ReconcileRequest(BaseModel):
    period_label: str           # e.g. "2024-01"
    as_of_date: str             # ISO date, e.g. "2024-01-31"
    transactions_csv: str       # raw CSV content
    settlements_csv: str        # raw CSV content
    rounding_tolerance: Optional[str] = "0.01"
    settlement_window: Optional[int] = 2


@router.post("/reconcile")
def reconcile(req: ReconcileRequest):
    """
    Run reconciliation. Accepts raw CSV strings + config.
    Returns full ReconciliationResult with all amounts as strings.
    """
    # Load and validate CSVs
    txns, txn_errors = load_transactions(req.transactions_csv)
    stls, stl_errors = load_settlements(req.settlements_csv)

    if txn_errors or stl_errors:
        raise HTTPException(status_code=422, detail={
            "transaction_errors": txn_errors,
            "settlement_errors": stl_errors,
        })

    try:
        as_of = date.fromisoformat(req.as_of_date)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid as_of_date: {req.as_of_date}")

    config = SystemConfig(
        rounding_tolerance=Decimal(req.rounding_tolerance),
        settlement_window=req.settlement_window,
    )

    # Load outstanding carry-forward entries
    cf_rows = db.load_outstanding_cf()
    from app.models.domain import CarryForwardEntry
    cf_entries = []
    for row in cf_rows:
        cf_entries.append(CarryForwardEntry(
            entry_id=row["entry_id"],
            transaction_id=row["transaction_id"],
            originating_period_label=row["originating_period_label"],
            resolved_period_label=row.get("resolved_period_label"),
            outstanding_days=row["outstanding_days"],
            status=row["status"],
            created_as_of_date=row["created_as_of_date"],
            last_updated_at=row["last_updated_at"],
            reconciliation_run_id=row["reconciliation_run_id"],
        ))

    result, new_cf, updated_cf = run_reconciliation(
        period_label=req.period_label,
        as_of_date=as_of,
        transactions=txns,
        settlements=stls,
        carry_forward_entries=cf_entries,
        config=config,
    )

    # Persist
    db.save_run(result)
    db.save_carry_forward(new_cf)
    db.save_carry_forward(updated_cf)

    return _serialize_result(result)


@router.get("/config")
def get_config():
    cfg = db.get_config()
    return {
        "rounding_tolerance": cfg["rounding_tolerance"],
        "settlement_window": cfg["settlement_window"],
        "supported_currencies": json.loads(cfg["supported_currencies"]),
    }
