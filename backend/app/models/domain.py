"""
Domain models. All monetary values use decimal.Decimal — never float.
Matching key: InternalTransaction.transaction_id == BankSettlement.transaction_ref
"""
from decimal import Decimal, InvalidOperation
from datetime import date, datetime
from typing import Literal, Optional, List
from pydantic import BaseModel, field_validator, model_validator
import uuid


ClassificationEnum = Literal[
    "MATCHED", "TIMING_DIFFERENCE", "MISSING_SETTLEMENT", "UNMATCHED_SETTLEMENT",
    "PARTIAL_SETTLEMENT", "MULTIPLE_SETTLEMENTS", "AMOUNT_MISMATCH",
    "ROUNDING_DIFFERENCE", "CURRENCY_MISMATCH", "DUPLICATE_TRANSACTION",
    "DUPLICATE_SETTLEMENT", "ORPHAN_REFUND",
]


class InternalTransaction(BaseModel):
    """Internal platform payment record.
    transaction_id is the reference the bank echoes back as BankSettlement.transaction_ref."""
    transaction_id: str
    transaction_date: date
    transaction_amount: Decimal
    currency: str
    transaction_type: Literal["payment", "refund"]
    status: Literal["success", "pending", "failed"]
    original_transaction_ref: Optional[str] = None  # Required for refunds
    merchant_id: str
    payment_method: str

    @field_validator("transaction_amount", mode="before")
    @classmethod
    def parse_amount(cls, v):
        if isinstance(v, float):
            raise ValueError("Use string decimal, not float, for transaction_amount")
        try:
            return Decimal(str(v))
        except InvalidOperation:
            raise ValueError(f"Cannot parse '{v}' as Decimal")

    @model_validator(mode="after")
    def refund_needs_original(self):
        if self.transaction_type == "refund" and not self.original_transaction_ref:
            raise ValueError("original_transaction_ref required for refund")
        return self


class BankSettlement(BaseModel):
    """Bank settlement record.
    transaction_ref == InternalTransaction.transaction_id"""
    settlement_id: str
    transaction_ref: str
    settlement_amount: Decimal
    currency: str
    settlement_date: date
    settlement_timestamp: datetime
    bank_batch_id: str
    bank_name: str
    status: Literal["settled", "reversed", "pending"]

    @field_validator("settlement_amount", mode="before")
    @classmethod
    def parse_amount(cls, v):
        if isinstance(v, float):
            raise ValueError("Use string decimal, not float, for settlement_amount")
        try:
            d = Decimal(str(v))
        except InvalidOperation:
            raise ValueError(f"Cannot parse '{v}' as Decimal")
        if d < Decimal("0"):
            raise ValueError("settlement_amount must be non-negative")
        return d


class DiscrepancyRecord(BaseModel):
    record_id: str = ""
    transaction_id: Optional[str] = None
    settlement_id: Optional[str] = None
    settlement_ids: Optional[List[str]] = None
    classification: ClassificationEnum
    transaction_amount: Optional[Decimal] = None
    settlement_amount: Optional[Decimal] = None
    individual_difference: Optional[Decimal] = None
    currency: str
    period_label: str
    rule_id: str
    duplicate_fingerprint: Optional[str] = None
    resolution_note: Optional[str] = None

    def model_post_init(self, __context):
        if not self.record_id:
            self.record_id = str(uuid.uuid4())


class FinancialTotals(BaseModel):
    gross_transaction_value: Decimal
    refund_total: Decimal
    net_transaction_value: Decimal
    bank_settlement_total: Decimal
    outstanding_amount: Decimal
    reconciliation_variance: Decimal
    aggregate_rounding_difference: Decimal
    aggregate_exceeds_tolerance: bool


class CarryForwardEntry(BaseModel):
    entry_id: str = ""
    transaction_id: str
    originating_period_label: str
    resolved_period_label: Optional[str] = None
    outstanding_days: int = 0
    status: Literal["outstanding", "resolved", "escalated"]
    transaction_amount: Optional[Decimal] = None
    transaction_currency: str = "INR"
    created_as_of_date: str
    last_updated_at: str
    reconciliation_run_id: str

    def model_post_init(self, __context):
        if not self.entry_id:
            self.entry_id = str(uuid.uuid4())


class ReconciliationResult(BaseModel):
    run_id: str = ""
    period_label: str
    as_of_date: str
    run_status: Literal["pending", "running", "completed", "failed"]
    run_timestamp: str
    configuration_snapshot: dict
    gross_transaction_value: Decimal = Decimal("0")
    refund_total: Decimal = Decimal("0")
    net_transaction_value: Decimal = Decimal("0")
    bank_settlement_total: Decimal = Decimal("0")
    outstanding_amount: Decimal = Decimal("0")
    reconciliation_variance: Decimal = Decimal("0")
    aggregate_rounding_difference: Decimal = Decimal("0")
    aggregate_exceeds_tolerance: bool = False
    total_transactions: int = 0
    total_settlements: int = 0
    matched_count: int = 0
    discrepancy_count: int = 0
    discrepancy_list: List[DiscrepancyRecord] = []
    resolved_carried_forward: List[dict] = []
    error_detail: Optional[str] = None

    def model_post_init(self, __context):
        if not self.run_id:
            self.run_id = str(uuid.uuid4())


class SystemConfig(BaseModel):
    rounding_tolerance: Decimal = Decimal("0.01")
    settlement_window: int = 2
    supported_currencies: List[str] = ["INR", "USD", "EUR"]

