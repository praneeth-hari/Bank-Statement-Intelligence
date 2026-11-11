import { describe, expect, it } from "vitest";
import { bankName, monthGaps, monthLabel, rupees, share, shortDate, sumPaise, typeName } from "./format";
import { clearHistory, loadHistory, remember, saveHistory, type HistoryItem } from "./history";
import { parseRoute } from "./route";

describe("money and dates", () => {
  it("formats rupees exactly, with Indian grouping", () => {
    expect(rupees("622451.98")).toBe("₹6,22,451.98");
    expect(rupees("0.10")).toBe("₹0.10");
    expect(rupees("-1234.5")).toBe("-₹1,234.50");
    expect(rupees(null)).toBe("");
    expect(rupees("not money")).toBe("");
  });
  it("adds amounts in integer paise, so 0.1 + 0.2 is exactly 0.30", () => {
    expect(sumPaise(["0.10", "0.20"])).toBe(30n);
  });
  it("writes dates and months without the browser's locale", () => {
    expect(shortDate("2026-07-10")).toBe("10 Jul 2026");
    expect(shortDate("2025-04-03")).toBe("3 Apr 2025");
    expect(monthLabel("2025-04")).toBe("Apr 25");
    expect(monthLabel("2025-04", true)).toBe("Apr 2025");
  });
  it("finds the months between statements that have no data", () => {
    expect(monthGaps(["2025-04", "2025-05", "2025-06", "2026-07", "2026-08"])).toEqual([["2025-07", "2026-06"]]);
    expect(monthGaps(["2025-11", "2026-01"])).toEqual([["2025-12", "2025-12"]]);
    expect(monthGaps(["2025-04", "2025-05"])).toEqual([]);
    expect(monthGaps([])).toEqual([]);
  });
  it("shares are exact tenths of a percent", () => {
    expect(share("317653.74", "622339.88")).toBe("51.0");
    expect(share("112.10", "622339.88")).toBe("<0.1");
    expect(share("0.00", "100.00")).toBe("0.0");
    expect(share("5.00", "0.00")).toBe("0.0");
  });
});

describe("names", () => {
  it("shows a bank printed in capitals in ordinary case and leaves mixed case alone", () => {
    expect(bankName("ZEPHYR UNION BANK")).toBe("Zephyr Union Bank");
    expect(bankName("Kaveri Mercantile Bank")).toBe("Kaveri Mercantile Bank");
    expect(bankName(null)).toBe("");
  });
  it("names transaction types", () => {
    expect(typeName("upi")).toBe("UPI");
    expect(typeName("pos")).toBe("Card (POS)");
    expect(typeName("mystery")).toBe("Mystery");
  });
});

describe("routes", () => {
  it("maps the address bar to a screen", () => {
    expect(parseRoute("")).toEqual({ name: "dashboard" });
    expect(parseRoute("#/")).toEqual({ name: "dashboard" });
    expect(parseRoute("#/statements")).toEqual({ name: "statements" });
    expect(parseRoute("#/ask")).toEqual({ name: "ask" });
    expect(parseRoute("#/quality")).toEqual({ name: "quality" });
    expect(parseRoute("#/s/abc-123")).toEqual({ name: "review", id: "abc-123" });
    expect(parseRoute("#/nonsense")).toEqual({ name: "dashboard" });
  });
});

describe("recent questions", () => {
  const item = (q: string, at = 1): HistoryItem => ({ q, result: "₹1.00", answered: true, at });
  const fake = () => {
    const m = new Map<string, string>();
    return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) };
  };
  it("puts the newest first and does not repeat a question", () => {
    const a = remember([], item("Total UPI spend"));
    const b = remember(a, item("How many credits?", 2));
    const c = remember(b, item("total upi spend ", 3));
    expect(c.map((x) => x.q)).toEqual(["total upi spend ", "How many credits?"]);
  });
  it("keeps at most twelve", () => {
    let list: HistoryItem[] = [];
    for (let i = 0; i < 20; i++) list = remember(list, item(`q${i}`, i));
    expect(list).toHaveLength(12);
    expect(list[0].q).toBe("q19");
  });
  it("round-trips through storage and ignores damaged content", () => {
    const s = fake();
    saveHistory([item("a")], s);
    expect(loadHistory(s)).toEqual([item("a")]);
    s.setItem("stmtai.ask.history", "{not json");
    expect(loadHistory(s)).toEqual([]);
    s.setItem("stmtai.ask.history", JSON.stringify([{ q: 1 }, item("ok")]));
    expect(loadHistory(s)).toEqual([item("ok")]);
    clearHistory(s);
    expect(loadHistory(s)).toEqual([]);
  });
  it("works when storage is missing or throws", () => {
    const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); }, removeItem: () => { throw new Error("blocked"); } };
    expect(loadHistory(broken)).toEqual([]);
    expect(() => saveHistory([item("a")], broken)).not.toThrow();
    expect(() => clearHistory(broken)).not.toThrow();
    expect(loadHistory(null)).toEqual([]);
  });
});
