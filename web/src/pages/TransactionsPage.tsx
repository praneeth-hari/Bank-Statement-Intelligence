import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { CategoriesPanel } from "../components/CategoriesPanel";
import { SamplesCard } from "../components/Samples";
import { Empty, Tile } from "../components/Shell";
import { count, rupees, shortDate, typeName } from "../lib/format";
import { amountProblem, EMPTY, isFiltered, SORTS, toParams, type SortKey, type TxFilters } from "../lib/transactions";
import type { TxPage } from "../types";

const PAGE = 50;

export function TransactionsPage() {
  const [f, setF] = useState<TxFilters>(EMPTY);
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<TxPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showCats, setShowCats] = useState(false);
  const [version, setVersion] = useState(0);              // bumped when the rules change, so the list is fetched again
  const seq = useRef(0);
  const problem = amountProblem(f);

  const set = (patch: Partial<TxFilters>) => { setF((x) => ({ ...x, ...patch })); setOffset(0); };

  useEffect(() => {
    if (problem) return;
    const id = ++seq.current;                             // an older, slower answer must not overwrite a newer one
    const t = setTimeout(() => {
      api.transactions(toParams(f, PAGE, offset))
        .then((d) => { if (id === seq.current) { setData(d); setError(null); } })
        .catch((e: Error) => { if (id === seq.current) setError(e.message); });
    }, 200);
    return () => clearTimeout(t);
  }, [f, offset, version, problem]);

  // a category that no longer exists (its rule was removed) must not stay selected
  useEffect(() => {
    if (data && f.category && !data.facets.categories.some((c) => c.toLowerCase() === f.category.toLowerCase())) set({ category: "" });
  }, [data]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (error && !data) return <p className="error" role="alert">{error}</p>;
  if (!data) return <p className="loading">Looking through your transactions…</p>;
  if (!data.has_data) {
    return (
      <>
        <h1 className="bt-h1">Every transaction.</h1>
        <Empty title="Nothing to search yet">Approve a statement and its transactions appear here. <a href="#/statements">Go to Statements</a></Empty>
        <SamplesCard onLoaded={() => setVersion((v) => v + 1)} />
      </>
    );
  }

  const from = data.matched === 0 ? 0 : data.offset + 1, to = Math.min(data.offset + data.rows.length, data.matched);
  const filtered = isFiltered(f);
  return (
    <>
      <div className="bt-head">
        <h1 className="bt-h1">Every transaction.</h1>
        <button type="button" className="bt-dl" onClick={() => setShowCats((v) => !v)} aria-expanded={showCats} data-testid="toggle-categories">
          {showCats ? "Hide categories" : "Categories"}
        </button>
      </div>
      <div className="bt-stack">
        {showCats && <CategoriesPanel onChanged={() => setVersion((v) => v + 1)} />}

        <Tile className="bt-filters" data-testid="filters">
          <div className="bt-frow">
            <label className="grow">Search descriptions<input type="search" value={f.q} onChange={(e) => set({ q: e.target.value })} placeholder="airtel, emi, salary…" data-testid="filter-q" /></label>
            <label>From<input type="date" value={f.from} onChange={(e) => set({ from: e.target.value })} data-testid="filter-from" /></label>
            <label>To<input type="date" value={f.to} onChange={(e) => set({ to: e.target.value })} /></label>
            <label className="narrow">Min ₹<input inputMode="decimal" value={f.min} onChange={(e) => set({ min: e.target.value })} placeholder="0" aria-invalid={!!problem} /></label>
            <label className="narrow">Max ₹<input inputMode="decimal" value={f.max} onChange={(e) => set({ max: e.target.value })} placeholder="any" aria-invalid={!!problem} /></label>
          </div>
          <div className="bt-frow">
            <label>Money<select value={f.direction} onChange={(e) => set({ direction: e.target.value as TxFilters["direction"] })} data-testid="filter-direction">
              <option value="any">In and out</option><option value="debit">Spent</option><option value="credit">Received</option></select></label>
            <label>Type<select value={f.type} onChange={(e) => set({ type: e.target.value })}>
              <option value="">All types</option>{data.facets.types.map((t) => <option key={t} value={t}>{typeName(t)}</option>)}</select></label>
            <label>Category<select value={f.category} onChange={(e) => set({ category: e.target.value })} data-testid="filter-category">
              <option value="">All categories</option>{data.facets.categories.map((c) => <option key={c} value={c}>{c}</option>)}</select></label>
            <label>Statement<select value={f.statement} onChange={(e) => set({ statement: e.target.value })}>
              <option value="">All statements</option>{data.facets.statements.map((s) => <option key={s.id} value={s.id}>{s.filename}</option>)}</select></label>
            <label>Order<select value={f.sort} onChange={(e) => set({ sort: e.target.value as SortKey })}>
              {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}</select></label>
            {filtered && <button type="button" className="bt-linkbtn" onClick={() => { setF(EMPTY); setOffset(0); }}>Clear filters</button>}
          </div>
          {problem && <p className="bt-error" role="alert">{problem}</p>}
          {error && <p className="bt-error" role="alert">{error}</p>}
        </Tile>

        <p className="bt-sum" data-testid="summary" aria-live="polite">
          <b>{count(data.matched)}</b> {data.matched === 1 ? "transaction" : "transactions"}{filtered ? " match" : ""}.
          {" "}Spent <b>{rupees(data.totals.debit)}</b> across {count(data.totals.debits)}, received <b>{rupees(data.totals.credit)}</b> across {count(data.totals.credits)}.
          {data.notes[0] && <span> {data.notes[0]}</span>}
        </p>

        <Tile className="bt-txtile">
          {data.rows.length === 0 ? (
            <p className="bt-sub" data-testid="nomatch">Nothing matches these filters. <button type="button" className="bt-linkbtn" onClick={() => { setF(EMPTY); setOffset(0); }}>Clear filters</button></p>
          ) : (
            <div className="bt-scroll">
              <table className="bt-table bt-tx" data-testid="tx-table">
                <thead><tr><th>Date</th><th>Description</th><th>Category</th><th className="r">Spent</th><th className="r">Received</th><th>Source</th></tr></thead>
                <tbody>{data.rows.map((r) => (
                  <tr key={`${r.statement_id}-${r.row}`}>
                    <td className="bt-date">{shortDate(r.date)}</td>
                    <td className="bt-desc">{r.description}</td>
                    <td>{r.category === "Uncategorised" ? <span className="bt-cat none">Uncategorised</span> : <span className="bt-cat">{r.category}</span>}</td>
                    <td className="bt-amt">{r.debit ? rupees(r.debit) : ""}</td>
                    <td className="bt-amt in">{r.credit ? rupees(r.credit) : ""}</td>
                    <td><a className="bt-src" href={`#/s/${r.statement_id}`} title={r.filename}>Open</a></td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
          {data.matched > PAGE && (
            <div className="bt-pager">
              <span>Showing {count(from)} to {count(to)} of {count(data.matched)}</span>
              <div>
                <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
                <button type="button" disabled={to >= data.matched} onClick={() => setOffset(offset + PAGE)} data-testid="next">Next</button>
              </div>
            </div>
          )}
        </Tile>
      </div>
    </>
  );
}
