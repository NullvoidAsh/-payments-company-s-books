# Requirements Document

## Introduction

The Payment Reconciliation & Discrepancy Detection System is a backend-driven financial tool that compares a business's internal payment transaction records against bank settlement records to detect discrepancies, classify them by type, and surface actionable reports to finance teams. Finance teams currently spend days manually comparing thousands of internal records against bank-provided settlement files — a process that is error-prone and slow. This system automates that process, covering multi-period reconciliation with cross-month carry-forward, partial and multiple settlements, aggregate rounding analysis, and duplicate detection based on precise fingerprint rules, with the goal of reducing month-end reconciliation time from days to hours.

## 1. Project Overview

The Payment Reconciliation & Discrepancy Detection System is a backend-driven financial tool that compares a business's internal payment transaction records against bank settlement records to detect discrepancies, classify them by type, and surface actionable reports to finance teams. The system handles multi-period reconciliation (including cross-month carry-forward), partial and multiple settlements, aggregate rounding analysis, and duplicate detection based on precise fingerprint rules.

**Technology Stack**

| Layer       | Technology                                                            |
|-------------|-----------------------------------------------------------------------|
| Backend     | Python, FastAPI, Pydantic, `decimal.Decimal` (never `float` for money), Pandas |
| Frontend    | Next.js, React, TypeScript, Tailwind CSS, shadcn/ui                   |
| Testing     | pytest, API integration tests, reconciliation engine unit tests       |
| Storage     | CSV for datasets, SQLite for persistence and carry-forward store      |

**Engineering Decisions**

- All monetary arithmetic uses `decimal.Decimal` with `ROUND_HALF_UP` for display; full precision is stored internally.
- Monetary amounts are serialized as JSON strings, never JSON numbers.
- No silent assumptions: every interpretation is documented with its consequence.

---

## 2. Problem Statement

Finance teams manually compare thousands of internal payment records against bank-provided settlement files every month. This process is error-prone and slow. Key problems include:

- Payments recorded internally but not yet settled (timing differences).
- Settlement amounts differing from transaction amounts (rounding, partial, or mismatch).
- Duplicate transaction or settlement records inflating totals.
- Refunds referencing non-existent originals (orphan refunds).
- Cross-month settlements resolved against the wrong period.
- Multiple legitimate settlements against a single transaction incorrectly flagged as duplicates.

---

## 3. Business Objectives

1. Reduce month-end reconciliation time from days to hours.
2. Detect and classify every discrepancy with a named, auditable classification.
3. Produce a Reconciliation_Variance figure that finance teams can sign off on.
4. Provide carry-forward tracking so outstanding items do not fall through period boundaries.
5. Flag aggregate rounding exposure when many small differences accumulate into a material total.
6. Generate exportable reports for auditors.

---

## 4. User Roles and Use Cases

### Roles

| Role                   | Description                                                                 |
|------------------------|-----------------------------------------------------------------------------|
| Finance_Analyst        | Runs reconciliation, reviews results, exports reports.                      |
| Finance_Manager        | Approves reconciliation runs, reviews dashboards, escalates discrepancies.  |
| Auditor                | Reads reconciliation history, traces carry-forward lineage, exports data.   |
| System_Administrator   | Manages configuration (tolerances, windows), ingests data files, monitors API. |

### Use Cases

| ID    | Actor               | Use Case                                                        |
|-------|---------------------|-----------------------------------------------------------------|
| UC-01 | Finance_Analyst     | Upload internal transaction CSV and bank settlement CSV for a period. |
| UC-02 | Finance_Analyst     | Trigger reconciliation run for a specified period.              |
| UC-03 | Finance_Analyst     | View discrepancy report classified by type.                     |
| UC-04 | Finance_Analyst     | Export reconciliation report as CSV or PDF.                     |
| UC-05 | Finance_Manager     | View dashboard showing Reconciliation_Variance and outstanding totals. |
| UC-06 | Finance_Manager     | Approve or flag a reconciliation run.                           |
| UC-07 | Auditor             | Query carry-forward store by period to trace outstanding items. |
| UC-08 | Auditor             | Verify duplicate detection evidence (fingerprint that triggered classification). |
| UC-09 | System_Administrator | Configure Rounding_Tolerance, Settlement_Window, and currency list. |
| UC-10 | System_Administrator | Ingest test dataset with fixed seed 42 for validation runs.     |

---

## 5. Functional Requirements

## Requirements

### Requirement 1: Data Ingestion

**User Story:** As a Finance_Analyst, I want to upload internal transaction and bank settlement files, so that the system has the data needed to run reconciliation.

#### Acceptance Criteria

1. WHEN a Finance_Analyst submits a CSV file of Internal_Transactions, THE Ingestion_Service SHALL parse and validate every row against the Internal_Transaction schema before persisting any records.
2. WHEN a Finance_Analyst submits a CSV file of Bank_Settlements, THE Ingestion_Service SHALL parse and validate every row against the Bank_Settlement schema before persisting any records.
3. IF a submitted CSV row fails schema validation, THEN THE Ingestion_Service SHALL reject the entire file, return an error response listing every invalid row with its field-level error, and persist no records from that file.
4. WHEN a file is successfully ingested, THE Ingestion_Service SHALL return a confirmation containing the ingestion_id, record_count, and period_label.
5. THE Ingestion_Service SHALL accept files up to 50 MB in size.
6. WHEN a duplicate ingestion is submitted (same file hash and period_label already ingested), THE Ingestion_Service SHALL reject it and return a conflict error referencing the existing ingestion_id.

---

### Requirement 2: Reconciliation Run

**User Story:** As a Finance_Analyst, I want to trigger a reconciliation run for a specific period, so that the system matches transactions against settlements and classifies every record.

#### Acceptance Criteria

1. WHEN a Finance_Analyst triggers a reconciliation run specifying a period_label, THE Reconciliation_Engine SHALL load all Internal_Transactions and Bank_Settlements for that period from the persistence store.
2. THE Reconciliation_Engine SHALL attempt to match each Internal_Transaction to one or more Bank_Settlements using the matching rules defined in Section 9.
3. WHEN a reconciliation run completes, THE Reconciliation_Engine SHALL persist the full result, including all classification outcomes, financial totals, and carry-forward updates, as a named Reconciliation_Result record.
4. WHEN a reconciliation run is in progress, THE Reconciliation_Engine SHALL update a run_status field (pending, running, completed, failed) queryable via the API.
5. IF a reconciliation run encounters an unrecoverable error, THEN THE Reconciliation_Engine SHALL set run_status to failed, persist an error_detail message, and leave existing Reconciliation_Results unchanged.
6. THE Reconciliation_Engine SHALL complete a run over 100,000 transaction-settlement pairs within 60 seconds on the reference hardware.

