import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { AskPanel } from "../components/AskPanel";
import type { StatementSummary } from "../types";

function when(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function StatementList() {
  const [items, setItems] = useState<StatementSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

  const load = useCallback(() => api.list().then(setItems).catch((e: Error) => setError(e.message)), []);
  useEffect(() => { void load(); }, [load]);

  // Poll only while something is still being extracted.
  const working = items?.some((s) => s.status === "processing");
  useEffect(() => {
    if (!working) return;
    const t = setInterval(() => void load(), 1500);
    return () => clearInterval(t);
  }, [working, load]);

  async function upload(files: FileList | File[]) {
    setError(null);
    setUploading(true);
    try {
      for (const f of Array.from(files)) await api.upload(f);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed.");
    } finally { setUploading(false); }
  }

  async function remove(s: StatementSummary) {
    if (!window.confirm(`Delete ${s.filename}? Its corrections are deleted too.`)) return;
    try { await api.remove(s.id); await load(); } catch (e) { setError(e instanceof Error ? e.message : "Delete failed."); }
  }

  return (
    <>
      <header className="top"><nav className="crumb"><b>Statements</b></nav></header>
      <main className="listpage">
        <div
          className={`drop ${over ? "over" : ""}`} data-testid="dropzone"
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); void upload(e.dataTransfer.files); }}
        >
          <p><b>{uploading ? "Uploading…" : "Drop a bank statement PDF here"}</b></p>
          <p className="d">Digital PDFs and scans both work. Scans take a minute while the text is read.</p>
          <button className="btn primary" onClick={() => picker.current?.click()} disabled={uploading}>Choose a file</button>
          <input ref={picker} type="file" accept="application/pdf" multiple hidden data-testid="file-input"
                 onChange={(e) => { if (e.target.files) void upload(e.target.files); e.target.value = ""; }} />
        </div>
        {error && <p className="error" role="alert">{error}</p>}

        {items && items.length > 0 && <AskPanel approved={items.filter((s) => s.approved && s.status === "ready").length} />}

        {items && items.length === 0 && <p className="empty">No statements yet. Upload one to see what was extracted and what needs a look.</p>}
        {items && items.length > 0 && (
          <ul className="list">
            {items.map((s) => (
              <li key={s.id} className="card row">
                <div className="name">
                  {s.status === "ready" ? <a href={`#/s/${s.id}`}>{s.filename}</a> : <span>{s.filename}</span>}
                  <small>{when(s.created)}</small>
                </div>
                <div className="state">
                  {s.status === "processing" && <span className="chip wait"><i />Reading the statement</span>}
                  {s.status === "failed" && <span className="chip bad" title={s.error ?? ""}><i />Could not read it</span>}
                  {s.status === "ready" && s.approved && <span className="chip good"><i />Approved</span>}
                  {s.status === "ready" && !s.approved && (s.to_review ?? 0) === 0 && <span className="chip good"><i />Nothing to review</span>}
                  {s.status === "ready" && !s.approved && (s.to_review ?? 0) > 0 && (
                    <span className="chip warn"><i />{s.to_review} to review</span>
                  )}
                  {s.status === "ready" && s.reconciles === false && <span className="chip bad"><i />Balance off</span>}
                </div>
                <div className="meta">{s.rows != null ? `${s.rows} rows` : ""}</div>
                {s.status === "failed" && <p className="why">{s.error}</p>}
                <button className="btn small ghost" onClick={() => void remove(s)}>Delete</button>
              </li>
            ))}
          </ul>
        )}
      </main>
    </>
  );
}
