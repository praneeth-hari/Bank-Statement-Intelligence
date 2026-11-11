import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { Donut, MonthBars } from "../components/charts";
import { SamplesCard } from "../components/Samples";
import { Empty, Tile } from "../components/Shell";
import { bankName, count, rupees, shortDate } from "../lib/format";
import { parsePaise } from "../lib/money";
import type { Overview } from "../types";

export function Dashboard() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.overview().then(setData).catch((e: Error) => setError(e.message)), []);
  useEffect(() => { void load(); }, [load]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!data) return <p className="loading">Adding up your statements…</p>;

  const s = data.statements;
  if (!data.has_data) {
    return (
      <>
        <h1 className="bt-h1">Your money, at a glance.</h1>
        <Empty title="Nothing to show yet">
          {s.total === 0
            ? <>Upload a statement to see what was extracted. Then approve it, and its numbers appear here. <a href="#/statements">Go to Statements</a></>
            : <>{s.awaiting} {s.awaiting === 1 ? "statement is" : "statements are"} waiting for review. Numbers here use approved statements only, so a total is never built on cells nobody checked. <a href="#/statements">Review a statement</a></>}
        </Empty>
        <SamplesCard onLoaded={() => void load()} />
      </>
    );
  }

  const t = data.totals;
  return (
    <>
      <div className="bt-head">
        <h1 className="bt-h1">Your money, {s.approved} {s.approved === 1 ? "statement" : "statements"} in.</h1>
        <a className="bt-dl" href={api.transactionsUrl()} download data-testid="download">Download CSV</a>
      </div>
      <div className="bt-grid">
        <Tile className="bt-violet c4" data-testid="spent"><div className="bt-label">You spent</div><div className="bt-big">{rupees(t.debit)}</div><p>{count(t.debits)} debits</p></Tile>
        <Tile className="bt-lime c4" data-testid="received"><div className="bt-label">You received</div><div className="bt-big">{rupees(t.credit)}</div><p>{count(t.credits)} credits</p></Tile>
        <Tile className="bt-butter c4"><div className="bt-label">Transactions counted</div><div className="bt-big">{count(t.transactions)}</div>
          <p>{data.notes[0] ?? "Counted from the approved statement."}</p></Tile>

        <Tile className="c7">
          <h3>Spending by month</h3><p className="bt-sub">Debits only. A month with no statement is skipped, not shown as zero.</p>
          <MonthBars months={data.by_month} />
        </Tile>
        <Tile className="bt-sky c5">
          <h3>Where it went</h3><p className="bt-sub">Share of all debits, by transaction type.</p>
          <Donut types={data.by_type} total={t.debit} />
        </Tile>

        <Tile className="c6">
          <h3>Balance by statement</h3><p className="bt-sub">First balance to last, one account each. They are never added together.</p>
          <ul className="bt-list">
            {data.balances.map((b) => {
              const first = parsePaise(b.first_balance) ?? 0n, last = parsePaise(b.last_balance) ?? 0n;
              return (
                <li key={b.statement_id}>
                  <div>
                    <a href={`#/s/${b.statement_id}`} className="bt-strong" title={b.filename}>{bankName(b.bank) || b.filename}</a>
                    <small>{shortDate(b.period_start)} to {shortDate(b.period_end)}</small>
                  </div>
                  <span className="bt-from">{rupees(b.first_balance)}</span>
                  <span aria-label="to">→</span>
                  <b className={last > first ? "up" : last < first ? "down" : ""}>{rupees(b.last_balance)}</b>
                </li>
              );
            })}
          </ul>
        </Tile>
        <Tile className="c6">
          <h3>Largest debits</h3><p className="bt-sub">Select one to open the statement it came from.</p>
          <table className="bt-table">
            <tbody>
              {data.largest_debits.map((d) => (
                <tr key={`${d.statement_id}-${d.row}`}>
                  <td className="bt-date">{shortDate(d.date)}</td>
                  <td className="bt-desc"><a href={`#/s/${d.statement_id}`} title={d.filename}>{d.description}</a></td>
                  <td className="bt-amt">{rupees(d.debit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Tile>
      </div>
    </>
  );
}
