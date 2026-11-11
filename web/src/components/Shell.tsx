import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import type { Route } from "../lib/route";
import type { Health, StatementSummary } from "../types";

/** Fired when the set of statements changes, so the sidebar count and note stay current. */
export const CHANGED = "stmtai:statements-changed";
export const announceChange = () => window.dispatchEvent(new Event(CHANGED));

const ITEMS: { name: Route["name"]; label: string; href: string }[] = [
  { name: "dashboard", label: "Dashboard", href: "#/" },
  { name: "transactions", label: "Transactions", href: "#/transactions" },
  { name: "recurring", label: "Recurring", href: "#/recurring" },
  { name: "statements", label: "Statements", href: "#/statements" },
  { name: "ask", label: "Ask", href: "#/ask" },
  { name: "quality", label: "Quality", href: "#/quality" },
];

/** The dark rounded sidebar and the page area. The note at the bottom says what the numbers are built from. */
export function Shell({ route, children }: { route: Route; children: ReactNode }) {
  const [list, setList] = useState<StatementSummary[] | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  useEffect(() => {
    const load = () => api.list().then(setList).catch(() => setList(null));
    void load();
    window.addEventListener(CHANGED, load);                  // statements were loaded, uploaded or deleted somewhere on the page
    return () => window.removeEventListener(CHANGED, load);
  }, [route.name]);
  useEffect(() => { api.health().then(setHealth).catch(() => setHealth(null)); }, []);

  const approved = list?.filter((s) => s.approved && s.status === "ready").length ?? 0;
  return (
    <div className="bt-shell">
      <aside className="bt-side">
        <a className="bt-wm" href="#/" aria-label="Statement Intelligence, home">Statement<br />Intelligence<i>.</i></a>
        <nav aria-label="Main">
          {ITEMS.map((i) => (
            <a key={i.name} href={i.href} className={route.name === i.name ? "on" : ""} aria-current={route.name === i.name ? "page" : undefined}>
              {i.label}
              {i.name === "statements" && list && list.length > 0 && <b>{list.length}</b>}
            </a>
          ))}
        </nav>
        <div className="bt-sidenote" data-testid="sidenote">
          <b>{list === null ? "Reading your statements" : approved === 0 ? "No approved statements" : `${approved} ${approved === 1 ? "statement" : "statements"} approved`}</b>
          Everything here is counted from approved statements only.
        </div>
        <p className="bt-priv" data-testid="privacy">
          <b>Private by design</b>
          Files stay on this computer. {health === null ? "" : health.llm ? `A local language model (${health.llm}) is on and also runs here.` : "No language model is used."}
        </p>
      </aside>
      <main className="bt-main">{children}</main>
    </div>
  );
}

export function Tile({ className = "", children, ...rest }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLElement>) {
  return <section className={`bt-tile ${className}`} {...rest}>{children}</section>;
}

export function Empty({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Tile className="bt-empty">
      <h3>{title}</h3>
      <p>{children}</p>
    </Tile>
  );
}
