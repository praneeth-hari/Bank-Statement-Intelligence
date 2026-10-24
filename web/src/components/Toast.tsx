import { useEffect } from "react";

interface Props { text: string; onUndo?: () => void; onClose: () => void; error?: boolean }

export function Toast({ text, onUndo, onClose, error }: Props) {
  useEffect(() => {
    const t = setTimeout(onClose, error ? 9000 : 7000);
    return () => clearTimeout(t);
  }, [text, error, onClose]);
  return (
    <div className={`toast ${error ? "error" : ""}`} role={error ? "alert" : "status"}>
      <span>{text}</span>
      {onUndo && <button onClick={onUndo}>Undo<kbd>U</kbd></button>}
      <button className="x" aria-label="Dismiss" onClick={onClose}>×</button>
    </div>
  );
}
