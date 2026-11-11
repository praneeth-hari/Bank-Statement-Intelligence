import { useEffect, useState } from "react";
import { api } from "../api";
import { FieldGrid, OUTCOMES } from "../components/charts";
import { Empty, Tile } from "../components/Shell";
import { count, percent } from "../lib/format";
import type { Quality, QualityCondition } from "../types";

const FIELD_NAMES: Record<string, [string, string]> = {
  description: ["description", "descriptions"], account_number: ["account number", "account numbers"],
  opening_balance: ["opening balance", "opening balances"], closing_balance: ["closing balance", "closing balances"],
  account_holder: ["account holder name", "account holder names"], date: ["date", "dates"], balance: ["running balance", "running balances"],
  debit: ["debit", "debits"], credit: ["credit", "credits"], ref: ["reference", "references"], bank_name: ["bank name", "bank names"],
  branch: ["branch", "branches"], ifsc: ["IFSC code", "IFSC codes"], value_date: ["value date", "value dates"],
  period_start: ["period start", "period starts"], period_end: ["period end", "period ends"], currency: ["currency", "currencies"],
};

/** "21 were descriptions, 2 were account numbers and 1 was the opening balance" */
export function missedSentence(c: QualityCondition): string {
  const parts = Object.entries(c.missed_by_field).map(([f, n]) => {
    const [one, many] = FIELD_NAMES[f] ?? [f.replace(/_/g, " "), `${f.replace(/_/g, " ")} fields`];
    return { n, text: `${count(n)} ${n === 1 ? `was ${/^[aeiou]/i.test(one) ? "an" : "a"} ${one}` : `were ${many}`}` };
  });
  if (parts.length === 0) return "";
  const list = parts.length === 1 ? parts[0].text : parts.slice(0, -1).map((p) => p.text).join(", ") + " and " + parts[parts.length - 1].text;
  return `Of the ${count(c.missed)} that got through, ${list}.`;
}

function flaggedText(c: QualityCondition): string {
  if (c.flagged === 0 && c.wrong === 0) return "none flagged, no wrong fields to catch";
  const caught = c.wrong === 0 ? "no wrong fields" : `caught ${count(c.caught)} of ${count(c.wrong)} wrong fields`;
  return `${percent(c.flag_rate)} flagged, ${caught}`;
}