---

### Requirement 3: Carry-Forward (Cross-Month Reconciliation)

**User Story:** As a Finance_Analyst, I want outstanding transactions from prior periods to be re-attempted in the current period, so that late-arriving settlements are matched to their originating transactions.

#### Acceptance Criteria

1. WHEN a reconciliation run completes and a transaction is classified TIMING_DIFFERENCE, THE Carry_Forward_Store SHALL persist an entry keyed by (transaction_id, originating_period_label) with status = outstanding and outstanding_days = days elapsed since transaction_date.
2. WHEN a reconciliation run begins for period P, THE Reconciliation_Engine SHALL load all Carry_Forward_Store entries with status = outstanding from all prior periods.
3. WHEN a carry-forward outstanding transaction matches a Bank_Settlement in the current period, THE Reconciliation_Engine SHALL reclassify the Carry_Forward_Store entry from outstanding to resolved and include the matched pair in the current period's Reconciliation_Result under the resolved_carried_forward section.
4. WHEN a carry-forward outstanding transaction does not match any Bank_Settlement in the current period and the Settlement_Window has not elapsed, THE Carry_Forward_Store SHALL retain the entry as outstanding and increment outstanding_days.
5. WHEN a carry-forward outstanding transaction does not match any Bank_Settlement and outstanding_days exceeds the configured Settlement_Window, THE Carry_Forward_Store SHALL update the entry status to escalated and THE Reconciliation_Engine SHALL classify the transaction as MISSING_SETTLEMENT in the current period's result.
6. THE Carry_Forward_Store SHALL be queryable by originating_period_label so that Auditors can retrieve all items originated in a given period with their current status and resolution detail.
7. WHEN a carry-forward item is resolved in period P, THE Carry_Forward_Store SHALL record the resolved_period_label = P so that the full lineage (originating period → resolving period) is permanently auditable.

---

### Requirement 4: Discrepancy Classification

**User Story:** As a Finance_Analyst, I want every unmatched or anomalous record to receive a named discrepancy classification, so that I know the reason for each exception.

#### Acceptance Criteria

1. THE Reconciliation_Engine SHALL classify every processed Internal_Transaction and Bank_Settlement record with exactly one of the following classifications: MATCHED, TIMING_DIFFERENCE, MISSING_SETTLEMENT, UNMATCHED_SETTLEMENT, PARTIAL_SETTLEMENT, MULTIPLE_SETTLEMENTS, AMOUNT_MISMATCH, ROUNDING_DIFFERENCE, CURRENCY_MISMATCH, DUPLICATE_TRANSACTION, DUPLICATE_SETTLEMENT, ORPHAN_REFUND.
2. WHEN a transaction and settlement are matched with an absolute amount difference of exactly zero, THE Reconciliation_Engine SHALL classify the pair as MATCHED.
3. WHEN a transaction and settlement are matched and the absolute amount difference is greater than zero and less than or equal to Rounding_Tolerance, THE Reconciliation_Engine SHALL classify the pair as ROUNDING_DIFFERENCE and SHALL NOT classify it as MATCHED.
4. WHEN a transaction and settlement are matched and the absolute amount difference is greater than Rounding_Tolerance and less than the full transaction amount, THE Reconciliation_Engine SHALL classify the pair as AMOUNT_MISMATCH.
5. WHEN no Bank_Settlement record exists for an Internal_Transaction within the Settlement_Window, THE Reconciliation_Engine SHALL classify the transaction as MISSING_SETTLEMENT.
6. WHEN a Bank_Settlement record exists but no matching Internal_Transaction is found, THE Reconciliation_Engine SHALL classify the settlement as UNMATCHED_SETTLEMENT.
7. WHEN an Internal_Transaction is matched by exactly one Bank_Settlement that covers only part of the transaction amount and the settlement amount is less than the transaction amount and no additional settlements exist for that transaction, THE Reconciliation_Engine SHALL classify the pair as PARTIAL_SETTLEMENT.
8. WHEN an Internal_Transaction is matched by two or more Bank_Settlement records with distinct settlement_id values, THE Reconciliation_Engine SHALL classify the transaction as MULTIPLE_SETTLEMENTS regardless of whether individual settlement amounts sum to the transaction amount.
9. WHEN the settlement_date of the matching Bank_Settlement falls outside the reconciliation period but within the Settlement_Window, THE Reconciliation_Engine SHALL classify the transaction as TIMING_DIFFERENCE.
10. WHEN an Internal_Transaction record is identified as a duplicate (per the rules in Section 10), THE Reconciliation_Engine SHALL classify it as DUPLICATE_TRANSACTION.
11. WHEN a Bank_Settlement record is identified as a duplicate (per the rules in Section 10), THE Reconciliation_Engine SHALL classify it as DUPLICATE_SETTLEMENT.
12. WHEN a refund Internal_Transaction references an original_transaction_id that does not exist in the current Internal_Transaction dataset or any prior period's persisted records, THE Reconciliation_Engine SHALL classify the refund as ORPHAN_REFUND.
13. WHEN transaction and settlement currencies do not match, THE Reconciliation_Engine SHALL classify the pair as CURRENCY_MISMATCH without attempting amount comparison.

---

### Requirement 5: Aggregate Rounding Analysis

**User Story:** As a Finance_Manager, I want to see the aggregate sum of all rounding differences for a reconciliation run, so that I can identify when many small rounding differences accumulate into a material exposure.

#### Acceptance Criteria

1. WHEN a reconciliation run completes, THE Reconciliation_Engine SHALL compute aggregate_rounding_difference as the sum of the individual amount differences for all pairs classified ROUNDING_DIFFERENCE in that run.
2. WHEN aggregate_rounding_difference is greater than or equal to Rounding_Tolerance, THE Reconciliation_Engine SHALL set the flag aggregate_exceeds_tolerance = true in the Reconciliation_Result summary.
3. WHEN aggregate_rounding_difference is less than Rounding_Tolerance, THE Reconciliation_Engine SHALL set aggregate_exceeds_tolerance = false.
4. THE Reconciliation_Engine SHALL include each ROUNDING_DIFFERENCE pair in the discrepancy list with its individual_difference value; small rounding differences SHALL NOT be silently omitted from the discrepancy list.
5. WHEN the reconciliation run includes 10 transactions each with individual_difference = ₹0.001, THE Reconciliation_Engine SHALL report aggregate_rounding_difference = ₹0.010 and aggregate_exceeds_tolerance = true because ₹0.010 ≥ default Rounding_Tolerance of ₹0.01.

---

