import type { FieldJson, ReviewItem, StatementDetail } from "../types";
import { formatInr, parsePaise } from "./money";

export interface ExplainLine { label: string; text: string; ok?: boolean }

const val = (f: FieldJson | null | undefined) => parsePaise(f?.value ?? null);

/** The arithmetic behind a balance or amount flag, in the words an accountant would use. */
export function explainRow(stmt: StatementDetail, item: ReviewItem): ExplainLine[] {
  if (item.row === null || !["balance", "debit", "credit"].includes(item.field)) return [];
  const rows = stmt.transactions;
  const row = rows[item.row]?.fields;
  if (!row) return [];
  const prev = item.row === 0 ? val(stmt.header.opening_balance) : val(rows[item.row - 1]?.fields.balance);
  if (prev === null) return [];
  const debit = val(row.debit), credit = val(row.credit), balance = val(row.balance);
  const fmt = formatInr;
  const lines: ExplainLine[] = [];

  if (item.field === "balance") {
    const amount = credit ?? debit;
    if (amount === null) return [];
    const sign = credit !== null ? 1n : -1n;
    // If a suggestion exists it is the value the arithmetic wants, so show the sum that produces it.
    const expected = prev + sign * amount;
    lines.push({
      label: credit !== null ? "Previous balance plus this credit" : "Previous balance minus this debit",
      text: `${fmt(prev)} ${credit !== null ? "+" : "−"} ${fmt(amount)} = ${fmt(expected)}`,
    });
    const next = rows[item.row + 1]?.fields;
    const nextBalance = val(next?.balance), nextCredit = val(next?.credit), nextDebit = val(next?.debit);
    const nextAmount = nextCredit ?? nextDebit;
    if (nextBalance !== null && nextAmount !== null) {
      const nextSign = nextCredit !== null ? 1n : -1n;
      if (expected + nextSign * nextAmount === nextBalance) {
        lines.push({
          label: "The next row agrees",
          text: `${fmt(expected)} ${nextCredit !== null ? "+" : "−"} ${fmt(nextAmount)} = ${fmt(nextBalance)}`,
          ok: true,
        });
      }
    }
  } else if (balance !== null) {
    const change = balance - prev;
    const direction = change >= 0n ? "added" : "taken out";
    lines.push({
      label: "Previous balance to this balance",
      text: `${fmt(prev)} to ${fmt(balance)}: ${fmt(change < 0n ? -change : change)} ${direction}`,
    });
  }
  return lines;
}
