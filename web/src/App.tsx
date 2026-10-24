import { useEffect, useState } from "react";
import { ReviewPage } from "./pages/ReviewPage";
import { StatementList } from "./pages/StatementList";

function route(): { id: string | null } {
  const m = /^#\/s\/([\w-]+)/.exec(window.location.hash);
  return { id: m ? m[1] : null };
}

export default function App() {
  const [current, setCurrent] = useState(route());
  useEffect(() => {
    const on = () => setCurrent(route());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return current.id ? <ReviewPage key={current.id} id={current.id} /> : <StatementList />;
}