### Requirement 6: Financial Calculations

**User Story:** As a Finance_Manager, I want the reconciliation summary to include precisely defined financial totals, so that I can confirm the variance figure and sign off on the period.

#### Acceptance Criteria

1. THE Reconciliation_Engine SHALL compute Gross_Transaction_Value as the sum of amounts of all Internal_Transaction records where transaction_type = 'payment' and status ≠ 'failed', excluding records classified DUPLICATE_TRANSACTION.
2. THE Reconciliation_Engine SHALL compute Refund_Total as the sum of amounts of all Internal_Transaction records where transaction_type = 'refund', excluding records classified DUPLICATE_TRANSACTION.
3. THE Reconciliation_Engine SHALL compute Net_Transaction_Value as Gross_Transaction_Value − Refund_Total.
4. THE Reconciliation_Engine SHALL compute Bank_Settlement_Total as the sum of settlement_amount of all Bank_Settlement records within the reconciliation scope, excluding records classified DUPLICATE_SETTLEMENT.
5. THE Reconciliation_Engine SHALL compute Outstanding_Amount as the sum of amounts of all Internal_Transaction records classified TIMING_DIFFERENCE or MISSING_SETTLEMENT.
6. THE Reconciliation_Engine SHALL compute Reconciliation_Variance as Net_Transaction_Value − Bank_Settlement_Total.
7. THE Reconciliation_Engine SHALL include Gross_Transaction_Value, Refund_Total, Net_Transaction_Value, Bank_Settlement_Total, Outstanding_Amount, and Reconciliation_Variance in every Reconciliation_Result summary.
8. THE Reconciliation_Engine SHALL exclude DUPLICATE_TRANSACTION and DUPLICATE_SETTLEMENT records from all financial totals while retaining them in the discrepancy list.

---

### Requirement 7: Dashboard

**User Story:** As a Finance_Manager, I want a real-time dashboard showing reconciliation status and key financials, so that I can monitor period health without opening raw reports.

#### Acceptance Criteria

1. THE Dashboard SHALL display Reconciliation_Variance, Outstanding_Amount, aggregate_rounding_difference, and aggregate_exceeds_tolerance for the most recent completed run.
2. THE Dashboard SHALL show a breakdown of discrepancy counts by classification type for the selected period.
3. WHEN aggregate_exceeds_tolerance is true, THE Dashboard SHALL render a visual alert distinguishing the aggregate rounding exposure from normal ROUNDING_DIFFERENCE entries.
4. THE Dashboard SHALL allow a Finance_Manager to select any prior reconciliation run and view its summary.
5. THE Dashboard SHALL reflect the current run_status of an in-progress reconciliation run, refreshing at most every 5 seconds.

---

### Requirement 8: Reporting and Export

**User Story:** As a Finance_Analyst, I want to export reconciliation results as CSV and PDF, so that I can share findings with auditors and finance leadership.

#### Acceptance Criteria

1. WHEN a Finance_Analyst requests a CSV export for a completed reconciliation run, THE Reporting_Service SHALL generate a CSV file containing every classified record with columns: transaction_id, settlement_id, classification, transaction_amount, settlement_amount, individual_difference, currency, period_label, resolution_note.
2. WHEN a Finance_Analyst requests a PDF export, THE Reporting_Service SHALL generate a PDF containing the reconciliation summary (all six financial totals), discrepancy table, aggregate rounding section, and carry-forward resolved section.
3. THE Reporting_Service SHALL complete a CSV export for 100,000 records within 30 seconds.
4. WHEN a Finance_Analyst requests an export for a run that does not exist, THE Reporting_Service SHALL return a not-found error.
5. WHERE an Auditor queries the carry-forward store by period, THE Reporting_Service SHALL export a CSV listing every carry-forward entry with columns: transaction_id, originating_period_label, resolved_period_label, outstanding_days, status.

---

### Requirement 9: Configuration Management

**User Story:** As a System_Administrator, I want to configure reconciliation parameters, so that the engine applies the correct tolerances and windows for each business context.

#### Acceptance Criteria

1. THE Configuration_Service SHALL expose a Rounding_Tolerance parameter (default: ₹0.01) that controls the threshold for ROUNDING_DIFFERENCE classification.
2. THE Configuration_Service SHALL expose a Settlement_Window parameter (default: 7 days) that controls how many days after a transaction date a settlement may arrive before the transaction is escalated to MISSING_SETTLEMENT.
3. THE Configuration_Service SHALL expose a supported_currencies list (default: ["INR", "USD", "EUR"]) that the Reconciliation_Engine uses to validate currency fields.
4. WHEN a System_Administrator updates a configuration parameter, THE Configuration_Service SHALL persist the new value and apply it to all subsequent reconciliation runs; runs already completed SHALL retain the configuration values in effect at the time they ran.
5. IF a System_Administrator submits an invalid configuration value (negative tolerance, zero-day window, empty currency list), THEN THE Configuration_Service SHALL reject the update and return a descriptive validation error.

---

## 6. Non-Functional Requirements

### Requirement 10: Performance

**User Story:** As a Finance_Analyst, I want reconciliation runs to complete quickly, so that I can iterate on corrections without waiting.

#### Acceptance Criteria

1. THE Reconciliation_Engine SHALL complete a reconciliation run over 100,000 transaction-settlement pairs within 60 seconds on a machine with 4 CPU cores and 8 GB RAM.
2. THE API SHALL respond to all read-only endpoints (status, summary, discrepancy list) within 2 seconds for datasets up to 10,000 records.
3. THE Reporting_Service SHALL generate a CSV export of 100,000 records within 30 seconds.

---

### Requirement 11: Data Integrity

**User Story:** As an Auditor, I want all stored reconciliation data to be immutable after a run completes, so that historical records cannot be altered after sign-off.

#### Acceptance Criteria

1. WHEN a reconciliation run reaches status = completed, THE Persistence_Layer SHALL mark the Reconciliation_Result as immutable; subsequent writes to that run's records SHALL return a conflict error.
2. THE Persistence_Layer SHALL store all monetary amounts as TEXT (string representation of Decimal) in SQLite, never as REAL or INTEGER.
3. THE Carry_Forward_Store SHALL log every status transition (outstanding → resolved, outstanding → escalated) with a timestamp and the reconciliation_run_id that triggered the transition.

---

### Requirement 12: Auditability

**User Story:** As an Auditor, I want every classification decision to be traceable to the specific rule that produced it, so that I can verify the reconciliation logic without reading code.

#### Acceptance Criteria

