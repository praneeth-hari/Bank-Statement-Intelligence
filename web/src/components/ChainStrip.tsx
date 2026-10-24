import type { RowStatus } from "../lib/chain";

interface Props { statuses: RowStatus[]; currentRow: number | null; onPick: (row: number) => void }

const LABEL: Record<RowStatus, string> = {
  ok: "no problem found", flag: "needs a look", brk: "breaks the balance", done: "checked",
};

export function ChainStrip({ statuses, currentRow, onPick }: Props) {
  return (
    <nav className="strip" aria-label="Balance chain, one mark per row">
      <h4>Balance<br />chain</h4>
      <div className="ticks">
        {statuses.map((s, row) => (
          <button
            key={row}
            className={`t ${s}${row === currentRow ? " cur" : ""}`}
            aria-label={`Row ${row + 1}: ${LABEL[s]}`}
            title={`Row ${row + 1}: ${LABEL[s]}`}
            onClick={() => onPick(row)}
          />
        ))}
      </div>
      <small>{statuses.length} rows</small>
    </nav>
  );
}
