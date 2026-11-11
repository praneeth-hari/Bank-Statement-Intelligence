import { formatMoneyString, parsePaise } from "./money";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "6622451.98" -> "₹6,22,451.98". Exact: the string goes through integer paise, never a float. */
export function rupees(v: string | null | undefined): string {
  const f = formatMoneyString(v);
  return f === null ? "" : (f.startsWith("-") ? "-₹" + f.slice(1) : "₹" + f);
}

/** "2026-07-10" -> "10 Jul 2026" (fixed English month names, so the text does not depend on the browser's locale). */
export function shortDate(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? "");
  if (!m) return iso ?? "";
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1] ?? m[2]} ${m[1]}`;
}

/** "2025-04" -> "Apr 25" for an axis, or "Apr 2025" in running text. */
export function monthLabel(key: string, long = false): string {
  const m = /^(\d{4})-(\d{2})$/.exec(key);
  if (!m) return key;
  return `${MONTHS[Number(m[2]) - 1] ?? m[2]} ${long ? m[1] : m[1].slice(2)}`;
}

/** The months with no data between two that have some. Returned as [firstMissing, lastMissing] pairs. */
export function monthGaps(keys: string[]): [string, string][] {
  const idx = (k: string) => Number(k.slice(0, 4)) * 12 + Number(k.slice(5, 7)) - 1;
  const key = (i: number) => `${Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, "0")}`;
  const out: [string, string][] = [];
  const sorted = [...keys].sort();
  for (let i = 1; i < sorted.length; i++) {
    const a = idx(sorted[i - 1]), b = idx(sorted[i]);
    if (b - a > 1) out.push([key(a + 1), key(b - 1)]);
  }
  return out;
}

/** Statements print the bank name in capitals. Show a name that is all capitals in ordinary case, leave the rest alone. */
export function bankName(name: string | null | undefined): string {
  const n = (name ?? "").trim();
  if (!n) return "";
  if (n !== n.toUpperCase()) return n;
  return n.toLowerCase().replace(/(^|[\s&/-])([a-z])/g, (_, sep: string, c: string) => sep + c.toUpperCase());
}

const TYPE_NAMES: Record<string, string> = {
  upi: "UPI", imps: "IMPS", neft: "NEFT", pos: "Card (POS)", atm: "ATM cash", emi: "EMI",
  charges: "Bank charges", salary: "Salary", interest: "Interest", other: "Other",
};
export const typeName = (t: string): string => TYPE_NAMES[t] ?? t.charAt(0).toUpperCase() + t.slice(1);

/** Colours are fixed per type so UPI is the same colour on every screen. */
export const PALETTE = ["#5B2EFF", "#FF7A59", "#16113A", "#7DC9FF", "#D6F54A", "#B7B0E8", "#FFE59A", "#0E9F6E"];
const TYPE_COLOURS: Record<string, string> = {
  upi: "#5B2EFF", pos: "#FF7A59", atm: "#16113A", imps: "#7DC9FF", emi: "#D6F54A", charges: "#B7B0E8",
  neft: "#FFE59A", salary: "#0E9F6E", interest: "#9BD8B5", other: "#C9C3EE",
};
export const typeColour = (t: string): string => TYPE_COLOURS[t] ?? "#C9C3EE";

/** Share of a total as a percentage with one decimal, from integer paise ("<0.1" when it rounds to nothing). */
export function share(part: string, total: string): string {
  const p = parsePaise(part), t = parsePaise(total);
  if (p === null || t === null || t === 0n) return "0.0";
  const tenths = (p * 1000n) / t;
  if (tenths === 0n && p > 0n) return "<0.1";
  return `${tenths / 10n}.${tenths % 10n}`;
}

/** Sum of strings, in paise. */
export function sumPaise(values: string[]): bigint {
  return values.reduce((a, v) => a + (parsePaise(v) ?? 0n), 0n);
}

/** Geometry only (bar heights, arc lengths): where rounding to a float cannot change a printed figure. */
export const ratio = (part: string, whole: string): number => {
  const p = parsePaise(part), w = parsePaise(whole);
  return p === null || w === null || w === 0n ? 0 : Number(p) / Number(w);
};

export const count = (n: number): string => n.toLocaleString("en-IN");
export const percent = (x: number | null | undefined, digits = 1): string => (x == null ? "" : `${(x * 100).toFixed(digits)}%`);