1. WHEN THE Reconciliation_Engine classifies a record, THE Reconciliation_Engine SHALL record the rule_id that produced the classification alongside the record in the Reconciliation_Result.
2. THE Carry_Forward_Store SHALL be queryable by originating_period_label and SHALL return the full lineage: originating period, all intermediate outstanding periods, and resolving period.
3. THE Reconciliation_Engine SHALL record the configuration snapshot (Rounding_Tolerance, Settlement_Window) in effect at the start of each run so that the Reconciliation_Result is self-describing.

---

## 7. Input Data Specifications

### Internal_Transaction Schema

| Field                   | Type            | Required | Description                                                        |
|-------------------------|-----------------|----------|--------------------------------------------------------------------|
| transaction_id          | string (UUID)   | Yes      | Unique identifier for the internal transaction.                    |
| transaction_ref         | string          | Yes      | Business reference shared with the bank.                           |
| transaction_date        | ISO 8601 date   | Yes      | Date the transaction was initiated.                                |
| transaction_amount      | Decimal string  | Yes      | Amount in the transaction currency. Never a float.                 |
| currency                | ISO 4217 code   | Yes      | Currency of the transaction (e.g., INR, USD).                      |
| transaction_type        | enum            | Yes      | 'payment' or 'refund'.                                             |
| status                  | enum            | Yes      | 'success', 'pending', 'failed'.                                    |
| original_transaction_id | string (UUID)   | Cond.    | Required when transaction_type = 'refund'. References the original payment. |
| merchant_id             | string          | Yes      | Identifier of the merchant originating the transaction.            |
| payment_method          | string          | Yes      | e.g., 'card', 'upi', 'netbanking'.                                 |

### Bank_Settlement Schema

| Field                | Type            | Required | Description                                                       |
|----------------------|-----------------|----------|-------------------------------------------------------------------|
| settlement_id        | string          | Yes      | Unique identifier assigned by the bank for this settlement record. |
| transaction_ref      | string          | Yes      | Business reference linking settlement to the originating transaction. |
| settlement_amount    | Decimal string  | Yes      | Amount settled by the bank. Never a float.                        |
| currency             | ISO 4217 code   | Yes      | Currency of the settlement.                                       |
| settlement_date      | ISO 8601 date   | Yes      | Date the bank processed the settlement.                           |
| settlement_timestamp | ISO 8601 datetime | Yes    | Full timestamp of the settlement (used in exact-record fingerprint). |
| bank_batch_id        | string          | Yes      | Bank batch identifier (used in exact-record fingerprint).         |
| bank_name            | string          | Yes      | Name of the settling bank.                                        |
| status               | enum            | Yes      | 'settled', 'reversed', 'pending'.                                 |

---

## 8. Output Data Specifications

### Reconciliation_Result

| Field                          | Type           | Description                                                              |
|--------------------------------|----------------|--------------------------------------------------------------------------|
| run_id                         | UUID           | Unique identifier for this reconciliation run.                           |
| period_label                   | string         | Period identifier (e.g., "2024-01").                                     |
| run_status                     | enum           | pending, running, completed, failed.                                     |
| run_timestamp                  | ISO 8601       | When the run started.                                                    |
| configuration_snapshot         | JSON object    | Rounding_Tolerance and Settlement_Window in effect at run start.         |
| gross_transaction_value        | Decimal string | See Section 11 for formula.                                              |
| refund_total                   | Decimal string | See Section 11 for formula.                                              |
| net_transaction_value          | Decimal string | See Section 11 for formula.                                              |
| bank_settlement_total          | Decimal string | See Section 11 for formula.                                              |
| outstanding_amount             | Decimal string | See Section 11 for formula.                                              |
| reconciliation_variance        | Decimal string | See Section 11 for formula.                                              |
| aggregate_rounding_difference  | Decimal string | Sum of all individual rounding differences in this run.                  |
| aggregate_exceeds_tolerance    | boolean        | True when aggregate_rounding_difference >= Rounding_Tolerance.           |
| discrepancy_list               | array          | All classified records (see below).                                      |
| resolved_carried_forward       | array          | Carry-forward items resolved in this run.                                |
| error_detail                   | string \| null | Present only when run_status = failed.                                   |

### Discrepancy_Record

| Field               | Type           | Description                                                              |
|---------------------|----------------|--------------------------------------------------------------------------|
| record_id           | UUID           | Unique identifier for this discrepancy record.                           |
| transaction_id      | string \| null | From Internal_Transaction (null for UNMATCHED_SETTLEMENT).               |
| settlement_id       | string \| null | From Bank_Settlement (null for MISSING_SETTLEMENT, ORPHAN_REFUND).       |
| classification      | enum           | One of the 12 classification values.                                     |
| transaction_amount  | Decimal string | Amount from Internal_Transaction (null if no transaction).               |
| settlement_amount   | Decimal string | Amount from Bank_Settlement (null if no settlement).                     |
| individual_difference | Decimal string | Absolute difference (null for non-amount discrepancies).                 |
| currency            | string         | Currency code.                                                           |
| period_label        | string         | Reconciliation period of this record.                                    |
| rule_id             | string         | The rule that produced this classification (for auditability).           |
| duplicate_fingerprint | string \| null | The fingerprint evidence for DUPLICATE_* classifications (null otherwise). |
| resolution_note     | string \| null | Human-readable explanation of the classification.                        |

---

## 9. Reconciliation Rules

### Rule R-01: Primary Matching

THE Reconciliation_Engine SHALL attempt to match each Internal_Transaction to Bank_Settlement records using transaction_ref as the primary key. The match is attempted against all Bank_Settlement records within scope (current period and carry-forward outstanding items).

### Rule R-02: Currency Pre-check

WHEN attempting a match between an Internal_Transaction and a Bank_Settlement, THE Reconciliation_Engine SHALL verify that the currency fields are equal before comparing amounts. IF currencies differ, THEN the pair SHALL be classified CURRENCY_MISMATCH and amount comparison SHALL NOT be performed.

### Rule R-03: Amount Comparison

WHEN currencies match, THE Reconciliation_Engine SHALL compute absolute_difference = |transaction_amount − settlement_amount| using `decimal.Decimal` arithmetic.

- IF absolute_difference = 0, THEN classification = MATCHED.
- IF 0 < absolute_difference ≤ Rounding_Tolerance, THEN classification = ROUNDING_DIFFERENCE. This pair is NOT MATCHED.
- IF absolute_difference > Rounding_Tolerance AND settlement_amount < transaction_amount AND no additional settlements exist for this transaction, THEN classification = PARTIAL_SETTLEMENT.
- IF absolute_difference > Rounding_Tolerance AND settlement_amount ≠ transaction_amount AND the above PARTIAL_SETTLEMENT condition is not met, THEN classification = AMOUNT_MISMATCH.