export function QualityPage() {
  const [q, setQ] = useState<Quality | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.quality().then(setQ).catch((e: Error) => setError(e.message)); }, []);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!q) return <p className="loading">Reading the evaluation reports…</p>;
  if (!q.available) {
    return (
      <>
        <h1 className="bt-h1">How far can you trust it?</h1>
        <Empty title="No evaluation reports found">
          This page reads the saved reports in the reports folder, written by <code>python -m stmtai.evaluate</code>. Run it, or point
          <code> STMTAI_REPORTS_DIR </code> at a folder that has them.
        </Empty>
      </>
    );
  }

  const h = q.headline;
  const rules = q.questions.find((x) => x.id === "rules");
  const heavy = q.conditions.find((c) => c.id === "heavy");
  const r = q.reviewer;
  return (
    <>
      <h1 className="bt-h1">How far can you trust it?</h1>
      <div className="bt-grid">
        {h && <>
          <Tile className="bt-violet c4" data-testid="caught"><div className="bt-label">Wrong fields flagged</div><div className="bt-big">{count(h.caught)} of {count(h.wrong)}</div><p>On {h.label.toLowerCase()}s</p></Tile>
          <Tile className="bt-coral c4" data-testid="missed"><div className="bt-label">Wrong and trusted</div><div className="bt-big">{count(h.missed)}</div><p>Got through without a flag</p></Tile>
          <Tile className="bt-lime c4"><div className="bt-label">Sent to a person</div><div className="bt-big">{percent(h.flag_rate)}</div><p>{count(h.flagged)} of {count(h.fields)} fields</p></Tile>

          <Tile className="c12">
            <h3>How a statement becomes an answer</h3>
            <p className="bt-sub">
              {h.docs} synthetic statements, {count(h.rows ?? 0)} rows and {count(h.fields)} fields, each checked against the true value. Made-up documents only, never real ones.
            </p>
            <div className="bt-steps">
              <div className="bt-step violet"><b>Read</b><span>Every field gets a confidence score.</span><strong>{count(h.fields)} fields on {h.label.toLowerCase()}s</strong></div>
              <div className="bt-step sky"><b>Flag</b><span>Low confidence goes to review.</span><strong>{count(h.flagged)} flagged, {percent(h.flag_rate)}</strong></div>
              <div className="bt-step lime"><b>Review</b><span>You approve or correct each flag.</span><strong>{count(h.caught)} of {count(h.wrong)} wrong fields caught</strong></div>
              <div className="bt-step butter"><b>Ask</b><span>Answers use approved rows only.</span>
                <strong>{rules ? `${rules.correct} of ${rules.of} test questions right` : "Answers list the rows behind them"}</strong></div>
            </div>
          </Tile>

          <Tile className="c12">
            <h3>Every field, and what the system did with it</h3>
            <p className="bt-sub">One square per field on {h.label.toLowerCase()}s, grouped by outcome rather than by position on the page.</p>
            <FieldGrid c={h} />
            <ul className="bt-legend">{OUTCOMES.map((o) => (
              <li key={o.key}><i style={{ background: o.colour }} />{o.label}, {count(h.outcomes[o.key])}</li>
            ))}</ul>
            {h.missed > 0 && <p className="bt-sub">{missedSentence(h)}</p>}
          </Tile>
        </>}

        <Tile className="c12">
          <h3>It knows when it can’t be trusted</h3>
          <p className="bt-sub">
            {heavy?.error_recall != null
              ? `Heavy scans are mostly wrong, yet ${percent(heavy.error_recall)} of the wrong fields are flagged, so a person is told to look instead of being handed bad numbers.`
              : "How many fields are right, and how many of the wrong ones are flagged, by how good the scan is."}
          </p>
          <div className="bt-conds">
            {q.conditions.map((c) => {
              const bad = (c.accuracy ?? 0) < 0.5;
              return (
                <div key={c.id} className="bt-cond">
                  <div><b>{c.label}</b><b className={bad ? "bad" : "good"}>{percent(c.accuracy)}</b></div>
                  <div className="bt-pill"><div style={{ width: `${(c.accuracy ?? 0) * 100}%`, background: bad ? "#FF7A59" : "#5B2EFF" }} /></div>
                  <small>{flaggedText(c)}</small>
                </div>
              );
            })}
          </div>
          <p className="bt-sub">Accuracy is the share of all fields read right, out of {q.conditions.map((c) => count(c.fields)).join(", ")} fields. The flag threshold is {q.threshold.toFixed(2)}.</p>
        </Tile>

        {q.names.length > 0 && (
          <Tile className="bt-sky c6">
            <h3>Repairing damaged names</h3><p className="bt-sub">{q.names[0].of} names with letters dropped on purpose. How many each approach restored.</p>
            <div className="bt-groups">{q.names.map((n) => (
              <div key={n.id} className="bt-grow wide">
                <span>{n.label}</span>
                <div className="bt-pill"><div style={{ width: `${(n.restored / n.of) * 100}%`, background: n.uses_model ? "#B7B0E8" : "#5B2EFF" }} /></div>
                <b>{n.restored}/{n.of}</b>
              </div>
            ))}</div>
            <p className="bt-sub">Purple bars need no model. Lilac bars use a language model.</p>
          </Tile>
        )}
        {q.questions.length > 0 && (
          <Tile className="c6">
            <h3>Answering questions</h3>
            <p className="bt-sub">{q.questions[0].of} answerable questions, checked against separately computed answers.{q.questions.some((x) => x.in_sample) && " The rules were tuned on these, so that score is not a fresh test."}</p>
            <div className="bt-qa">{q.questions.map((x) => (
              <div key={x.id}>
                <div className="bt-qhead"><b>{x.label}</b><span>{x.correct} right, <em className={x.wrong ? "bad" : ""}>{x.wrong} wrong</em>, {x.refused} refused</span></div>
                <div className="bt-stackbar" role="img" aria-label={`${x.correct} right, ${x.wrong} wrong, ${x.refused} refused`}>
                  <i style={{ flex: x.correct, background: "#5B2EFF" }} />
                  {x.wrong > 0 && <i style={{ flex: x.wrong, background: "#FF7A59" }} />}
                  {x.refused > 0 && <i style={{ flex: x.refused, background: "#C9C3EE" }} />}
                </div>
              </div>
            ))}</div>
          </Tile>
        )}

        <Tile className="bt-butter c12" data-testid="reviewer">
          <h3>What reviewers did here</h3>
          {r.reviewed > 0
            ? <p>You have checked {count(r.flagged_reviewed)} flagged {r.flagged_reviewed === 1 ? "cell" : "cells"} on this installation. {count(r.flagged_actually_wrong)} {r.flagged_actually_wrong === 1 ? "was" : "were"} actually wrong, and you corrected {count(r.unflagged_corrected)} {r.unflagged_corrected === 1 ? "cell" : "cells"} that were not flagged. Reviewers mostly look at flagged cells only, so that last number is a lower bound.</p>
            : <p>Nothing reviewed yet. As you review and approve statements, this shows how often the flags matched what you actually corrected.</p>}
        </Tile>
      </div>
      <p className="bt-foot">{q.note}{q.extras_source ? ` ${q.extras_source}` : ""}</p>
    </>
  );
}
