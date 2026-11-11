export type Route =
  | { name: "dashboard" }
  | { name: "statements" }
  | { name: "ask" }
  | { name: "quality" }
  | { name: "review"; id: string };

/** The address bar is the only router: #/, #/statements, #/ask, #/quality and #/s/<id> for the review screen. */
export function parseRoute(hash: string): Route {
  const review = /^#\/s\/([\w-]+)/.exec(hash);
  if (review) return { name: "review", id: review[1] };
  if (/^#\/statements\/?$/.test(hash)) return { name: "statements" };
  if (/^#\/ask\/?$/.test(hash)) return { name: "ask" };
  if (/^#\/quality\/?$/.test(hash)) return { name: "quality" };
  return { name: "dashboard" };
}
