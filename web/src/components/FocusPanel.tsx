import { useEffect, useRef } from "react";
import { api } from "../api";
import { cropStyle } from "../lib/geometry";
import { explainRow } from "../lib/explain";
import { fieldLabel } from "../lib/labels";
import { displayValue } from "../lib/money";
import type { Action, ReviewItem, StatementDetail } from "../types";

interface Props {
  stmt: StatementDetail;
  item: ReviewItem;
  busy: boolean;
  editing: boolean;
  draft: string;
  onDraft: (v: string) => void;
  onEdit: (on: boolean) => void;
  onAct: (action: Action, value?: string) => void;
}

const CROP_WIDTH = 410;
const truncate = (t: string, n: number) => (t.length > n ? `${t.slice(0, n - 1)}…` : t);

export function FocusPanel({ stmt, item, busy, editing, draft, onDraft, onEdit, onAct }: Props) {
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { if (editing) input.current?.focus(); }, [editing]);

  const page = item.bbox ? stmt.pages[item.bbox.page] : undefined;
  const row = item.row === null ? null : stmt.transactions[item.row]?.fields;
  const title = item.row === null ? fieldLabel(item.field) : `${fieldLabel(item.field)}, row ${item.row + 1}`;
  const sub = row
    ? [displayValue("date", row.date?.value ?? null), truncate(row.description?.text ?? "", 42)].filter(Boolean).join(" · ")
    : "Account details at the top of the statement";

  const read = displayValue(item.field, item.value, item.text || "nothing read");
  const hasSuggestion = item.suggestion !== null;
  const fromModel = item.flags.includes("llm_suggested");
  const fromRule = item.flags.includes("rule_suggested");
  const clears = !hasSuggestion && item.flags.includes("suggest_clear");
  const suggestion = hasSuggestion ? displayValue(item.field, item.suggestion) : null;
  const lines = explainRow(stmt, item);
  const severe = item.group === "chain";

  const primary = hasSuggestion
    ? { label: suggestion !== null && suggestion.length > 16 ? "Use suggestion" : `Use ${suggestion}`, action: "accept_suggestion" as Action }
    : clears
      ? { label: "Clear this cell", action: "accept_suggestion" as Action }
      : { label: "Looks right", action: "confirm" as Action };

  return (
    <section className="card focus" data-testid="focus" aria-live="polite">
      <h2>{title}</h2>
      <p className="sub">{sub}</p>
      <p className={`reason ${severe ? "severe" : ""}`}>{item.reasons.slice(0, 2).join(" ")}</p>

      {page && item.bbox && (
        <figure className="crop">
          <div
            role="img"
            aria-label={`Scan of the ${fieldLabel(item.field)} cell, enlarged`}
            style={{ ...cropStyle(item.bbox, page, CROP_WIDTH), backgroundImage: `url(${api.imageUrl(page.image, 200)})` }}
          />
          <figcaption>What the scan shows, enlarged</figcaption>
        </figure>
      )}

      {editing ? (
        <form className="editbox" onSubmit={(e) => { e.preventDefault(); onAct("correct", draft); }}>
          <label htmlFor="edit-value">Correct value</label>
          <input id="edit-value" ref={input} value={draft} onChange={(e) => onDraft(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Escape") onEdit(false); }} autoComplete="off" spellCheck={false} />
          <div className="acts">
            <button className="go" type="submit" disabled={busy}>Save</button>
            <button className="sec" type="button" onClick={() => onEdit(false)}>Cancel</button>
          </div>
        </form>
      ) : (
        <>
          <div className={`cmp ${hasSuggestion ? "two" : ""}`}>
            <div className={`val read ${hasSuggestion ? "struck" : ""}`}>
              <small>Read from the scan</small>
              <b data-testid="read-value">{read}</b>
            </div>
            {hasSuggestion && (
              <div className={`val sug ${fromModel || fromRule ? "model" : ""}`}>
                <small>{fromModel ? "Suggested by a language model" : fromRule ? "Suggested by a rule" : "Suggested"}</small>
                <b data-testid="suggested-value">{suggestion}</b>
              </div>
            )}
          </div>
          {lines.length > 0 && (
            <div className="math">
              {lines.map((l) => (
                <div key={l.label}><span>{l.label}</span><span className={l.ok ? "ok" : ""}>{l.text}</span></div>
              ))}
            </div>
          )}
          <div className="acts">
            <button className="go" data-testid="primary-action" disabled={busy}
                    onClick={() => onAct(primary.action)}>
              {primary.label}<kbd>Enter</kbd>
            </button>
            <button className="sec" disabled={busy} onClick={() => onEdit(true)}>Edit<kbd>E</kbd></button>
            {(hasSuggestion || clears) && (
              <button className="sec" disabled={busy} onClick={() => onAct("confirm")}>Keep<kbd>K</kbd></button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
