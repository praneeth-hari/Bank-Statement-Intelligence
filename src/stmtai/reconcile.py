"""Reconciliation checks for a statement.

The running balance is the strongest correctness signal for bank statements:
``previous balance + credit - debit`` must equal the printed balance on every row,
and the last balance must equal the closing balance. A row that breaks the chain is
either misread or the statement was altered.

The chain continues from the *stated* balance of each row, so one bad row does not
automatically flag every row after it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .schema import Statement


@dataclass(frozen=True)
class ReconIssue:
    kind: str  # balance_mismatch | closing_mismatch | date_order | out_of_period | negative_balance
    row: int | None  # index into statement.transactions, None for statement-level issues
    expected: str | None = None
    actual: str | None = None


def reconcile(st: Statement) -> list[ReconIssue]:
    issues: list[ReconIssue] = []
    previous = st.opening_balance
    last_date = None

    for i, t in enumerate(st.transactions):
        expected = previous + t.signed_amount
        if expected != t.balance:
            issues.append(ReconIssue("balance_mismatch", i, str(expected), str(t.balance)))
        if t.balance < Decimal("0"):
            issues.append(ReconIssue("negative_balance", i, None, str(t.balance)))
        if last_date is not None and t.date < last_date:
            issues.append(ReconIssue("date_order", i, str(last_date), str(t.date)))
        if not (st.period_start <= t.date <= st.period_end):
            issues.append(ReconIssue("out_of_period", i, f"{st.period_start}..{st.period_end}", str(t.date)))
        previous = t.balance
        last_date = t.date

    if st.transactions and previous != st.closing_balance:
        issues.append(ReconIssue("closing_mismatch", None, str(st.closing_balance), str(previous)))
    if not st.transactions and st.opening_balance != st.closing_balance:
        issues.append(ReconIssue("closing_mismatch", None, str(st.opening_balance), str(st.closing_balance)))
    return issues
