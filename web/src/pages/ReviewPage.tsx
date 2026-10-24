import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { ChainStrip } from "../components/ChainStrip";
import { FocusPanel } from "../components/FocusPanel";
import { PageView } from "../components/PageView";
import { QueuePanel } from "../components/QueuePanel";
import { Toast } from "../components/Toast";
import { rowStatuses } from "../lib/chain";
import { fieldLabel } from "../lib/labels";
import { displayValue } from "../lib/money";
import { pickNext, sortItems, step } from "../lib/queue";
import type { Action, GroupInfo, ReviewResponse, StatementDetail } from "../types";

interface ToastState { text: string; undo?: () => void; error?: boolean }

export function ReviewPage({ id }: { id: string }) {
  const [stmt, setStmt] = useState<StatementDetail | null>(null);
  const [review, setReview] = useState<ReviewResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [pageIndex, setPageIndex] = useState(0);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const lastUndo = useRef<(() => void) | undefined>(undefined);

  const sorted = useMemo(() => (review ? sortItems(review.items, review.groups) : []), [review]);
  const item = sorted.find((i) => i.key === selected) ?? null;

  const refresh = useCallback(async () => {
    const [s, r] = await Promise.all([api.get(id), api.review(id)]);
    setStmt(s);
    setReview(r);
    return { s, r, sorted: sortItems(r.items, r.groups) };
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    refresh().then(({ sorted: first }) => { if (!cancelled) setSelected(first[0]?.key ?? null); })
      .catch((e: Error) => !cancelled && setLoadError(e.message));
    return () => { cancelled = true; };
  }, [refresh]);

  // Selecting an item on another page flips the page. Changing item closes the editor.
  useEffect(() => {
    if (item?.bbox && item.bbox.page !== pageIndex) setPageIndex(item.bbox.page);
    setEditing(false);
    setDraft(item ? displayValue(item.field, item.suggestion ?? item.value, item.text) : "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  const fail = (e: unknown) => setToast({ text: e instanceof Error ? e.message : "Something went wrong.", error: true });

  async function undoMany(ids: number[], restore: string | null) {
    try {
      await Promise.all(ids.map((cid) => api.undo(id, cid)));
      const { sorted: now } = await refresh();
      setSelected(restore && now.some((i) => i.key === restore) ? restore : now[0]?.key ?? null);
      setToast({ text: "Undone." });
      lastUndo.current = undefined;
    } catch (e) { fail(e); }
  }

  async function act(action: Action, value?: string) {
    if (!item || busy) return;
    setBusy(true);
    try {
      const res = await api.correct(id, item.row, item.field, action, value);
      const { sorted: now } = await refresh();
      setSelected(pickNext(sorted, item.key, now));
      const verb = action === "confirm" ? "Confirmed" : action === "correct" ? "Corrected" : "Accepted the suggestion for";
      const undo = () => undoMany([res.id], item.key);
      lastUndo.current = undo;
      setToast({ text: `${verb} ${fieldLabel(item.field).toLowerCase()}${item.row === null ? "" : `, row ${item.row + 1}`}.`, undo });
    } catch (e) { fail(e); } finally { setBusy(false); }
  }

  async function confirmGroup(group: GroupInfo) {
    if (busy) return;
    setBusy(true);
    try {
      const res = await api.confirmGroup(id, group.id);
      const { sorted: now } = await refresh();
      setSelected(now[0]?.key ?? null);
      const undo = () => undoMany(res.ids, null);
      lastUndo.current = undo;
      setToast({ text: `Confirmed ${res.confirmed} items.`, undo });
    } catch (e) { fail(e); } finally { setBusy(false); }
  }

  async function setApproved(on: boolean) {
    setBusy(true);
    try {
      await (on ? api.approve(id) : api.reopen(id));
      await refresh();
      setToast({ text: on ? "Approved. The data is ready to export." : "Reopened for changes." });
    } catch (e) { fail(e); } finally { setBusy(false); }
  }

  // Keyboard: the whole point of the screen is to review without reaching for the mouse.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, select") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "ArrowDown") { e.preventDefault(); setSelected((k) => step(sorted, k, 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setSelected((k) => step(sorted, k, -1)); }
      else if (e.key.toLowerCase() === "u") lastUndo.current?.();
      else if (item && !stmt?.approved) {
        if (e.key === "Enter" && t.tagName !== "BUTTON") {
          e.preventDefault();
          void act(item.suggestion !== null || item.flags.includes("suggest_clear") ? "accept_suggestion" : "confirm");
        } else if (e.key.toLowerCase() === "e") { e.preventDefault(); setEditing(true); }
        else if (e.key.toLowerCase() === "k" && (item.suggestion !== null || item.flags.includes("suggest_clear"))) void act("confirm");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (loadError) return <Message title="Could not open this statement" body={loadError} />;
  if (!stmt || !review) return <p className="loading">Loading statement…</p>;
  if (stmt.status !== "ready") return <Message title={`Statement is ${stmt.status}`} body={stmt.error ?? "Try again in a moment."} />;

  const total = review.count;
  const reviewed = stmt.corrections;
  const statuses = rowStatuses(stmt, review.items);
  const breaks = stmt.summary.chain_breaks ?? 0;
  const rows = stmt.transactions.length;
  const canExport = stmt.approved || total === 0;

  return (
    <>
      <header className="top">
        <nav className="crumb"><a href="#/">Statements</a><span>/</span><b>{stmt.filename}</b></nav>
        {review.reconciles
          ? <span className="chip good"><i />Balance adds up on all {rows} rows</span>
          : <span className="chip bad"><i />{breaks > 0 ? `Balance does not add up on ${breaks} ${breaks === 1 ? "row" : "rows"}` : "Closing balance does not match"}</span>}
        <div className="prog">
          <span data-testid="progress">{reviewed} of {reviewed + total} reviewed</span>
          <div className="bar" aria-hidden><b style={{ width: `${reviewed + total ? (reviewed / (reviewed + total)) * 100 : 100}%` }} /></div>
          {canExport
            ? <><a className="btn" href={api.exportUrl(id, "csv")} download>Export CSV</a></>
            : <button className="btn" disabled title={`${total} fields still need review`}>Export</button>}
          {stmt.approved
            ? <button className="btn" onClick={() => setApproved(false)} disabled={busy}>Reopen</button>
            : <button className="btn primary" data-testid="approve" disabled={total > 0 || busy}
                      title={total > 0 ? `${total} fields still need review` : "Mark this statement as checked"}
                      onClick={() => setApproved(true)}>Approve</button>}
        </div>
      </header>

      <main className="review">
        <ChainStrip statuses={statuses} currentRow={item?.row ?? null}
                    onPick={(row) => { const hit = sorted.find((i) => i.row === row); if (hit) setSelected(hit.key); }} />
        <PageView stmt={stmt} items={sorted} selectedKey={selected} pageIndex={pageIndex}
                  onPage={setPageIndex} onSelect={setSelected} />
        <div className="right">
          {stmt.approved ? (
            <section className="card focus done" data-testid="approved">
              <h2>Approved</h2>
              <p className="sub">{reviewed} fields were checked by a person. Changes are locked until you reopen it.</p>
              <div className="acts">
                <a className="go link" href={api.exportUrl(id, "csv")} download>Export CSV</a>
                <a className="sec link" href={api.exportUrl(id, "json")} download>Export JSON</a>
              </div>
            </section>
          ) : item ? (
            <FocusPanel stmt={stmt} item={item} busy={busy} editing={editing} draft={draft}
                        onDraft={setDraft} onEdit={setEditing} onAct={act} />
          ) : (
            <section className="card focus done" data-testid="all-clear">
              <h2>Everything is checked</h2>
              <p className="sub">
                {review.reconciles ? `The balance adds up on all ${rows} rows.` : "Nothing is left to review, but the balance still does not reconcile."}
                {" "}{reviewed > 0 ? `${reviewed} fields were reviewed.` : ""}
              </p>
              <div className="acts">
                <button className="go" disabled={busy} onClick={() => setApproved(true)}>Approve</button>
              </div>
            </section>
          )}
          {!stmt.approved && (
            <QueuePanel groups={review.groups} total={total} selected={item} disabled={busy}
                        onJump={(g) => { const hit = sorted.find((i) => i.group === g.id); if (hit) setSelected(hit.key); }}
                        onConfirmAll={confirmGroup} />
          )}
        </div>
      </main>
      {toast && <Toast text={toast.text} error={toast.error} onUndo={toast.undo} onClose={() => setToast(null)} />}
    </>
  );
}

function Message({ title, body }: { title: string; body: string }) {
  return (
    <main className="center">
      <section className="card message">
        <h2>{title}</h2>
        <p>{body}</p>
        <a className="btn" href="#/">Back to statements</a>
      </section>
    </main>
  );
}