### Rule R-04: Multiple Settlements

WHEN two or more Bank_Settlement records with distinct settlement_id values share the same transaction_ref as an Internal_Transaction, THE Reconciliation_Engine SHALL classify the transaction as MULTIPLE_SETTLEMENTS. MULTIPLE_SETTLEMENTS is a legitimate classification and SHALL NOT be reclassified as DUPLICATE_SETTLEMENT.

### Rule R-05: Timing Window

WHEN an Internal_Transaction has no matching Bank_Settlement within the current reconciliation period but a potential match exists with a settlement_date after the period end and within the Settlement_Window, THE Reconciliation_Engine SHALL classify the transaction as TIMING_DIFFERENCE and persist it to the Carry_Forward_Store.

### Rule R-06: Missing Settlement

WHEN an Internal_Transaction has no matching Bank_Settlement within the reconciliation period and outstanding_days > Settlement_Window, THE Reconciliation_Engine SHALL classify the transaction as MISSING_SETTLEMENT.

### Rule R-07: Unmatched Settlement

WHEN a Bank_Settlement record has no matching Internal_Transaction in the current scope (including carry-forward), THE Reconciliation_Engine SHALL classify the settlement as UNMATCHED_SETTLEMENT.

### Rule R-08: Failed Transaction Exclusion

WHEN an Internal_Transaction has status = 'failed', THE Reconciliation_Engine SHALL exclude it from matching and from all financial totals. Failed transactions SHALL NOT appear in the discrepancy list unless they are also classified as DUPLICATE_TRANSACTION.

### Rule R-09: Refund Validation

WHEN processing an Internal_Transaction with transaction_type = 'refund', THE Reconciliation_Engine SHALL verify that original_transaction_id references an existing payment record. IF no such record is found, THEN the refund SHALL be classified ORPHAN_REFUND.

### Rule R-10: Carry-Forward Matching

WHEN a reconciliation run begins for period P, THE Reconciliation_Engine SHALL load carry-forward outstanding items from prior periods and attempt to match them against period P's Bank_Settlements before processing new transactions. A carry-forward match SHALL be recorded in the resolved_carried_forward section of period P's Reconciliation_Result and SHALL update the Carry_Forward_Store entry to resolved.

---

## 10. Discrepancy Classification Rules

### Classification Definitions

| Classification        | Trigger Condition                                                                                                           |
|-----------------------|-----------------------------------------------------------------------------------------------------------------------------|
| MATCHED               | Exact currency match; absolute_difference = 0.                                                                             |
| TIMING_DIFFERENCE     | No settlement in current period; potential settlement within Settlement_Window in a future period.                          |
| MISSING_SETTLEMENT    | No settlement found after outstanding_days > Settlement_Window.                                                             |
| UNMATCHED_SETTLEMENT  | Settlement with no matching Internal_Transaction.                                                                           |
| PARTIAL_SETTLEMENT    | One settlement exists; settlement_amount < transaction_amount; difference > Rounding_Tolerance; no other settlements.       |
| MULTIPLE_SETTLEMENTS  | Two or more Bank_Settlements with **distinct** settlement_id values share the same transaction_ref.                        |
| AMOUNT_MISMATCH       | Amount difference > Rounding_Tolerance; not a partial settlement pattern.                                                   |
| ROUNDING_DIFFERENCE   | 0 < absolute_difference ≤ Rounding_Tolerance. This is a discrepancy, NOT MATCHED.                                         |
| CURRENCY_MISMATCH     | transaction.currency ≠ settlement.currency.                                                                                 |
| DUPLICATE_TRANSACTION | Internal_Transaction identified as duplicate per Rule D-01 or D-02 below.                                                  |
| DUPLICATE_SETTLEMENT  | Bank_Settlement identified as duplicate per Rule D-03 or D-04 below.                                                       |
| ORPHAN_REFUND         | Refund with original_transaction_id not found in any period.                                                                |

### Duplicate Detection Rules

#### Rule D-01: Duplicate Transaction by ID

WHEN two or more Internal_Transaction records share the same transaction_id value, THE Reconciliation_Engine SHALL classify all but the first-received as DUPLICATE_TRANSACTION. The first-received record SHALL be designated the original and retain its primary classification.

#### Rule D-02: Duplicate Transaction by Exact-Record Fingerprint

WHEN two or more Internal_Transaction records share identical values for ALL of: transaction_id, transaction_ref, transaction_amount, currency, transaction_date, and merchant_id, THE Reconciliation_Engine SHALL classify all but the first-received as DUPLICATE_TRANSACTION.

#### Rule D-03: Duplicate Settlement by ID

WHEN two or more Bank_Settlement records share the same settlement_id value, THE Reconciliation_Engine SHALL classify all but the first-received as DUPLICATE_SETTLEMENT and SHALL record `duplicate_fingerprint = "settlement_id:<value>"` on the DUPLICATE_SETTLEMENT record. Only the designated original SHALL participate in matching and financial totals.

#### Rule D-04: Duplicate Settlement by Exact-Record Fingerprint

WHEN two or more Bank_Settlement records share identical values for ALL of: settlement_id, transaction_ref, settlement_amount, currency, settlement_timestamp, and bank_batch_id, THE Reconciliation_Engine SHALL classify all but the first-received as DUPLICATE_SETTLEMENT and SHALL record `duplicate_fingerprint = "exact_record:<field1=value1,...>"`.

#### Rule D-05: MULTIPLE_SETTLEMENTS is NOT a Duplicate

WHEN two or more Bank_Settlement records reference the same transaction_ref but have **distinct** settlement_id values and do NOT match the exact-record fingerprint in Rule D-04, THE Reconciliation_Engine SHALL classify the transaction as MULTIPLE_SETTLEMENTS and SHALL NOT raise DUPLICATE_SETTLEMENT for those records.

---

## 11. Financial Calculation Rules

All calculations use `decimal.Decimal` with full internal precision. Display values use `ROUND_HALF_UP` to two decimal places. All totals exclude duplicate records per Rules D-01 through D-04.

### Gross_Transaction_Value

```
Gross_Transaction_Value =
  SUM(transaction_amount)
  WHERE transaction_type = 'payment'
    AND status ≠ 'failed'
    AND classification ≠ 'DUPLICATE_TRANSACTION'
```

### Refund_Total

```
Refund_Total =
  SUM(transaction_amount)
  WHERE transaction_type = 'refund'
    AND classification ≠ 'DUPLICATE_TRANSACTION'
```

### Net_Transaction_Value

```
Net_Transaction_Value = Gross_Transaction_Value − Refund_Total
```

### Bank_Settlement_Total

