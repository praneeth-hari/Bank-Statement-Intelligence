import type { GroupInfo, ReviewItem } from "../types";

interface Props {
  groups: GroupInfo[];
  total: number;
  selected: ReviewItem | null;
  disabled: boolean;
  onJump: (group: GroupInfo) => void;
  onConfirmAll: (group: GroupInfo) => void;
}

export function QueuePanel({ groups, total, selected, disabled, onJump, onConfirmAll }: Props) {
  return (
    <section className="card queue" aria-label="Review queue">
      <h3 data-testid="queue-title">Left to review, {total}</h3>
      {groups.filter((g) => g.count > 0).map((g) => (
        <div key={g.id} className={`grp ${selected?.group === g.id ? "on" : ""}`}>
          <button className="grp-main" onClick={() => onJump(g)}>
            <span className={`dot ${g.id === "chain" ? "brk" : "flag"}`} />
            <span>
              {g.label}
              <span className="d">{g.hint}</span>
            </span>
          </button>
          {g.bulk ? (
            <button className="ca" disabled={disabled} onClick={() => onConfirmAll(g)}
                    title="Confirm every item in this group. Each one is still logged separately.">
              Confirm all {g.count}
            </button>
          ) : (
            <span className="n">{g.count}</span>
          )}
        </div>
      ))}
    </section>
  );
}
