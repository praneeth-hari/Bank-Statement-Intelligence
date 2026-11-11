import { monthGaps, monthLabel, PALETTE, ratio, share, typeColour, typeName } from "../lib/format";
import type { Overview, QualityCondition } from "../types";

const HEIGHT = 170;

/** One column per month with data. Months with no statement are a gap, not a zero. */
export function MonthBars({ months }: { months: Overview["by_month"] }) {
  const peak = Math.max(...months.map((m) => Number(m.debit)), 1);   // geometry only: a bar height, not a printed figure
  const gaps = monthGaps(months.map((m) => m.month));
  const years = [...new Set(months.map((m) => m.month.slice(0, 4)))];
  const gapBefore = new Map(gaps.map(([a, b]) => [a, [a, b] as [string, string]]));
  const next = (k: string) => { const i = Number(k.slice(0, 4)) * 12 + Number(k.slice(5, 7)); return `${Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, "0")}`; };
  return (
    <div>
      <div className="bt-bars" role="img" aria-label={`Debits for ${months.length} months`}>
        {months.map((m) => {
          const gap = gapBefore.get(next(m.month));
          return (
            <div key={m.month} className="bt-bargroup">
              <div className="bt-bar">
                <span>{shortK(m.debit)}</span>
                <i style={{ height: Math.max((Number(m.debit) / peak) * HEIGHT, 3), background: PALETTE[years.indexOf(m.month.slice(0, 4)) % 2] }} />
                <em>{monthLabel(m.month)}</em>
              </div>
              {gap && <div className="bt-gap" title={`No statements for ${monthLabel(gap[0], true)} to ${monthLabel(gap[1], true)}`} />}
            </div>
          );
        })}
      </div>
      {gaps.length > 0 && (
        <p className="bt-sub">
          No statements for {gaps.map(([a, b]) => (a === b ? monthLabel(a, true) : `${monthLabel(a, true)} to ${monthLabel(b, true)}`)).join(", ")}, so those months are skipped.
        </p>
      )}
    </div>
  );
}

function shortK(v: string): string {
  const n = Number(v);
  return n >= 100000 ? `${(n / 100000).toFixed(2)}L` : `${Math.round(n / 1000)}K`;
}

/** A ring split by transaction type; the legend beside it carries the exact shares. */
export function Donut({ types, total }: { types: Overview["by_type"]; total: string }) {
  const R = 70, C = 2 * Math.PI * R;
  let offset = 0;
  const top = types[0];
  return (
    <div className="bt-donut">
      <svg width="180" height="180" viewBox="0 0 180 180" role="img" aria-label={`Debits by type, ${top ? typeName(top.type) : "none"} largest`}>
        {types.map((t) => {
          const len = ratio(t.debit, total) * C;
          const el = <circle key={t.type} r={R} cx="90" cy="90" fill="none" stroke={typeColour(t.type)} strokeWidth="30"
                             strokeDasharray={`${Math.max(len - 2, 0.8)} ${C}`} strokeDashoffset={-offset} transform="rotate(-90 90 90)" />;
          offset += len;
          return el;
        })}
        {top && <>
          <text x="90" y="88" textAnchor="middle" className="bt-donut-n">{Math.round(Number(share(top.debit, total).replace("<", "")))}%</text>
          <text x="90" y="108" textAnchor="middle" className="bt-donut-l">{typeName(top.type)}</text>
        </>}
      </svg>
      <ul>
        {types.map((t) => (
          <li key={t.type}><i style={{ background: typeColour(t.type) }} /><span>{typeName(t.type)}</span><b>{share(t.debit, total)}%</b></li>
        ))}
      </ul>
    </div>
  );
}

const SQUARE = 5.6, PITCH = 7.3, COLS = 148;
export const OUTCOMES = [
  { key: "trusted_wrong", label: "Trusted but wrong", colour: "#FF7A59" },
  { key: "flagged_wrong", label: "Flagged, was wrong", colour: "#5B2EFF" },
  { key: "flagged_fine", label: "Flagged, was fine", colour: "#7DC9FF" },
  { key: "trusted_right", label: "Trusted and right", colour: "#E4DFFB" },
] as const;

/** One square per field, grouped by what happened to it. The few that matter come first, top left. */
export function FieldGrid({ c }: { c: QualityCondition }) {
  const rects: JSX.Element[] = [];
  let n = 0;
  for (const o of OUTCOMES) {
    for (let i = 0; i < c.outcomes[o.key]; i++, n++) {
      rects.push(<rect key={n} x={(n % COLS) * PITCH} y={Math.floor(n / COLS) * PITCH} width={SQUARE} height={SQUARE} rx="1.6" fill={o.colour} />);
    }
  }
  const rows = Math.ceil(n / COLS);
  return (
    <svg className="bt-grid-svg" viewBox={`0 0 ${COLS * PITCH} ${rows * PITCH}`} role="img"
         aria-label={OUTCOMES.map((o) => `${o.label}: ${c.outcomes[o.key]}`).join(". ")}>
      {rects}
    </svg>
  );
}
