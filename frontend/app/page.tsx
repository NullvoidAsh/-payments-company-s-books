"use client";
import { useState, useEffect } from "react";
import { listRuns, getRun, reconcile, exportCsvUrl, fmt, CLASSIFICATION_COLORS, RunSummary, ReconciliationRun, ReconcileRequest } from "@/lib/api";

export default function Home() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedRun, setSelectedRun] = useState<ReconciliationRun | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"dashboard" | "run">("dashboard");

  // Form state
  const [periodLabel, setPeriodLabel] = useState("2024-01");
  const [asOfDate, setAsOfDate] = useState("2024-01-31");
  const [txnCsv, setTxnCsv] = useState("");
  const [stlCsv, setStlCsv] = useState("");
  const [tolerance, setTolerance] = useState("0.01");
  const [window_, setWindow] = useState("2");
  const [filterCls, setFilterCls] = useState("ALL");
  const [runMsg, setRunMsg] = useState("");

  useEffect(() => { fetchRuns(); }, []);

  async function fetchRuns() {
    try {
      const data = await listRuns();
      setRuns(data.runs);
    } catch (e: unknown) {
      setError(String(e));
    }
  }

  async function fetchRun(id: string) {
    setLoading(true);
    setError(null);
    try {
      const run = await getRun(id);
      setSelectedRun(run);
      setView("run");
    } catch (e: unknown) { setError(String(e)); }
    finally { setLoading(false); }
  }

  async function handleFileLoad(setter: (s: string) => void, file: File) {
    const text = await file.text();
    setter(text);
  }

  async function handleReconcile() {
    if (!txnCsv || !stlCsv) { setError("Upload both CSV files first."); return; }
    setLoading(true); setError(null); setRunMsg("");
    try {
      const req: ReconcileRequest = {
        period_label: periodLabel, as_of_date: asOfDate,
        transactions_csv: txnCsv, settlements_csv: stlCsv,
        rounding_tolerance: tolerance, settlement_window: parseInt(window_),
      };
      const result = await reconcile(req);
      setSelectedRun(result);
      setView("run");
      setRunMsg(`Run ${result.run_id.slice(0,8)}… completed.`);
      await fetchRuns();
    } catch (e: unknown) { setError(String(e)); }
    finally { setLoading(false); }
  }

  // Discrepancy breakdown by classification
  const breakdown = selectedRun
    ? Object.entries(
        selectedRun.discrepancy_list.reduce((acc, d) => {
          acc[d.classification] = (acc[d.classification] || 0) + 1;
          return acc;
        }, {} as Record<string, number>)
      ).sort((a, b) => b[1] - a[1])
    : [];

  const filteredDiscs = selectedRun
    ? (filterCls === "ALL" ? selectedRun.discrepancy_list
      : selectedRun.discrepancy_list.filter(d => d.classification === filterCls))
    : [];

  return (
    <div className="max-w-7xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Payment Reconciliation</h1>
          <p className="text-sm text-gray-500">Discrepancy Detection System</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => setView("dashboard")}
            className={`px-3 py-1.5 rounded text-sm font-medium ${view === "dashboard" ? "bg-blue-600 text-white" : "bg-white border text-gray-700"}`}>
            Dashboard
          </button>
          <button onClick={() => setView("run")}
            className={`px-3 py-1.5 rounded text-sm font-medium ${view === "run" ? "bg-blue-600 text-white" : "bg-white border text-gray-700"}`}>
            Run Details
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
          <strong>Error:</strong> {error}
          <button onClick={() => setError(null)} className="ml-2 text-red-500 hover:text-red-700">✕</button>
        </div>
      )}

      {/* ── RUN RECONCILIATION FORM ── */}
      <div className="bg-white rounded-lg border p-5 mb-6">
        <h2 className="font-semibold text-gray-800 mb-4">Run Reconciliation</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Period Label</label>
            <input value={periodLabel} onChange={e => setPeriodLabel(e.target.value)}
              className="w-full border rounded px-2 py-1.5 text-sm" placeholder="2024-01" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">As-of Date (Cutoff)</label>
            <input type="date" value={asOfDate} onChange={e => setAsOfDate(e.target.value)}
              className="w-full border rounded px-2 py-1.5 text-sm" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Rounding Tolerance</label>
            <input value={tolerance} onChange={e => setTolerance(e.target.value)}
              className="w-full border rounded px-2 py-1.5 text-sm" placeholder="0.01" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Settlement Window (days)</label>
            <input type="number" value={window_} onChange={e => setWindow(e.target.value)}
              className="w-full border rounded px-2 py-1.5 text-sm" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 mb-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Internal Transactions CSV</label>
            <input type="file" accept=".csv"
              onChange={e => e.target.files?.[0] && handleFileLoad(setTxnCsv, e.target.files[0])}
              className="w-full text-sm" />
            {txnCsv && <span className="text-xs text-green-600">✓ Loaded ({txnCsv.split("\n").length - 1} rows)</span>}
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Bank Settlements CSV</label>
            <input type="file" accept=".csv"
              onChange={e => e.target.files?.[0] && handleFileLoad(setStlCsv, e.target.files[0])}
              className="w-full text-sm" />
            {stlCsv && <span className="text-xs text-green-600">✓ Loaded ({stlCsv.split("\n").length - 1} rows)</span>}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={handleReconcile} disabled={loading}
            className="px-4 py-2 bg-blue-600 text-white rounded font-medium text-sm disabled:opacity-50 hover:bg-blue-700">
            {loading ? "Running…" : "Run Reconciliation"}
          </button>
          {runMsg && <span className="text-sm text-green-600">{runMsg}</span>}
        </div>
      </div>

      {/* ── DASHBOARD VIEW ── */}
      {view === "dashboard" && (
        <div>
          <h2 className="font-semibold text-gray-800 mb-3">Reconciliation Runs</h2>
          {runs.length === 0 ? (
            <p className="text-gray-500 text-sm">No runs yet. Upload CSVs and run reconciliation above.</p>
          ) : (
            <div className="bg-white rounded-lg border overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    {["Period","As-of Date","Status","Matched","Discrepancies","Variance","Rounding Alert",""].map(h => (
                      <th key={h} className="px-3 py-2 text-left text-xs font-medium text-gray-600">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {runs.map(r => (
                    <tr key={r.run_id} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-medium">{r.period_label}</td>
                      <td className="px-3 py-2 text-gray-600">{r.as_of_date}</td>
                      <td className="px-3 py-2">
                        <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${r.run_status === "completed" ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"}`}>
                          {r.run_status}
                        </span>
                      </td>
                      <td className="px-3 py-2">{r.matched_count}</td>
                      <td className="px-3 py-2 text-red-600 font-medium">{r.discrepancy_count}</td>
                      <td className="px-3 py-2 font-mono">{fmt(r.reconciliation_variance, "INR")}</td>
                      <td className="px-3 py-2">
                        {r.aggregate_exceeds_tolerance && (
                          <span className="px-2 py-0.5 bg-orange-100 text-orange-700 rounded-full text-xs">⚠ Rounding</span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <button onClick={() => fetchRun(r.run_id)}
                          className="text-blue-600 hover:underline text-xs font-medium">View</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── RUN DETAIL VIEW ── */}
      {view === "run" && selectedRun && (
        <div>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
            {[
              { label: "Gross Transactions", value: fmt(selectedRun.gross_transaction_value, "INR"), color: "blue" },
              { label: "Net Transaction Value", value: fmt(selectedRun.net_transaction_value, "INR"), color: "blue" },
              { label: "Bank Settlement Total", value: fmt(selectedRun.bank_settlement_total, "INR"), color: "green" },
              { label: "Reconciliation Variance", value: fmt(selectedRun.reconciliation_variance, "INR"),
                color: selectedRun.reconciliation_variance === "0" ? "green" : "red" },
              { label: "Outstanding Amount", value: fmt(selectedRun.outstanding_amount, "INR"), color: "yellow" },
              { label: "Matched", value: `${selectedRun.matched_count} / ${selectedRun.total_transactions}`, color: "green" },
              { label: "Discrepancies", value: String(selectedRun.discrepancy_count), color: "red" },
              { label: "Refund Total", value: fmt(selectedRun.refund_total, "INR"), color: "purple" },
            ].map(c => (
              <div key={c.label} className="bg-white rounded-lg border p-4">
                <p className="text-xs text-gray-500 mb-1">{c.label}</p>
                <p className={`text-lg font-bold font-mono text-${c.color}-700`}>{c.value}</p>
              </div>
            ))}
          </div>

          {/* Aggregate rounding warning */}
          {selectedRun.aggregate_exceeds_tolerance && (
            <div className="mb-5 p-4 bg-orange-50 border border-orange-200 rounded-lg flex items-start gap-3">
              <span className="text-orange-500 text-xl">⚠</span>
              <div>
                <p className="font-semibold text-orange-800">Aggregate Rounding Exposure</p>
                <p className="text-sm text-orange-700">
                  Total rounding differences sum to <strong>{fmt(selectedRun.aggregate_rounding_difference, "INR")}</strong>,
                  which meets or exceeds the configured tolerance of{" "}
                  <strong>{selectedRun.configuration_snapshot.rounding_tolerance}</strong>.
                  Individual differences are small but their cumulative impact is material.
                </p>
              </div>
            </div>
          )}

          {/* Cross-month resolved */}
          {selectedRun.resolved_carried_forward.length > 0 && (
            <div className="mb-5 p-4 bg-blue-50 border border-blue-200 rounded-lg">
              <p className="font-semibold text-blue-800 mb-2">
                Carry-Forward Resolved ({selectedRun.resolved_carried_forward.length})
              </p>
              {selectedRun.resolved_carried_forward.map((r, i) => (
                <div key={i} className="text-sm text-blue-700">
                  Transaction <code className="bg-blue-100 px-1 rounded">{r.transaction_id}</code>{" "}
                  from period <strong>{r.originating_period_label}</strong> resolved as{" "}
                  <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${CLASSIFICATION_COLORS[r.classification] || ""}`}>
                    {r.classification}
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Discrepancy breakdown */}
          <div className="grid grid-cols-2 gap-4 mb-5">
            <div className="bg-white rounded-lg border p-4">
              <h3 className="font-semibold text-gray-800 mb-3 text-sm">Discrepancy Breakdown</h3>
              <div className="space-y-1.5">
                {breakdown.map(([cls, count]) => (
                  <div key={cls} className="flex items-center justify-between">
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${CLASSIFICATION_COLORS[cls] || "bg-gray-100 text-gray-700"}`}>
                      {cls}
                    </span>
                    <span className="text-sm font-mono font-bold">{count}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="bg-white rounded-lg border p-4">
              <h3 className="font-semibold text-gray-800 mb-3 text-sm">Run Info</h3>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between"><span className="text-gray-500">Run ID</span><code className="text-xs">{selectedRun.run_id.slice(0,16)}…</code></div>
                <div className="flex justify-between"><span className="text-gray-500">Period</span><span>{selectedRun.period_label}</span></div>
                <div className="flex justify-between"><span className="text-gray-500">Cutoff</span><span>{selectedRun.as_of_date}</span></div>
                <div className="flex justify-between"><span className="text-gray-500">Tolerance</span><span>{selectedRun.configuration_snapshot.rounding_tolerance}</span></div>
                <div className="flex justify-between"><span className="text-gray-500">Window</span><span>{selectedRun.configuration_snapshot.settlement_window}d</span></div>
                <div className="flex justify-between"><span className="text-gray-500">Transactions</span><span>{selectedRun.total_transactions}</span></div>
                <div className="flex justify-between"><span className="text-gray-500">Settlements</span><span>{selectedRun.total_settlements}</span></div>
              </div>
              <div className="mt-3">
                <a href={`http://localhost:8000/api/runs/${selectedRun.run_id}/export/csv`}
                  target="_blank" rel="noopener noreferrer"
                  className="text-sm text-blue-600 hover:underline">↓ Export CSV</a>
              </div>
            </div>
          </div>

          {/* Discrepancy table */}
          <div className="bg-white rounded-lg border">
            <div className="flex items-center justify-between p-3 border-b">
              <h3 className="font-semibold text-gray-800 text-sm">Discrepancy Records ({filteredDiscs.length})</h3>
              <select value={filterCls} onChange={e => setFilterCls(e.target.value)}
                className="border rounded px-2 py-1 text-xs">
                <option value="ALL">All Classifications</option>
                {breakdown.map(([cls]) => <option key={cls} value={cls}>{cls}</option>)}
              </select>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-gray-50">
                  <tr>
                    {["Classification","Transaction ID","Settlement ID","Txn Amount","Stl Amount","Diff","Currency","Note"].map(h => (
                      <th key={h} className="px-3 py-2 text-left font-medium text-gray-600 whitespace-nowrap">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {filteredDiscs.slice(0, 200).map(d => (
                    <tr key={d.record_id} className="hover:bg-gray-50">
                      <td className="px-3 py-2">
                        <span className={`px-1.5 py-0.5 rounded-full text-xs font-medium whitespace-nowrap ${CLASSIFICATION_COLORS[d.classification] || "bg-gray-100"}`}>
                          {d.classification}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-mono text-gray-600 max-w-32 truncate">{d.transaction_id || "—"}</td>
                      <td className="px-3 py-2 font-mono text-gray-600 max-w-32 truncate">{d.settlement_id || "—"}</td>
                      <td className="px-3 py-2 font-mono">{fmt(d.transaction_amount)}</td>
                      <td className="px-3 py-2 font-mono">{fmt(d.settlement_amount)}</td>
                      <td className="px-3 py-2 font-mono text-red-600">{fmt(d.individual_difference)}</td>
                      <td className="px-3 py-2">{d.currency}</td>
                      <td className="px-3 py-2 text-gray-500 max-w-xs truncate" title={d.resolution_note || ""}>{d.resolution_note || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {filteredDiscs.length > 200 && (
                <p className="px-3 py-2 text-xs text-gray-500">Showing first 200 of {filteredDiscs.length} records.</p>
              )}
            </div>
          </div>
        </div>
      )}

      {view === "run" && !selectedRun && (
        <p className="text-gray-500 text-sm">Select a run from the Dashboard or run a new reconciliation.</p>
      )}
    </div>
  );
}