```
Bank_Settlement_Total =
  SUM(settlement_amount)
  WHERE settlement is within reconciliation scope
    AND classification ≠ 'DUPLICATE_SETTLEMENT'
```

### Outstanding_Amount

```
Outstanding_Amount =
  SUM(transaction_amount)
  WHERE classification IN ('TIMING_DIFFERENCE', 'MISSING_SETTLEMENT')
```

### Reconciliation_Variance

```
Reconciliation_Variance = Net_Transaction_Value − Bank_Settlement_Total
```

### Aggregate_Rounding_Difference

```
aggregate_rounding_difference =
  SUM(individual_difference)
  WHERE classification = 'ROUNDING_DIFFERENCE'
```

---

## 12. Data Validation Requirements

### Requirement 13: Input Validation

**User Story:** As a Finance_Analyst, I want the system to reject malformed data before reconciliation, so that the reconciliation results are based only on valid records.

#### Acceptance Criteria

1. THE Ingestion_Service SHALL reject any Internal_Transaction row where transaction_amount is not parseable as a valid `decimal.Decimal` value.
2. THE Ingestion_Service SHALL reject any Internal_Transaction row where transaction_type = 'refund' and original_transaction_id is absent or empty.
3. THE Ingestion_Service SHALL reject any Internal_Transaction row where currency is not in the configured supported_currencies list.
4. THE Ingestion_Service SHALL reject any Bank_Settlement row where settlement_amount is negative.
5. THE Ingestion_Service SHALL reject any row where a required field is null or empty.
6. WHEN any row in a submitted file fails validation, THE Ingestion_Service SHALL reject the entire file and return a structured error listing every row number and field-level failure reason.

---

## 13. API Requirements

### Requirement 14: RESTful API

**User Story:** As a Finance_Analyst, I want a RESTful API, so that I can integrate the reconciliation system with existing finance tooling.

#### Acceptance Criteria

1. THE API SHALL expose a POST `/reconciliation/ingest` endpoint that accepts multipart CSV uploads for internal transactions and bank settlements.
2. THE API SHALL expose a POST `/reconciliation/run` endpoint that accepts a period_label and triggers a reconciliation run, returning a run_id.
3. THE API SHALL expose a GET `/reconciliation/run/{run_id}` endpoint that returns the full Reconciliation_Result for a completed run.
4. THE API SHALL expose a GET `/reconciliation/run/{run_id}/status` endpoint that returns run_status and progress metadata.
5. THE API SHALL expose a GET `/reconciliation/carry-forward` endpoint that accepts a period_label query parameter and returns all Carry_Forward_Store entries for that originating period.
6. THE API SHALL expose a GET `/reconciliation/run/{run_id}/export/csv` endpoint that triggers CSV export.
7. THE API SHALL expose a GET `/reconciliation/run/{run_id}/export/pdf` endpoint that triggers PDF export.
8. THE API SHALL return all monetary amounts as JSON strings, never as JSON numbers.
9. THE API SHALL return HTTP 422 for all validation errors with a JSON body containing field-level error details.
10. THE API SHALL return HTTP 404 for requests referencing non-existent run_id or period_label.

---

## 14. Dashboard Requirements

### Requirement 15: Finance Dashboard

**User Story:** As a Finance_Manager, I want a web dashboard, so that I can monitor reconciliation status and key financials without using the API directly.

#### Acceptance Criteria

1. THE Dashboard SHALL display a summary card for each completed reconciliation run showing: period_label, run_timestamp, Reconciliation_Variance, Outstanding_Amount, aggregate_rounding_difference, aggregate_exceeds_tolerance.
2. THE Dashboard SHALL display a discrepancy breakdown table grouping records by classification with count and total amount per classification.
3. WHEN aggregate_exceeds_tolerance is true, THE Dashboard SHALL render a warning banner stating the aggregate rounding exposure and its relationship to Rounding_Tolerance.
4. THE Dashboard SHALL provide a carry-forward panel showing all outstanding items by originating period with outstanding_days.
5. THE Dashboard SHALL allow a Finance_Manager to drill into any DUPLICATE_SETTLEMENT or DUPLICATE_TRANSACTION record to view the duplicate_fingerprint evidence.
6. THE Dashboard SHALL provide CSV and PDF export buttons for the currently selected run.

---

## 15. Reporting and Export Requirements

### Requirement 16: Reconciliation Reports

**User Story:** As a Finance_Analyst, I want structured exports for each reconciliation run, so that I can share findings with auditors and leadership.

#### Acceptance Criteria

1. WHEN a CSV export is requested, THE Reporting_Service SHALL include every record in the discrepancy_list including DUPLICATE_* records.
2. WHEN a PDF export is requested, THE Reporting_Service SHALL include a dedicated section for aggregate rounding showing aggregate_rounding_difference and aggregate_exceeds_tolerance.
3. WHEN a carry-forward export is requested, THE Reporting_Service SHALL include columns: transaction_id, originating_period_label, resolved_period_label, outstanding_days, status, reconciliation_run_id of the transition.
4. THE Reporting_Service SHALL format all Decimal amounts in export files using ROUND_HALF_UP to two decimal places with the currency code appended (e.g., "100.51 INR").

---

## 16. Testing Requirements

### Requirement 17: Test Dataset

**User Story:** As a System_Administrator, I want a deterministic test dataset, so that test results are reproducible across environments.

#### Acceptance Criteria

1. THE Test_Dataset_Generator SHALL generate at least 100 Internal_Transaction records and 100 Bank_Settlement records using fixed random seed 42.
2. THE Test_Dataset_Generator SHALL include at least one record of each classification: MATCHED, MISSING_SETTLEMENT, UNMATCHED_SETTLEMENT, PARTIAL_SETTLEMENT, MULTIPLE_SETTLEMENTS, TIMING_DIFFERENCE, ROUNDING_DIFFERENCE, CURRENCY_MISMATCH, DUPLICATE_TRANSACTION, DUPLICATE_SETTLEMENT, ORPHAN_REFUND, AMOUNT_MISMATCH.
3. THE Test_Dataset_Generator SHALL include at least one failed payment transaction to verify its exclusion from financial totals.
4. THE Test_Dataset_Generator SHALL include the aggregate rounding scenario: 10 Internal_Transaction records each with transaction_amount differing from the corresponding settlement_amount by exactly ₹0.001.
5. THE Test_Dataset_Generator SHALL output deterministic CSV files whose SHA-256 hashes are stable across runs with the same seed.

---

### Requirement 18: Acceptance Test Cases

**User Story:** As a Finance_Analyst, I want the system to pass all mandatory test cases, so that I have confidence in the correctness of the reconciliation engine.

