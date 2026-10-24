/** Money is handled as integer paise (bigint) so 0.1 + 0.2 style rounding can never creep into a check. */

export function parsePaise(value: string | null | undefined): bigint | null {
  if (value == null) return null;
  const m = /^(-)?(\d+)(?:\.(\d{1,2}))?$/.exec(value.replace(/,/g, "").trim());
  if (!m) return null;
  const paise = BigInt(m[2]) * 100n + BigInt((m[3] ?? "").padEnd(2, "0") || "0");
  return m[1] ? -paise : paise;
}

/** 12334420n -> "1,23,344.20" (Indian digit grouping, as printed on the statements). */
export function formatInr(paise: bigint): string {
  const negative = paise < 0n;
  const abs = negative ? -paise : paise;
  const whole = (abs / 100n).toString();
  const frac = (abs % 100n).toString().padStart(2, "0");
  const grouped = whole.length <= 3
    ? whole
    : whole.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + whole.slice(-3);
  return `${negative ? "-" : ""}${grouped}.${frac}`;
}

export function formatMoneyString(value: string | null | undefined): string | null {
  const p = parsePaise(value);
  return p === null ? null : formatInr(p);
}

export const MONEY_FIELDS = new Set(["debit", "credit", "balance", "opening_balance", "closing_balance"]);
export const DATE_FIELDS = new Set(["date", "value_date", "period_start", "period_end"]);

/** "2025-04-02" -> "02/04/2025" */
export function formatDate(iso: string | null | undefined): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso ?? "");
  return m ? `${m[3]}/${m[2]}/${m[1]}` : null;
}

/** What a reviewer should see for a field value, in the format the statement itself uses. */
export function displayValue(field: string, value: string | null, fallback = ""): string {
  if (value == null || value === "") return fallback;
  if (MONEY_FIELDS.has(field)) return formatMoneyString(value) ?? value;
  if (DATE_FIELDS.has(field)) return formatDate(value) ?? value;
  return value;
}
