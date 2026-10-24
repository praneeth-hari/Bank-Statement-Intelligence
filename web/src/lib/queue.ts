import type { GroupInfo, ReviewItem } from "../types";

/** Reviewer's working order: group priority first (balance problems can clear other flags), then document order. */
export function sortItems(items: ReviewItem[], groups: GroupInfo[]): ReviewItem[] {
  const rank = new Map(groups.map((g, i) => [g.id, i]));
  return [...items].sort((a, b) =>
    (rank.get(a.group) ?? 99) - (rank.get(b.group) ?? 99) ||
    (a.bbox?.page ?? 0) - (b.bbox?.page ?? 0) ||
    (a.row ?? -1) - (b.row ?? -1) ||
    a.field.localeCompare(b.field));
}

/** After an action, move to the next item that is still waiting; wrap to the first; null when nothing is left. */
export function pickNext(before: ReviewItem[], currentKey: string | null, after: ReviewItem[]): string | null {
  if (after.length === 0) return null;
  const present = new Set(after.map((i) => i.key));
  const at = before.findIndex((i) => i.key === currentKey);
  for (const candidate of before.slice(at + 1)) if (present.has(candidate.key)) return candidate.key;
  return after[0].key;
}

export function step(items: ReviewItem[], currentKey: string | null, delta: 1 | -1): string | null {
  if (items.length === 0) return null;
  const at = items.findIndex((i) => i.key === currentKey);
  if (at === -1) return items[0].key;
  return items[(at + delta + items.length) % items.length].key;
}
