/** Recent questions, kept in this browser only. Every read and write is guarded, because storage can be
 * unavailable (private windows, blocked site data) and the page must work without it. */

export interface HistoryItem { q: string; result: string; answered: boolean; at: number }

const KEY = "stmtai.ask.history";
const MAX = 12;

export function loadHistory(storage: Pick<Storage, "getItem"> | null = safeStorage()): HistoryItem[] {
  try {
    const raw = storage?.getItem(KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((x): x is HistoryItem =>
      !!x && typeof x.q === "string" && typeof x.result === "string" && typeof x.answered === "boolean" && typeof x.at === "number").slice(0, MAX);
  } catch {
    return [];
  }
}

/** Newest first; asking the same question again moves it to the top instead of repeating it. */
export function remember(items: HistoryItem[], item: HistoryItem): HistoryItem[] {
  const same = (s: string) => s.trim().toLowerCase();
  return [item, ...items.filter((x) => same(x.q) !== same(item.q))].slice(0, MAX);
}

export function saveHistory(items: HistoryItem[], storage: Pick<Storage, "setItem"> | null = safeStorage()): void {
  try {
    storage?.setItem(KEY, JSON.stringify(items.slice(0, MAX)));
  } catch {
    /* the history is a convenience, never required */
  }
}

export function clearHistory(storage: Pick<Storage, "removeItem"> | null = safeStorage()): void {
  try {
    storage?.removeItem(KEY);
  } catch {
    /* nothing to do */
  }
}

function safeStorage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}
