export type Route =
  | { name: "dashboard" }
  | { name: "transactions" }
  | { name: "recurring" }
  | { name: "statements" }
  | { name: "ask" }
  | { name: "quality" }
  | { name: "review"; id: string };

/** The address bar is the only router: #/, #/transactions, #/recurring, #/statements, #/ask, #/quality and #/s/<id> for the review screen. */
export function parseRoute(hash: string): Route {
  const review = /^#\/s\/([\w-]+)/.exec(hash);
  if (review) return { name: "review", id: review[1] };
  if (/^#\/transactions\/?$/.test(hash)) return { name: "transactions" };
  if (/^#\/recurring\/?$/.test(hash)) return { name: "recurring" };
  if (/^#\/statements\/?$/.test(hash)) return { name: "statements" };
  if (/^#\/ask\/?$/.test(hash)) return { name: "ask" };
  if (/^#\/quality\/?$/.test(hash)) return { name: "quality" };
  return { name: "dashboard" };
}
