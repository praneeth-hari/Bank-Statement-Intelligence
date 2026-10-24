import { useEffect, useRef } from "react";
import { api } from "../api";
import { boxStyle } from "../lib/geometry";
import type { ReviewItem, StatementDetail } from "../types";

interface Props {
  stmt: StatementDetail;
  items: ReviewItem[];
  selectedKey: string | null;
  pageIndex: number;
  onPage: (index: number) => void;
  onSelect: (key: string) => void;
}

const prefersReducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export function PageView({ stmt, items, selectedKey, pageIndex, onPage, onSelect }: Props) {
  const page = stmt.pages[pageIndex];
  const scroller = useRef<HTMLDivElement>(null);

  // Keep the selected box in view, centred, whenever the selection or page changes.
  useEffect(() => {
    const el = scroller.current?.querySelector<HTMLElement>(`[data-key="${CSS.escape(selectedKey ?? "")}"]`);
    el?.scrollIntoView({ block: "center", behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }, [selectedKey, pageIndex]);

  if (!page) return null;
  const onPageItems = items.filter((i) => i.bbox?.page === page.page);

  // Cells a person has already confirmed or corrected stay visible, quietly, so progress is visible on the page.
  const done: { key: string; bbox: NonNullable<ReviewItem["bbox"]> }[] = [];
  const collect = (prefix: string, fields: Record<string, { bbox: ReviewItem["bbox"]; flags: string[] } | null>) => {
    for (const [name, f] of Object.entries(fields)) {
      if (f?.bbox?.page === page.page && f.flags.some((x) => x === "human_corrected" || x === "human_verified"))
        done.push({ key: `${prefix}:${name}`, bbox: f.bbox });
    }
  };
  collect("h", stmt.header);
  stmt.transactions.forEach((t) => collect(`r${t.row}`, t.fields));

  return (
    <section className="card pagecard" aria-label="Statement page">
      <header className="pagehead">
        <h3>Page {pageIndex + 1} of {stmt.pages.length}</h3>
        {stmt.pages.length > 1 && (
          <span className="pager">
            <button className="btn small" disabled={pageIndex === 0} onClick={() => onPage(pageIndex - 1)}>Previous page</button>
            <button className="btn small" disabled={pageIndex === stmt.pages.length - 1} onClick={() => onPage(pageIndex + 1)}>Next page</button>
          </span>
        )}
      </header>
      <div className="pagescroll" ref={scroller}>
        <div className="pageframe">
          <img src={api.imageUrl(page.image, 130)} alt={`Statement page ${pageIndex + 1}`} draggable={false} />
          {done.map((d) => (
            <span key={`done-${d.key}`} className="box done" style={boxStyle(d.bbox, page)} />
          ))}
          {onPageItems.map((it) => (
            <button
              key={it.key}
              data-key={it.key}
              aria-label={`${it.field} needs review`}
              className={`box ${it.group === "chain" ? "brk" : "flag"}${it.key === selectedKey ? " sel" : ""}`}
              style={boxStyle(it.bbox!, page)}
              onClick={() => onSelect(it.key)}
            />
          ))}
        </div>
      </div>
      <footer className="legend">
        <span><i className="sw brk" />Breaks the balance</span>
        <span><i className="sw flag" />Needs a look</span>
        <span><i className="sw done" />Checked</span>
        <span><i className="sw sel" />Selected</span>
      </footer>
    </section>
  );
}
