import { useEffect, useState } from "react";
import { api } from "../api";
import { SamplesCard } from "../components/Samples";
import { Empty, Tile } from "../components/Shell";
import { count, rupees, shortDate } from "../lib/format";
import { ordinal, titleCase } from "../lib/transactions";
import type { Recurring, RecurringItem } from "../types";

function amountText(i: RecurringItem): string {
  if (i.amount_kind === "same") return `${rupees(i.low)} every time`;
  if (i.amount_kind === "close") return `${rupees(i.low)} to ${rupees(i.high)}, about the same`;
  return `${rupees(i.low)} to ${rupees(i.high)}, it varies`;
}

export function RecurringPage() {
  const [data, setData] = useState<Recurring | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => api.recurring().then(setData).catch((e: Error) => setError(e.message));
  useEffect(() => { void load(); }, []);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!data) return <p className="loading">Looking for payments that repeat…</p>;
  const title = <h1 className="bt-h1">What comes round again.</h1>;
  if (!data.has_data || data.reason) {
    return (
      <>
        {title}
        <Empty title={data.has_data ? "Not enough months yet" : "Nothing to look at yet"}>
          {data.reason ?? <>Approve a statement first. <a href="#/statements">Go to Statements</a></>}
        </Empty>
        <SamplesCard onLoaded={() => void load()} />
      </>
    );
  }
  const out = data.items.filter((i) => i.direction === "debit").length, inn = data.items.length - out;
  return (
    <>
      {title}
      <div className="bt-grid">
        <Tile className="bt-violet c4"><div className="bt-label">Payments that repeat</div><div className="bt-big" data-testid="recurring-count">{count(data.items.length)}</div>
          <p>{count(out)} going out, {count(inn)} coming in</p></Tile>
        <Tile className="bt-sky c4"><div className="bt-label">Months looked at</div><div className="bt-big">{count(data.months_covered)}</div><p>Months with an approved statement</p></Tile>
        <Tile className="bt-butter c4"><div className="bt-label">What counts</div><p className="bt-rule">{data.rules}</p></Tile>

        <Tile className="c12">
          {data.items.length === 0
            ? <p className="bt-sub" data-testid="nothing-repeats">Nothing repeats in these statements. A payment needs to turn up in several different months to count.</p>
            : <ul className="bt-rec" data-testid="recurring-list">{data.items.map((i) => (
                <li key={`${i.direction}-${i.rail}-${i.label}`}>
                  <div className="who">
                    <b>{titleCase(i.label)}</b>
                    <small>{i.rail ? `via ${i.rail} · ` : ""}around the {ordinal(i.day_of_month)}</small>
                  </div>
                  <div className="seen"><b>{count(i.months)} months</b><small>{count(i.count)} {i.count === 1 ? "payment" : "payments"}, {shortDate(i.first_date)} to {shortDate(i.last_date)}</small></div>
                  <div className="amt"><b className={i.direction === "credit" ? "in" : ""}>{i.direction === "credit" ? "In" : "Out"}</b><small>{amountText(i)}</small></div>
                  <div className="tot"><b>{rupees(i.total)}</b><small>in total</small></div>
                  <details><summary>Dates</summary><p>{i.dates.map(shortDate).join(", ")}</p></details>
                </li>
              ))}</ul>}
        </Tile>
      </div>
      <p className="bt-foot">{data.note}</p>
    </>
  );
}
