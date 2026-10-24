import { describe, expect, it } from "vitest";
import { groupLabel, money } from "./ask";

describe("query answers on screen", () => {
  it("formats amounts exactly, with Indian grouping", () => {
    expect(money("86657.17")).toBe("86,657.17");
    expect(money("15540.00")).toBe("15,540.00");
    expect(money("1234567.50")).toBe("12,34,567.50");
    expect(money("0.10")).toBe("0.10");
    expect(money("9007199254740993.01")).toBe("9,00,71,99,25,47,40,993.01"); // beyond float precision
  });
  it("formats counts as whole numbers and passes through what it cannot read", () => {
    expect(money("28", "transactions")).toBe("28");
    expect(money("12345", "transactions")).toBe("12,345");
    expect(money(null)).toBe("");
    expect(money("n/a")).toBe("n/a");
  });
  it("names groups the way a person writes them", () => {
    expect(groupLabel("upi")).toBe("UPI");
    expect(groupLabel("emi")).toBe("EMI");
    expect(groupLabel("charges")).toBe("Charges");
    expect(groupLabel("2025-04")).toBe("2025-04");
    expect(groupLabel("harsh chahal")).toBe("Harsh chahal");
  });
});
