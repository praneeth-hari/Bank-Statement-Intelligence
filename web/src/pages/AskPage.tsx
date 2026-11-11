import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Tile } from "../components/Shell";
import { PALETTE } from "../lib/format";
import { groupLabel, money } from "../lib/ask";
import { clearHistory, loadHistory, remember, saveHistory, type HistoryItem } from "../lib/history";
import type { QueryResponse } from "../types";

const EXAMPLES = ["Total UPI spend", "My 5 largest debits", "Spending by month", "How many credits?"];
const SHOWN = 8;
const EARLIER = 3;

interface Asked { q: string; reply: QueryResponse }

/** The one-line result kept in the recent-questions list. */
export function summary(r: QueryResponse): string {
  if (!r.answered) return "Not answered";
  if (r.kind === "number") return (r.unit === "INR" ? "₹" : "") + money(r.value, r.unit) + (r.unit === "transactions" ? " transactions" : "");
  if (r.kind === "groups") return `${r.groups?.length ?? 0} groups`;
  if (r.kind === "rows") return `${r.matched ?? 0} transactions`;
  return "No matching transactions";
}

function Rows({ r }: { r: QueryResponse }) {
  const rows = r.rows ?? [];
  if (rows.length === 0 || r.kind === "groups") return null;
  return (
    <>
      <table className="bt-table">
        <thead><tr><th>Date</th><th>Description</th><th className="r">Debit</th><th className="r">Credit</th><th>Source</th></tr></thead>
        <tbody>{rows.slice(0, SHOWN).map((x) => (
          <tr key={`${x.statement_id}-${x.row}`}>
            <td className="bt-date">{x.date}</td><td className="bt-desc">{x.description}</td>
            <td className="bt-amt">{money(x.debit)}</td><td className="bt-amt">{money(x.credit)}</td>
            <td><a className="bt-src" href={`#/s/${x.statement_id}`} title={x.filename}>Open</a></td>
          </tr>
        ))}</tbody>
      </table>
      <p className="bt-sub">
        {r.kind === "rows" ? `Showing ${Math.min(rows.length, SHOWN)} of ${r.matched} matching transactions.`
          : `The answer counts ${r.matched} transaction${r.matched === 1 ? "" : "s"}. Showing ${Math.min(rows.length, SHOWN)}.`}
      </p>
    </>
  );
}

function Groups({ r }: { r: QueryResponse }) {
  const groups = r.groups ?? [];
  const peak = Math.max(...groups.map((g) => Number(g.value)), 1);   // geometry only
  return (
    <div className="bt-groups">
      {groups.map((g, i) => (
        <div key={g.key} className="bt-grow">
          <span>{groupLabel(g.key)}</span>
          <div className="bt-pill"><div style={{ width: `${Math.max((Number(g.value) / peak) * 100, 1.5)}%`, background: PALETTE[i % PALETTE.length] }} /></div>
          <b>{r.unit === "transactions" ? "" : "₹"}{money(g.value, r.unit)}</b>
        </div>
      ))}
    </div>
  );
}

function AnswerTile({ a, latest }: { a: Asked; latest: boolean }) {
  const r = a.reply;
  const testid = latest ? (r.answered ? "answer" : "refusal") : "answer-earlier";
  if (!r.answered) {
    return (
      <Tile className="bt-butter" role="status" data-testid={testid}>
        <h3 className="bt-q">{a.q}</h3>
        <p className="bt-refusal"><b>No answer.</b> {r.reason}</p>
      </Tile>
    );
  }
  const model = r.parser === "model";
  const number = r.kind === "number";
  return (
    <Tile className={`bt-answer ${number ? "has-head" : ""}`} aria-live={latest ? "polite" : undefined} data-testid={testid}>
      <div className={number ? "bt-answer-head" : undefined}>
        <div className="bt-answer-title">
          <h3 className="bt-q">{a.q}</h3>
          <span className={`bt-tag ${model ? "model" : ""}`}>{model ? "Read by a language model, check this reading" : "Read by rules"}</span>
        </div>
        {number && <div className="bt-answer-big">{r.unit === "INR" && <span>₹</span>}{money(r.value, r.unit)}{r.unit === "transactions" && <span> transactions</span>}</div>}
        {r.kind === "none" && <p className="bt-none">No matching transactions</p>}
        <p className="bt-sub">Read as <b>{r.interpretation}</b></p>
      </div>
      <div className={number ? "bt-answer-body" : undefined}>
        {r.kind === "groups" && <Groups r={r} />}
        <Rows r={r} />
        {r.notes.map((n) => <p className="bt-note" key={n}>{n}</p>)}
      </div>
    </Tile>
  );
}

