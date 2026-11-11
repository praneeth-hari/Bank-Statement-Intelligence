import { useEffect, useRef } from "react";

interface Props {
  title: string;
  detail: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}

/** In-app replacement for window.confirm. Focus starts on Cancel so a stray Enter never deletes. */
export function ConfirmDialog({ title, detail, confirmLabel, onConfirm, onCancel }: Props) {
  const cancel = useRef<HTMLButtonElement>(null);
  const card = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    cancel.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); onCancel(); }
      if (e.key === "Tab" && card.current) {                       // keep focus inside the dialog
        const els = card.current.querySelectorAll<HTMLElement>("button");
        const first = els[0], last = els[els.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); before?.focus?.(); };
  }, [onCancel]);
  return (
    <div className="bt-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }} data-testid="confirm-scrim">
      <div className="bt-dialog" role="alertdialog" aria-modal="true" aria-labelledby="dlg-title" aria-describedby="dlg-detail" ref={card}>
        <h2 id="dlg-title">{title}</h2>
        <p id="dlg-detail">{detail}</p>
        <div className="bt-dialog-actions">
          <button type="button" className="bt-dlg-cancel" ref={cancel} onClick={onCancel}>Cancel</button>
          <button type="button" className="bt-dlg-danger" onClick={onConfirm} data-testid="confirm-yes">{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