#### Acceptance Criteria

**Case 1 — TIMING_DIFFERENCE (mandatory)**

1. WHEN an Internal_Transaction with amount ₹1,500 and transaction_date = January 31 has a matching Bank_Settlement with settlement_date = February 1 and both currencies match, THE Reconciliation_Engine SHALL classify the transaction as TIMING_DIFFERENCE in the January reconciliation run.
2. WHEN the January reconciliation run completes, THE Carry_Forward_Store SHALL contain an entry for this transaction_id with status = outstanding and originating_period_label = "2024-01".
3. WHEN the February reconciliation run executes and loads the carry-forward entry, THE Reconciliation_Engine SHALL match the January transaction against the February 1 settlement and reclassify it as MATCHED.
4. WHEN the February reconciliation run completes, THE Reconciliation_Result for February SHALL include this matched pair in the resolved_carried_forward section.
5. WHEN the February reconciliation run completes, THE Carry_Forward_Store entry SHALL show status = resolved and resolved_period_label = "2024-02".

**Case 2 — ROUNDING_DIFFERENCE (mandatory)**

6. WHEN an Internal_Transaction has transaction_amount = ₹100.505 and a matching Bank_Settlement has settlement_amount = ₹100.50 and the same currency, THE Reconciliation_Engine SHALL compute absolute_difference = ₹0.005.
7. WHEN absolute_difference = ₹0.005 and Rounding_Tolerance = ₹0.01, THE Reconciliation_Engine SHALL classify the pair as ROUNDING_DIFFERENCE.
8. THE Reconciliation_Engine SHALL NOT classify this pair as MATCHED.
9. WHEN the reconciliation run completes, THE discrepancy_list SHALL contain this pair with individual_difference = ₹0.005 and classification = ROUNDING_DIFFERENCE.

**Case 3 — DUPLICATE_SETTLEMENT (mandatory)**

10. WHEN two Bank_Settlement records share the same settlement_id value, THE Reconciliation_Engine SHALL classify the later-received record as DUPLICATE_SETTLEMENT with duplicate_fingerprint = "settlement_id:<value>".
11. THE Reconciliation_Engine SHALL use only the original (first-received) settlement in matching and financial total calculations.
12. THE DUPLICATE_SETTLEMENT record SHALL appear in the discrepancy_list of the Reconciliation_Result.
13. THE Reconciliation_Engine SHALL NOT raise DUPLICATE_SETTLEMENT for two Bank_Settlement records that share only the same transaction_ref but have distinct settlement_id values.

**Case 4 — ORPHAN_REFUND (mandatory)**

14. WHEN an Internal_Transaction with transaction_type = 'refund' has an original_transaction_id that does not exist in the current period or any prior period's persisted records, THE Reconciliation_Engine SHALL classify it as ORPHAN_REFUND.
15. THE ORPHAN_REFUND record SHALL appear in the discrepancy_list.
16. THE ORPHAN_REFUND amount SHALL be included in Refund_Total if the record is not also classified as DUPLICATE_TRANSACTION.

**Test Case T-A — Multiple Legitimate Settlements**

17. WHEN one Internal_Transaction is matched by three Bank_Settlement records each with a distinct settlement_id and each covering a partial portion of the transaction amount, THE Reconciliation_Engine SHALL classify the transaction as MULTIPLE_SETTLEMENTS.
18. THE Reconciliation_Engine SHALL NOT raise DUPLICATE_SETTLEMENT for any of the three settlement records.
19. THE Reconciliation_Result SHALL record all three settlement_ids in the discrepancy record for this transaction.

**Test Case T-B — Actual Duplicate Settlement Records**

20. WHEN two Bank_Settlement records share the same settlement_id, THE Reconciliation_Engine SHALL mark the original record with a flag original = true and the duplicate record with original = false and classification = DUPLICATE_SETTLEMENT.
21. Only the original record SHALL be used in Bank_Settlement_Total and matching.
22. The DUPLICATE_SETTLEMENT record SHALL remain visible in the discrepancy_list with its duplicate_fingerprint.

**Test Case T-C — Cross-Month Carry-Forward**

23. WHEN a January reconciliation run classifies an Internal_Transaction of ₹1,500 (transaction_date = January 31) as TIMING_DIFFERENCE, the Carry_Forward_Store SHALL persist the entry with originating_period_label = "2024-01".
24. WHEN a February reconciliation run is executed and a Bank_Settlement with settlement_date = February 1 matches the carry-forward transaction, THE Reconciliation_Engine SHALL classify the pair as MATCHED in the February result under resolved_carried_forward.
25. THE February Reconciliation_Result's reconciliation_variance SHALL account for the ₹1,500 settlement in Bank_Settlement_Total.
26. THE Carry_Forward_Store entry SHALL show resolved_period_label = "2024-02" and status = resolved after the February run.

**Test Case T-D — Aggregate Rounding**

27. WHEN a reconciliation run processes 10 Internal_Transaction records each with individual_difference = ₹0.001 against their respective settlements, THE Reconciliation_Engine SHALL classify each pair as ROUNDING_DIFFERENCE individually.
28. THE Reconciliation_Engine SHALL compute aggregate_rounding_difference = ₹0.010.
29. WHEN Rounding_Tolerance = ₹0.01 and aggregate_rounding_difference = ₹0.010, THE Reconciliation_Engine SHALL set aggregate_exceeds_tolerance = true because ₹0.010 ≥ ₹0.01.
30. Each of the 10 pairs SHALL appear individually in the discrepancy_list with its own individual_difference = ₹0.001.

**Correction 1 — Duplicate Settlement Detection**

31. THE Reconciliation_Engine SHALL identify a DUPLICATE_SETTLEMENT ONLY when: (a) two or more Bank_Settlement records share the same settlement_id value, OR (b) two or more Bank_Settlement records match on ALL of: settlement_id, transaction_ref, settlement_amount, currency, settlement_timestamp, and bank_batch_id.
32. THE Reconciliation_Engine SHALL NOT classify a Bank_Settlement as DUPLICATE_SETTLEMENT solely because it shares transaction_ref with another settlement that has a distinct settlement_id.

**Correction 2 — Cross-Month Carry-Forward Persistence**

33. THE Carry_Forward_Store SHALL persist entries from every period and SHALL NOT delete them when a new period's run begins.
34. THE Reconciliation_Engine SHALL load carry-forward entries from ALL prior periods, not only the immediately preceding period.
35. WHEN a carry-forward item remains unmatched across multiple periods and outstanding_days > Settlement_Window, THE Reconciliation_Engine SHALL escalate it to MISSING_SETTLEMENT.