export function AskPage() {
  const [approved, setApproved] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [latest, setLatest] = useState<Asked | null>(null);
  const [earlier, setEarlier] = useState<Asked[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>(() => loadHistory());
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { api.overview().then((o) => setApproved(o.statements.approved)).catch(() => setApproved(0)); }, []);

  async function ask(question: string) {
    const q = question.trim();
    if (!q) return;
    setBusy(true); setError(null);
    try {
      const reply = await api.ask(q);
      setEarlier((e) => (latest ? [latest, ...e] : e).slice(0, EARLIER));
      setLatest({ q, reply });
      const next = remember(history, { q, result: summary(reply), answered: reply.answered, at: Date.now() });
      setHistory(next); saveHistory(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not ask.");
    } finally {
      setBusy(false);
    }
  }

  const none = approved === 0;
  return (
    <>
      <h1 className="bt-h1">Ask your statements.</h1>
      <div className="bt-grid">
        <div className="c8 bt-stack">
          <Tile className="bt-violet bt-askbox" data-testid="ask">
            <form onSubmit={(e) => { e.preventDefault(); void ask(text); }}>
              <input ref={input} value={text} onChange={(e) => setText(e.target.value)} disabled={none || busy || approved === null} maxLength={300}
                     placeholder="For example: how much did I spend on UPI in March?" aria-label="Your question" data-testid="ask-input" />
              <button className="bt-go" disabled={none || busy || !text.trim()}>{busy ? "Asking…" : "Ask"}</button>
            </form>
            {none
              ? <p className="bt-onviolet">Approve a statement first. Answers use approved statements only, so a number is never built on cells nobody has checked. <a href="#/statements">Go to Statements</a></p>
              : <>
                  <p className="bt-onviolet">Try one of these</p>
                  <div className="bt-chips">{EXAMPLES.map((x) => (
                    <button key={x} type="button" disabled={busy || approved === null} onClick={() => { setText(x); void ask(x); }}>{x}</button>
                  ))}</div>
                </>}
            {error && <p className="bt-error" role="alert">{error}</p>}
          </Tile>

          {latest && <AnswerTile a={latest} latest />}
          {earlier.length > 0 && (
            <section aria-label="Earlier answers" className="bt-stack" data-testid="earlier">
              {earlier.map((a, i) => <AnswerTile key={`${a.q}-${i}`} a={a} latest={false} />)}
            </section>
          )}
          {!latest && !none && approved !== null && <p className="bt-hint">Answers list the transactions behind every number. A question that cannot be read reliably is refused with a reason, never guessed.</p>}
        </div>

        <Tile className="c4 bt-recent" data-testid="recent">
          <div className="bt-rhead"><h3>Recent questions</h3>
            {history.length > 0 && <button type="button" className="bt-linkbtn" onClick={() => { clearHistory(); setHistory([]); }}>Clear</button>}</div>
          <p className="bt-sub">Kept in this browser only.</p>
          {history.length === 0
            ? <p className="bt-sub">Questions you ask will be listed here.</p>
            : <ul className="bt-hist">{history.map((h) => (
                <li key={h.q}>
                  <button type="button" disabled={none || busy} onClick={() => { setText(h.q); void ask(h.q); }}>
                    <b>{h.q}</b><small className={h.answered ? "" : "bad"}>{h.result}</small>
                  </button>
                </li>
              ))}</ul>}
          <p className="bt-callout">Questions that cannot be read reliably are refused with a reason, never guessed.</p>
        </Tile>
      </div>
    </>
  );
}
