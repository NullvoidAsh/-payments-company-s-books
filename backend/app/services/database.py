"""SQLite persistence layer. Amounts stored as TEXT, never REAL."""
import sqlite3
import json
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime

DB_PATH = Path(__file__).parent.parent.parent / "payment_recon.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    rounding_tolerance TEXT NOT NULL DEFAULT '0.01',
    settlement_window INTEGER NOT NULL DEFAULT 2,
    supported_currencies TEXT NOT NULL DEFAULT '["INR","USD","EUR"]',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reconciliation_runs (
    run_id TEXT PRIMARY KEY,
    period_label TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    run_status TEXT NOT NULL,
    run_timestamp TEXT NOT NULL,
    configuration_snapshot TEXT NOT NULL,
    gross_transaction_value TEXT,
    refund_total TEXT,
    net_transaction_value TEXT,
    bank_settlement_total TEXT,
    outstanding_amount TEXT,
    reconciliation_variance TEXT,
    aggregate_rounding_difference TEXT,
    aggregate_exceeds_tolerance INTEGER,
    total_transactions INTEGER,
    total_settlements INTEGER,
    matched_count INTEGER,
    discrepancy_count INTEGER,
    error_detail TEXT,
    completed_at TEXT,
    is_immutable INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS discrepancy_records (
    record_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    transaction_id TEXT,
    settlement_id TEXT,
    settlement_ids TEXT,
    classification TEXT NOT NULL,
    transaction_amount TEXT,
    settlement_amount TEXT,
    individual_difference TEXT,
    currency TEXT NOT NULL,
    period_label TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    duplicate_fingerprint TEXT,
    resolution_note TEXT,
    FOREIGN KEY (run_id) REFERENCES reconciliation_runs(run_id)
);
CREATE TABLE IF NOT EXISTS carry_forward_entries (
    entry_id TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL,
    originating_period_label TEXT NOT NULL,
    resolved_period_label TEXT,
    outstanding_days INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    transaction_amount TEXT,
    transaction_currency TEXT DEFAULT 'INR',
    created_as_of_date TEXT NOT NULL,
    last_updated_at TEXT NOT NULL,
    reconciliation_run_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_period ON reconciliation_runs(period_label);
CREATE INDEX IF NOT EXISTS idx_dr_run ON discrepancy_records(run_id);
CREATE INDEX IF NOT EXISTS idx_cf_status ON carry_forward_entries(status);
CREATE INDEX IF NOT EXISTS idx_cf_period ON carry_forward_entries(originating_period_label);
"""


@contextmanager
def get_conn(path: Path = None):
    p = path or DB_PATH
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(path: Path = None):
    with get_conn(path) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT OR IGNORE INTO config (id,rounding_tolerance,settlement_window,supported_currencies,updated_at) VALUES (1,'0.01',2,'[\"INR\",\"USD\",\"EUR\"]',?)",
            (datetime.utcnow().isoformat(),)
        )


def get_config(path: Path = None) -> dict:
    with get_conn(path) as conn:
        row = conn.execute("SELECT * FROM config WHERE id=1").fetchone()
        if row:
            return dict(row)
        return {"rounding_tolerance": "0.01", "settlement_window": 2,
                "supported_currencies": '["INR","USD","EUR"]'}


def save_run(result, path: Path = None):
    """Persist a ReconciliationResult to SQLite."""
    import json
    with get_conn(path) as conn:
        conn.execute("""
            INSERT INTO reconciliation_runs
            (run_id,period_label,as_of_date,run_status,run_timestamp,
             configuration_snapshot,gross_transaction_value,refund_total,
             net_transaction_value,bank_settlement_total,outstanding_amount,
             reconciliation_variance,aggregate_rounding_difference,
             aggregate_exceeds_tolerance,total_transactions,total_settlements,
             matched_count,discrepancy_count,error_detail,completed_at,is_immutable)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
        """, (
            result.run_id, result.period_label, result.as_of_date,
            result.run_status, result.run_timestamp,
            json.dumps(result.configuration_snapshot),
            str(result.gross_transaction_value), str(result.refund_total),
            str(result.net_transaction_value), str(result.bank_settlement_total),
            str(result.outstanding_amount), str(result.reconciliation_variance),
            str(result.aggregate_rounding_difference),
            1 if result.aggregate_exceeds_tolerance else 0,
            result.total_transactions, result.total_settlements,
            result.matched_count, result.discrepancy_count,
            result.error_detail, datetime.utcnow().isoformat(),
        ))
        for d in result.discrepancy_list:
            conn.execute("""
                INSERT INTO discrepancy_records
                (record_id,run_id,transaction_id,settlement_id,settlement_ids,
                 classification,transaction_amount,settlement_amount,
                 individual_difference,currency,period_label,rule_id,
                 duplicate_fingerprint,resolution_note)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                d.record_id, result.run_id,
                d.transaction_id, d.settlement_id,
                json.dumps(d.settlement_ids) if d.settlement_ids else None,
                d.classification,
                str(d.transaction_amount) if d.transaction_amount is not None else None,
                str(d.settlement_amount) if d.settlement_amount is not None else None,
                str(d.individual_difference) if d.individual_difference is not None else None,
                d.currency, d.period_label, d.rule_id,
                d.duplicate_fingerprint, d.resolution_note,
            ))


def save_carry_forward(entries, path: Path = None):
    with get_conn(path) as conn:
        for e in entries:
            conn.execute("""
                INSERT OR REPLACE INTO carry_forward_entries
                (entry_id,transaction_id,originating_period_label,resolved_period_label,
                 outstanding_days,status,transaction_amount,transaction_currency,
                 created_as_of_date,last_updated_at,reconciliation_run_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (e.entry_id, e.transaction_id, e.originating_period_label,
                  e.resolved_period_label, e.outstanding_days, e.status,
                  str(e.transaction_amount) if e.transaction_amount else None,
                  e.transaction_currency or "INR",
                  e.created_as_of_date, e.last_updated_at, e.reconciliation_run_id))


def load_outstanding_cf(path: Path = None):
    with get_conn(path) as conn:
        rows = conn.execute(
            "SELECT * FROM carry_forward_entries WHERE status='outstanding'"
        ).fetchall()
        return [dict(r) for r in rows]


def list_runs(path: Path = None):
    with get_conn(path) as conn:
        rows = conn.execute(
            "SELECT run_id,period_label,as_of_date,run_status,run_timestamp,"
            "matched_count,discrepancy_count,reconciliation_variance,"
            "aggregate_exceeds_tolerance FROM reconciliation_runs ORDER BY run_timestamp DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_run(run_id: str, path: Path = None):
    with get_conn(path) as conn:
        run = conn.execute(
            "SELECT * FROM reconciliation_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        if not run:
            return None
        run_dict = dict(run)
        discs = conn.execute(
            "SELECT * FROM discrepancy_records WHERE run_id=?", (run_id,)
        ).fetchall()
        run_dict["discrepancy_list"] = [dict(d) for d in discs]
        return run_dict

