import { describe, expect, it } from "vitest";
import { fromPaise } from "./money";
import { parseRoute } from "./route";
import { amountProblem, EMPTY, isFiltered, ordinal, titleCase, toParams } from "./transactions";

describe("transaction filters", () => {
  it("sends only the filters that are set, with the sort split into its two parts", () => {
    const p = toParams({ ...EMPTY, q: " upi ", min: "100", direction: "debit", sort: "amount-asc" }, 100, 200);
    expect(Object.fromEntries(p)).toEqual({ q: "upi", min_amount: "100", direction: "debit", sort: "amount", order: "asc", limit: "100", offset: "200" });
    expect(Object.fromEntries(toParams(EMPTY, 50, 0))).toEqual({ sort: "date", order: "desc", limit: "50", offset: "0" });
  });
  it("knows when something is filtered, and sorting does not count", () => {
    expect(isFiltered(EMPTY)).toBe(false);
    expect(isFiltered({ ...EMPTY, sort: "amount-asc" })).toBe(false);
    expect(isFiltered({ ...EMPTY, category: "Health" })).toBe(true);
    expect(isFiltered({ ...EMPTY, direction: "credit" })).toBe(true);
  });
  it("accepts plain amounts and refuses anything else", () => {
    expect(amountProblem({ min: "", max: "" })).toBeNull();
    expect(amountProblem({ min: "1500", max: "1500.5" })).toBeNull();
    for (const bad of ["-5", "1,500", "abc", "1.234", "₹5"]) expect(amountProblem({ min: bad, max: "" })).not.toBeNull();
  });
});

describe("wording", () => {
  it("title-cases statement text but keeps the banking words in capitals", () => {
    expect(titleCase("EMI HOME LOAN")).toBe("EMI Home Loan");
    expect(titleCase("AIRTEL PAYMENTS")).toBe("Airtel Payments");
    expect([titleCase("IRCTC"), titleCase("DMART"), titleCase("BIGBASKET")]).toEqual(["IRCTC", "DMart", "BigBasket"]);
    expect(titleCase("ORBITAL SOFTWARE PVT LTD SALARY")).toBe("Orbital Software Pvt Ltd Salary");
  });
  it("writes ordinals, including the teens", () => {
    expect([1, 2, 3, 4, 9, 11, 12, 13, 21, 22, 23, 30].map(ordinal)).toEqual(["1st", "2nd", "3rd", "4th", "9th", "11th", "12th", "13th", "21st", "22nd", "23rd", "30th"]);
  });
  it("turns paise back into an exact two-decimal string", () => {
    expect([fromPaise(3010n), fromPaise(5n), fromPaise(0n), fromPaise(-1234n)]).toEqual(["30.10", "0.05", "0.00", "-12.34"]);
  });
  it("routes the two new pages", () => {
    expect(parseRoute("#/transactions")).toEqual({ name: "transactions" });
    expect(parseRoute("#/recurring/")).toEqual({ name: "recurring" });
  });
});
