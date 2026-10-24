import { useState } from "react";
import { api } from "../api";
import { groupLabel, money } from "../lib/ask";
import type { QueryResponse } from "../types";

const EXAMPLES = ["Total UPI spend", "My 5 largest debits", "Spending by month", "How many credits?"];
const SHOWN = 8;

function Answer({ r }: { r: QueryResponse }) {
  const unit = r.unit === "transactions" ? "transactions" : "₹";
  const rows = r.rows ?? [];
  return (
    <section className="answer" aria-live="polite" data-testid="answer">
      {r.kind === "number" && (
        <p className="big">{r.unit === "INR" && <span>₹</span>}{money(r.value, r.unit)}{r.unit === "transactions" && <span> transactions</span>}</p>
      )}
      {r.kind === "none" && <p className="big none">No matching transactions</p>}
      {r.kind === "groups" && (
        <table className="tbl groups">
          <tbody>{(r.groups ?? []).map((g) => (
            <tr key={g.key}><td>{groupLabel(g.key)}</td><td className="num">{unit === "₹" ? "₹" : ""}{money(g.value, r.unit)}</td></tr>
          ))}</tbody>
        </table>
      )}
      <p className={`read ${r.parser === "model" ? "model" : ""}`}>
        <span>Understood as</span> <b>{r.interpretation}</b>
        <em>{r.parser === "model" ? "read by a language model, check this reading" : "read by rules"}</em>
      </p>
      {r.notes.map((n) => <p className="note" key={n}>{n}</p>)}
      {rows.length > 0 && r.kind !== "groups" && (
        <>
          <table className="tbl">
            <thead><tr><th>Date</th><th>Description</th><th className="num">Debit</th><th className="num">Credit</th><th /></tr></thead>
            <tbody>{rows.slice(0, SHOWN).map((x) => (
              <tr key={`${x.statement_id}-${x.row}`}>
                <td>{x.date}</td><td className="desc">{x.description}</td>
                <td className="num">{money(x.debit)}</td><td className="num">{money(x.credit)}</td>
                <td><a href={`#/s/${x.statement_id}`} title={x.filename}>Open</a></td>
              </tr>
            ))}</tbody>
          </table>
          <p className="d">
            {r.kind === "rows" ? `Showing ${Math.min(rows.length, SHOWN)} of ${r.matched} matching transactions.`
              : `The answer counts ${r.matched} transaction${r.matched === 1 ? "" : "s"}. Showing ${Math.min(rows.length, SHOWN)}.`}
          </p>
        </>
      )}
    </section>
  );
}

export function AskPanel({ approved }: { approved: number }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [reply, setReply] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function ask(question: string) {
    const q = question.trim();
    if (!q) return;
    setBusy(true); setError(null);
    try { setReply(await api.ask(q)); } catch (e) { setError(e instanceof Error ? e.message : "Could not ask."); } finally { setBusy(false); }
  }

  return (
    <section className="card ask" data-testid="ask">
      <h2>Ask your statements</h2>
      <p className="d">
        {approved > 0
          ? `Answers come from your ${approved} approved statement${approved === 1 ? "" : "s"} only, with the transactions behind every number.`
          : "Approve a statement first. Answers use approved statements only, so a number is never built on cells nobody has checked."}
      </p>
      <form onSubmit={(e) => { e.preventDefault(); void ask(text); }}>
        <input value={text} onChange={(e) => setText(e.target.value)} disabled={approved === 0 || busy} maxLength={300}
               placeholder="For example: how much did I spend on UPI in March?" aria-label="Your question" data-testid="ask-input" />
        <button className="btn primary" disabled={approved === 0 || busy || !text.trim()}>{busy ? "Asking…" : "Ask"}</button>
      </form>
      {approved > 0 && (
        <div className="eg">{EXAMPLES.map((x) => (
          <button key={x} type="button" className="btn small" disabled={busy} onClick={() => { setText(x); void ask(x); }}>{x}</button>
        ))}</div>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      {reply && !reply.answered && (
        <p className="refusal" role="status" data-testid="refusal">
          <b>No answer.</b> {reply.reason}
        </p>
      )}
      {reply && reply.answered && <Answer r={reply} />}
    </section>
  );
}
