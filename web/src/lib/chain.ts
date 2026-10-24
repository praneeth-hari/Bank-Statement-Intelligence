import type { ReviewItem, StatementDetail } from "../types";

export type RowStatus = "ok" | "flag" | "brk" | "done";

/** One status per transaction row for the balance-chain strip. */
export function rowStatuses(stmt: StatementDetail, items: ReviewItem[]): RowStatus[] {
  const out: RowStatus[] = stmt.transactions.map((t) =>
    Object.values(t.fields).some((f) => f?.flags.some((x) => x === "human_corrected" || x === "human_verified")) ? "done" : "ok");
  for (const it of items) {
    if (it.row === null) continue;
    if (it.group === "chain") out[it.row] = "brk";
    else if (out[it.row] !== "brk") out[it.row] = "flag";
  }
  return out;
}
