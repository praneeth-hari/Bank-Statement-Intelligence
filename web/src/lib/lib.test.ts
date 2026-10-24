import { describe, expect, it } from "vitest";
import { cropStyle, boxStyle } from "./geometry";
import { explainRow } from "./explain";
import { displayValue, formatDate, formatInr, parsePaise } from "./money";
import { pickNext, sortItems, step } from "./queue";
import { rowStatuses } from "./chain";
import type { FieldJson, GroupInfo, ReviewItem, StatementDetail } from "../types";

const field = (value: string | null, extra: Partial<FieldJson> = {}): FieldJson => ({
  text: value ?? "", value, confidence: 1, needs_review: false, flags: [], reasons: [], suggestion: null,
  suggestion_verified: false, bbox: null, source: "ocr", ...extra,
});

function statement(rows: { debit?: string; credit?: string; balance: string }[], opening = "1000.00"): StatementDetail {
  return {
    id: "x", filename: "x.pdf", status: "ready", error: null, created: "", approved: false, approved_at: null,
    pages: [{ page: 0, width: 600, height: 800, image: "/p" }],
    header: { opening_balance: field(opening) },
    transactions: rows.map((r, row) => ({
      row, fields: { debit: r.debit ? field(r.debit) : null, credit: r.credit ? field(r.credit) : null, balance: field(r.balance) },
    })),
    issues: [], summary: {}, corrections: 0,
  };
}
const item = (over: Partial<ReviewItem>): ReviewItem => ({
  key: "r0:balance", scope: "row", row: 0, field: "balance", text: "", value: null, confidence: 0.2, flags: [],
  reasons: [], suggestion: null, suggestion_verified: false, bbox: null, group: "other", ...over,
});
const GROUPS: GroupInfo[] = (["chain", "repaired", "prefix", "header", "other"] as const)
  .map((id) => ({ id, label: id, hint: "", bulk: id === "prefix", count: 0 }));

describe("money", () => {
  it("parses and formats in Indian grouping", () => {
    expect(parsePaise("123344.20")).toBe(12334420n);
    expect(parsePaise("1,23,344.2")).toBe(12334420n);
    expect(parsePaise("-5")).toBe(-500n);
    expect(parsePaise("abc")).toBeNull();
    expect(parsePaise(null)).toBeNull();
    expect(formatInr(12334420n)).toBe("1,23,344.20");
    expect(formatInr(5n)).toBe("0.05");
    expect(formatInr(99999n)).toBe("999.99");
    expect(formatInr(100000n)).toBe("1,000.00");
    expect(formatInr(1234567890n)).toBe("1,23,45,678.90");
    expect(formatInr(-12334420n)).toBe("-1,23,344.20");
  });
  it("formats values for display by field type", () => {
    expect(displayValue("balance", "12334.42")).toBe("12,334.42");
    expect(displayValue("date", "2025-04-02")).toBe("02/04/2025");
    expect(displayValue("description", "UPI/1")).toBe("UPI/1");
    expect(displayValue("debit", null, "nothing read")).toBe("nothing read");
    expect(formatDate("garbage")).toBeNull();
  });
});

describe("explainRow", () => {
  it("shows the sum and that the next row agrees", () => {
    const s = statement([{ credit: "500.00", balance: "9.99" }, { debit: "200.00", balance: "1300.00" }]);
    const lines = explainRow(s, item({}));
    expect(lines[0].text).toBe("1,000.00 + 500.00 = 1,500.00");
    expect(lines[1]).toMatchObject({ label: "The next row agrees", ok: true, text: "1,500.00 − 200.00 = 1,300.00" });
  });
  it("omits the next-row line when it does not follow", () => {
    const s = statement([{ credit: "500.00", balance: "9.99" }, { debit: "200.00", balance: "42.00" }]);
    expect(explainRow(s, item({}))).toHaveLength(1);
  });
  it("explains an amount from the balance movement", () => {
    const s = statement([{ debit: "999.00", balance: "700.00" }]);
    const [line] = explainRow(s, item({ key: "r0:debit", field: "debit" }));
    expect(line.text).toBe("1,000.00 to 700.00: 300.00 taken out");
  });
  it("returns nothing for text fields and header items", () => {
    const s = statement([{ credit: "1.00", balance: "1001.00" }]);
    expect(explainRow(s, item({ field: "description" }))).toEqual([]);
    expect(explainRow(s, item({ row: null }))).toEqual([]);
  });
});

describe("queue order and navigation", () => {
  const a = item({ key: "a", group: "other", row: 1 }), b = item({ key: "b", group: "chain", row: 9 }),
    c = item({ key: "c", group: "chain", row: 3 }), d = item({ key: "d", group: "header", row: null });
  it("puts balance problems first, then document order", () => {
    expect(sortItems([a, b, c, d], GROUPS).map((i) => i.key)).toEqual(["c", "b", "d", "a"]);
  });
  it("moves on to the next waiting item, wraps, and ends", () => {
    const before = sortItems([a, b, c, d], GROUPS);
    expect(pickNext(before, "c", [a, b, d])).toBe("b");
    expect(pickNext(before, "a", [b, c, d])).toBe("b");        // wraps to the first remaining
    expect(pickNext(before, "c", [b])).toBe("b");
    expect(pickNext(before, "c", [])).toBeNull();
  });
  it("steps with wrap-around", () => {
    const list = sortItems([a, b, c, d], GROUPS);
    expect(step(list, "a", 1)).toBe("c");
    expect(step(list, "c", -1)).toBe("a");
    expect(step([], null, 1)).toBeNull();
  });
});

describe("geometry and chain", () => {
  it("places boxes as percentages of the page", () => {
    const style = boxStyle({ page: 0, x0: 60, y0: 80, x1: 120, y1: 100 }, { page: 0, width: 600, height: 800, image: "" }, 0);
    expect(style).toEqual({ left: "10%", top: "10%", width: "10%", height: `${(20 / 800) * 100}%` });
  });
  it("crops to the box and never zooms past the limits", () => {
    const crop = cropStyle({ page: 0, x0: 100, y0: 100, x1: 140, y1: 112 }, { page: 0, width: 600, height: 800, image: "" }, 410, 48, 3);
    expect(crop.width).toBeLessThanOrEqual(410);
    expect(crop.backgroundPosition.startsWith("-")).toBe(true);
  });
  it("marks rows by their worst status", () => {
    const s = statement([{ credit: "1", balance: "1" }, { credit: "1", balance: "1" }, { credit: "1", balance: "1" }]);
    s.transactions[2].fields.balance = field("1", { flags: ["human_corrected"] });
    const out = rowStatuses(s, [item({ row: 0, group: "other" }), item({ row: 0, group: "chain" })]);
    expect(out).toEqual(["brk", "ok", "done"]);
  });
});
