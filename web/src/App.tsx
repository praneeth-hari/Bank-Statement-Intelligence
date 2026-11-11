import { useEffect, useState } from "react";
import { Shell } from "./components/Shell";
import { AskPage } from "./pages/AskPage";
import { Dashboard } from "./pages/Dashboard";
import { QualityPage } from "./pages/QualityPage";
import { ReviewPage } from "./pages/ReviewPage";
import { StatementList } from "./pages/StatementList";
import { parseRoute, type Route } from "./lib/route";

export default function App() {
  const [route, setRoute] = useState<Route>(parseRoute(window.location.hash));
  useEffect(() => {
    const on = () => { setRoute(parseRoute(window.location.hash)); window.scrollTo(0, 0); };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  // The review screen needs the whole width for the page image, so it keeps its own layout.
  if (route.name === "review") return <ReviewPage key={route.id} id={route.id} />;
  return (
    <Shell route={route}>
      {route.name === "dashboard" && <Dashboard />}
      {route.name === "statements" && <StatementList />}
      {route.name === "ask" && <AskPage />}
      {route.name === "quality" && <QualityPage />}
    </Shell>
  );
}
