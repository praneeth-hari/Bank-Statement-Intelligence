/** The Transactions page's filters, kept apart from the screen so they can be tested. */

export type SortKey = "date-desc" | "date-asc" | "amount-desc" | "amount-asc";

export interface TxFilters {
  q: string; from: string; to: string; min: string; max: string;
  type: string; direction: "any" | "debit" | "credit"; statement: string; category: string; sort: SortKey;
}

export const EMPTY: TxFilters = { q: "", from: "", to: "", min: "", max: "", type: "", direction: "any", statement: "", category: "", sort: "date-desc" };
export const SORTS: { value: SortKey; label: string }[] = [
  { value: "date-desc", label: "Newest first" }, { value: "date-asc", label: "Oldest first" },
  { value: "amount-desc", label: "Largest first" }, { value: "amount-asc", label: "Smallest first" },
];

const AMOUNT = /^\d+(\.\d{1,2})?$/;

/** What is wrong with the amount boxes, or null. An empty box is fine: it means no limit. */
export function amountProblem(f: Pick<TxFilters, "min" | "max">): string | null {
  for (const v of [f.min.trim(), f.max.trim()]) if (v !== "" && !AMOUNT.test(v)) return "Amounts are numbers like 1500 or 1500.50.";
  return null;
}

/** True when any filter is set, so the page can offer to clear them. Sorting is not a filter. */
export function isFiltered(f: TxFilters): boolean {
  return Object.entries(f).some(([k, v]) => k !== "sort" && v !== "" && v !== "any");
}

/** Only filters that are set are sent. */
export function toParams(f: TxFilters, limit: number, offset: number): URLSearchParams {
  const p = new URLSearchParams();
  const put = (k: string, v: string) => { if (v.trim() !== "") p.set(k, v.trim()); };
  put("q", f.q); put("date_from", f.from); put("date_to", f.to); put("min_amount", f.min); put("max_amount", f.max);
  put("type", f.type); put("statement_id", f.statement); put("category", f.category);
  if (f.direction !== "any") p.set("direction", f.direction);
  const [sort, order] = f.sort.split("-");
  p.set("sort", sort); p.set("order", order);
  p.set("limit", String(limit)); p.set("offset", String(offset));
  return p;
}

const KEEP_UPPER = new Set(["EMI", "UPI", "IMPS", "NEFT", "ECS", "ATM", "POS", "SMS", "AMC", "GST", "INR", "NACH", "RTGS", "IFSC", "EMIS"]);

const BRANDS: Record<string, string> = { IRCTC: "IRCTC", DMART: "DMart", BIGBASKET: "BigBasket", BOOKMYSHOW: "BookMyShow", PHARMEASY: "PharmEasy", MYNTRA: "Myntra" };

/** "ECS EMI HOME LOAN" -> "EMI Home Loan". Statements print in capitals; keep the short banking words in capitals. */
export function titleCase(label: string): string {
  return label.toLowerCase().split(/\s+/).filter(Boolean).map((w) => {
    const up = w.toUpperCase();
    return BRANDS[up] ?? (KEEP_UPPER.has(up) ? up : w.charAt(0).toUpperCase() + w.slice(1));
  }).join(" ");
}

/** 1 -> "1st", 9 -> "9th", 22 -> "22nd", 11 -> "11th". */
export function ordinal(n: number): string {
  const v = n % 100;
  const suffix = v >= 11 && v <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${suffix}`;
}
