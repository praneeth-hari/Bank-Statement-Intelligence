import { formatMoneyString } from "./money";

/** An amount or a count from /query, formatted without floating point so no digit can change on the way to the screen. */
export function money(v: string | null | undefined, unit?: string): string {
  if (v == null) return "";
  if (unit === "transactions") return /^\d+$/.test(v) ? BigInt(v).toLocaleString("en-IN") : v;
  return formatMoneyString(v) ?? v;
}

const CAPS = new Set(["upi", "imps", "neft", "pos", "atm", "emi"]);

/** Group keys come from the API in lower case: transaction types are acronyms, the rest are words. */
export function groupLabel(key: string): string {
  if (/^\d{4}-\d{2}$/.test(key)) return key;
  return CAPS.has(key) ? key.toUpperCase() : key.charAt(0).toUpperCase() + key.slice(1);
}
