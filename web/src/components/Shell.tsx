import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import type { Route } from "../lib/route";
import type { StatementSummary } from "../types";

const ITEMS: { name: Route["name"]; label: string; href: string }[] = [
  { name: "dashboard", label: "Dashboard", href: "#/" },
  { name: "statements", label: "Statements", href: "#/statements" },
  { name: "ask", label: "Ask", href: "#/ask" },
  { name: "quality", label: "Quality", href: "#/quality" },
];

/** The dark rounded sidebar and the page area. The note at the bottom says what the numbers are built from. */
export function Shell({ route, children }: { route: Route; children: ReactNode }) {
  const [list, setList] = useState<StatementSummary[] | null>(null);
  useEffect(() => { api.list().then(setList).catch(() => setList(null)); }, [route.name]);

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
