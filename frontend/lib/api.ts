const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface DiscrepancyRecord {
  record_id: string;
  transaction_id: string | null;
  settlement_id: string | null;
  settlement_ids: string[] | null;
  classification: string;
  transaction_amount: string | null;
  settlement_amount: string | null;
  individual_difference: string | null;
  currency: string;
  period_label: string;
  rule_id: string;
  duplicate_fingerprint: string | null;
  resolution_note: string | null;
}

export interface RunSummary {
  run_id: string;
  period_label: string;
  as_of_date: string;
  run_status: string;
  run_timestamp: string;
  matched_count: number;
  discrepancy_count: number;
  reconciliation_variance: string;
  aggregate_exceeds_tolerance: boolean;
}

export interface ReconciliationRun {
  run_id: string;
  period_label: string;
  as_of_date: string;
  run_status: string;
  run_timestamp: string;
  configuration_snapshot: { rounding_tolerance: string; settlement_window: number };
  gross_transaction_value: string;
  refund_total: string;
  net_transaction_value: string;
  bank_settlement_total: string;
  outstanding_amount: string;
  reconciliation_variance: string;
  aggregate_rounding_difference: string;
  aggregate_exceeds_tolerance: boolean;
  total_transactions: number;
  total_settlements: number;
  matched_count: number;
  discrepancy_count: number;
  discrepancy_list: DiscrepancyRecord[];
  resolved_carried_forward: Array<{ transaction_id: string; classification: string; originating_period_label: string }>;
}

export interface ReconcileRequest {
  period_label: string;
  as_of_date: string;
  transactions_csv: string;
  settlements_csv: string;
  rounding_tolerance?: string;
  settlement_window?: number;
}

export async function listRuns(): Promise<{ runs: RunSummary[] }> {
  const r = await fetch(`${API}/api/runs`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function getRun(runId: string): Promise<ReconciliationRun> {
  const r = await fetch(`${API}/api/runs/${runId}`);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

export async function reconcile(req: ReconcileRequest): Promise<ReconciliationRun> {
  const r = await fetch(`${API}/api/reconcile`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(JSON.stringify(err.detail || err));
  }
  return r.json();
}

export function exportCsvUrl(runId: string): string {
  return `${API}/api/runs/${runId}/export/csv`;
}

/** Format a Decimal string for display — 2dp with currency. */
export function fmt(amount: string | null | undefined, currency = ""): string {
  if (!amount) return "—";
  const parts = amount.split(".");
  const intPart = parts[0];
  const decPart = (parts[1] || "").padEnd(2, "0").slice(0, 2);
  return currency ? `₹${intPart}.${decPart}` : `${intPart}.${decPart}`;
}

export const CLASSIFICATION_COLORS: Record<string, string> = {
  MATCHED: "bg-green-100 text-green-800",
  TIMING_DIFFERENCE: "bg-yellow-100 text-yellow-800",
  MISSING_SETTLEMENT: "bg-red-100 text-red-800",
  UNMATCHED_SETTLEMENT: "bg-orange-100 text-orange-800",
  PARTIAL_SETTLEMENT: "bg-amber-100 text-amber-800",
  MULTIPLE_SETTLEMENTS: "bg-blue-100 text-blue-800",
  AMOUNT_MISMATCH: "bg-red-100 text-red-800",
  ROUNDING_DIFFERENCE: "bg-purple-100 text-purple-800",
  CURRENCY_MISMATCH: "bg-pink-100 text-pink-800",
  DUPLICATE_TRANSACTION: "bg-gray-100 text-gray-700",
  DUPLICATE_SETTLEMENT: "bg-gray-100 text-gray-700",
  ORPHAN_REFUND: "bg-rose-100 text-rose-800",
};