**Correction 3 — ROUNDING_DIFFERENCE vs MATCHED**

36. THE Reconciliation_Engine SHALL apply the classification rule: absolute_difference = 0 → MATCHED; 0 < absolute_difference ≤ Rounding_Tolerance → ROUNDING_DIFFERENCE; never MATCHED.
37. THE Reconciliation_Engine SHALL include every ROUNDING_DIFFERENCE pair in the discrepancy_list; ROUNDING_DIFFERENCE pairs SHALL NOT be silently omitted.

**Correction 4 — Aggregate Rounding Scenario**

38. THE Reconciliation_Engine SHALL compute aggregate_rounding_difference for every run and include it in the Reconciliation_Result summary.
39. WHEN aggregate_rounding_difference >= Rounding_Tolerance, THE Reconciliation_Engine SHALL set aggregate_exceeds_tolerance = true.

**Correction 5 — Financial Calculations**

40. THE Reconciliation_Engine SHALL exclude DUPLICATE_TRANSACTION records from Gross_Transaction_Value and Refund_Total.
41. THE Reconciliation_Engine SHALL exclude DUPLICATE_SETTLEMENT records from Bank_Settlement_Total.
42. THE Reconciliation_Engine SHALL include failed transactions in neither Gross_Transaction_Value nor any other total.

**Correction 6 — Additional Test Cases**

43. THE Test_Suite SHALL include test cases T-A, T-B, T-C, and T-D as defined in this section with assertions for each numbered criterion above.

---

## 17. Acceptance Criteria Summary

Each of the following conditions constitutes a pass/fail acceptance gate for the system:

| Gate ID | Description                                                                                           | Linked Criteria   |
|---------|-------------------------------------------------------------------------------------------------------|-------------------|
| AC-01   | TIMING_DIFFERENCE classified for Jan 31 transaction; resolved to MATCHED in February via carry-forward. | Case 1, T-C       |
| AC-02   | ₹100.505 vs ₹100.50 classified ROUNDING_DIFFERENCE, NOT MATCHED.                                     | Case 2, Corr. 3   |
| AC-03   | Identical settlement_id → DUPLICATE_SETTLEMENT; shared transaction_ref only → MULTIPLE_SETTLEMENTS.  | Case 3, Corr. 1   |
| AC-04   | Refund with non-existent original_transaction_id → ORPHAN_REFUND.                                    | Case 4            |
| AC-05   | 3 distinct-ID settlements for 1 transaction → MULTIPLE_SETTLEMENTS; no DUPLICATE_SETTLEMENT raised.  | T-A               |
| AC-06   | Identical settlement_id pair: original participates in totals; duplicate in discrepancy_list only.    | T-B               |
| AC-07   | February carry-forward run shows ₹1,500 as MATCHED under resolved_carried_forward.                   | T-C               |
| AC-08   | 10 × ₹0.001 rounding differences: each ROUNDING_DIFFERENCE; aggregate = ₹0.010; flag = true.         | T-D, Corr. 4      |
| AC-09   | Financial totals exclude duplicate and failed records; formulas match Section 11.                     | Corr. 5           |
| AC-10   | DUPLICATE_SETTLEMENT triggered ONLY by identical settlement_id or exact-record fingerprint.           | Corr. 1           |

---

## 18. Assumptions and Limitations

### Documented Assumptions

| Topic                    | Assumption                                                                                                                                              | Consequence                                                                                                        |
|--------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------|
| Transaction matching      | The primary matching key between Internal_Transactions and Bank_Settlements is transaction_ref. The engine does not perform fuzzy or ML-based matching. | Records with typographical differences in transaction_ref will not be matched.                                     |
| Settlement delays         | A settlement arriving within Settlement_Window days after the transaction date is a timing difference, not a missing settlement.                         | The Settlement_Window (default 7 days) must be calibrated to the actual bank's SLA; misconfiguration causes false MISSING_SETTLEMENT classifications. |
| Month-end cutoff          | The reconciliation period boundary is midnight on the last calendar day of the month in UTC. Any settlement with settlement_date after that boundary falls in the next period. | Settlements timestamped in a timezone ahead of UTC may be attributed to the wrong period if not normalized.        |
| Rounding tolerance        | Default Rounding_Tolerance = ₹0.01. This applies per-transaction. Aggregate tolerance is a reporting flag only; it does not change per-transaction classifications. | Per-transaction ROUNDING_DIFFERENCE records are still raised even when aggregate_exceeds_tolerance = false.        |
| Duplicate identification  | Duplicates are detected by exact field matching only (settlement_id equality or full exact-record fingerprint). The engine does not detect near-duplicates. | Two records that are substantively duplicate but differ by one field will not be detected.                         |
| Refund treatment          | Refund amounts are subtracted from Gross_Transaction_Value to produce Net_Transaction_Value. Refunds are not matched against settlements in the same way as payments. | Refund settlements will appear as UNMATCHED_SETTLEMENT unless explicit refund-settlement matching is configured.   |
| Currency handling         | All amount comparisons require identical currency codes. No currency conversion is performed.                                                           | Cross-currency transactions are always classified CURRENCY_MISMATCH; variance across currencies is not computed.  |
| Partial settlements       | PARTIAL_SETTLEMENT applies when exactly one settlement exists and covers less than the full transaction amount. If multiple settlements together cover the full amount, it is MULTIPLE_SETTLEMENTS. | A transaction partially covered by multiple settlements is MULTIPLE_SETTLEMENTS, not PARTIAL_SETTLEMENT.          |
| Failed transactions       | Internal_Transaction records with status = 'failed' are excluded from all matching and all financial totals.                                            | A payment that failed internally but was settled by the bank (edge case) will appear as UNMATCHED_SETTLEMENT.     |
| Multiple settlements      | Multiple settlements with distinct settlement_ids against one transaction are legitimate and classified MULTIPLE_SETTLEMENTS, not DUPLICATE_SETTLEMENT.  | Finance teams must review MULTIPLE_SETTLEMENTS to confirm all partial amounts are intentional.                     |
| Financial totals          | All totals are computed in the settlement currency (INR by default). Multi-currency runs produce separate totals per currency in this version.           | A single Reconciliation_Variance figure is not meaningful when multiple currencies are present.                   |

### Limitations

1. The system does not perform real-time streaming reconciliation; it operates on batch uploads per period.
2. No automatic currency conversion is supported in this version.
3. The SQLite persistence layer is suitable for datasets up to approximately 1 million records; larger datasets require a migration to a relational database.
4. PDF export is generated server-side; complex layouts may differ across rendering environments.
5. The carry-forward store is queryable but does not send automated alerts; finance teams must poll the dashboard or API.
