import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { count } from "../lib/format";
import type { Categories } from "../types";
import { Tile } from "./Shell";

/** Rules of the form "if the description contains this text, call it that". Oldest matching rule wins. */
export function CategoriesPanel({ onChanged }: { onChanged: () => void }) {
  const [data, setData] = useState<Categories | null>(null);
  const [pattern, setPattern] = useState("");
  const [category, setCategory] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => api.categories().then(setData).catch((e: Error) => setError(e.message)), []);
  useEffect(() => { void load(); }, [load]);

  async function run(job: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await job(); await load(); onChanged(); }
    catch (e) { setError(e instanceof Error ? e.message : "That did not work."); }
    finally { setBusy(false); }
  }

  if (!data) return <Tile className="bt-cats"><p className="bt-sub">Loading your categories…</p></Tile>;
  const names = [...new Set(data.rules.map((r) => r.category))];
  return (
    <Tile className="bt-cats" data-testid="categories">
      <h3>Your categories</h3>
      <p className="bt-sub">
        A rule says: if a description contains this text, use this category. Capital letters don’t matter, and the oldest matching rule wins.
        Anything no rule matches stays Uncategorised, never guessed. {count(data.coverage.categorised)} of {count(data.coverage.total)} transactions have a category now.
      </p>

      {data.rules.length > 0 && (
        <ul className="bt-rules">
          {data.rules.map((r) => (
            <li key={r.id}>
              <span><b>{r.pattern}</b> <i aria-label="becomes">→</i> {r.category}</span>
              <small>{count(r.matches)} {r.matches === 1 ? "match" : "matches"}</small>
              <button type="button" className="bt-linkbtn" disabled={busy} onClick={() => void run(() => api.removeCategory(r.id))} aria-label={`Remove the rule for ${r.pattern}`}>Remove</button>
            </li>
          ))}
        </ul>
      )}

      <form className="bt-addrule" onSubmit={(e) => { e.preventDefault(); void run(async () => { await api.addCategory(pattern, category); setPattern(""); setCategory(""); }); }}>
        <label>Text to look for<input value={pattern} onChange={(e) => setPattern(e.target.value)} maxLength={40} placeholder="APOLLO" data-testid="rule-pattern" /></label>
        <label>Category<input value={category} onChange={(e) => setCategory(e.target.value)} maxLength={24} placeholder="Health" list="category-names" data-testid="rule-category" /></label>
        <datalist id="category-names">{names.map((n) => <option key={n} value={n} />)}</datalist>
        <button type="submit" className="bt-dark" disabled={busy || !pattern.trim() || !category.trim()} data-testid="rule-add">Add rule</button>
      </form>
      {error && <p className="bt-error" role="alert">{error}</p>}

      {data.suggestions.length > 0 && (
        <div className="bt-sugg" data-testid="suggestions">
          <div className="bt-rhead">
            <b>Suggested from your statements</b>
            <button type="button" className="bt-linkbtn" disabled={busy}
                    onClick={() => void run(async () => { for (const s of data.suggestions) await api.addCategory(s.pattern, s.category); })}>
              Add all {data.suggestions.length}
            </button>
          </div>
          <div className="bt-chips light">
            {data.suggestions.map((s) => (
              <button key={s.pattern} type="button" disabled={busy} onClick={() => void run(() => api.addCategory(s.pattern, s.category))}
                      title={`${s.matches} ${s.matches === 1 ? "transaction matches" : "transactions match"}`}>
                {s.pattern} → {s.category} · {s.matches}
              </button>
            ))}
          </div>
        </div>
      )}
    </Tile>
  );
}
