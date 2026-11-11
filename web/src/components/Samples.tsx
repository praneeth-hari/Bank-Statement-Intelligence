import { useEffect, useState } from "react";
import { api } from "../api";
import { announceChange, Tile } from "./Shell";

/** One button that loads the bundled made-up statements. Hidden when the server has none. */
export function SamplesCard({ onLoaded }: { onLoaded: () => void }) {
  const [count, setCount] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.health().then((h) => setCount(h.samples)).catch(() => setCount(0)); }, []);
  if (count === 0) return null;

  async function load() {
    setBusy(true); setError(null);
    try { await api.loadSamples(); announceChange(); onLoaded(); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not load the samples."); }
    finally { setBusy(false); }
  }
  return (
    <Tile className="bt-lime bt-samples" data-testid="samples">
      <h3>No statements to hand?</h3>
      <p>Load {count} made-up sample statements. They belong to no real person or account, and they are approved for you so every page has something to show.</p>
      <button type="button" className="bt-dark" onClick={() => void load()} disabled={busy}>{busy ? "Loading…" : "Load sample statements"}</button>
      {error && <p className="bt-error" role="alert">{error}</p>}
    </Tile>
  );
}
