"""Can a model restore dropped letters at all? A controlled test, independent of any OCR engine.

    python -m stmtai.llm.probe --model qwen2.5:3b
    python -m stmtai.llm.probe --model llama3.1:8b

The real scans leave very few wrong descriptions to practise on, so this builds them: take true payment
descriptions from the synthetic ground truth, damage the name the way OCR does (a letter dropped, or one letter
swapped for a look-alike), and ask the model to repair them with exactly the prompt and checks the fallback uses.
Undamaged descriptions are mixed in as controls, and a good model must leave them alone.

Limit, stated up front: synthetic damage is not real OCR damage, so read the numbers as a way to *compare
models*, not as the accuracy you will see on scans.
"""

from __future__ import annotations

import argparse
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from ..schema import Label
from .client import OllamaClient
from .fallback import DESCRIPTION_SCHEMA, DESCRIPTION_SYSTEM, _ask
from .validate import check_description, squash

_LOOKALIKE_SWAP = {"E": "F", "M": "N", "H": "N", "R": "P", "U": "V", "B": "R", "D": "O", "C": "G", "L": "I", "W": "V", "K": "X"}
_RAIL_NAME = re.compile(r"^((?:UPI|IMPS)/\d{10,13}/)([A-Z][A-Z .]{3,})$")


def damage(description: str, rng: random.Random) -> Optional[tuple[str, str]]:
    """(damaged text, kind) or None when the description has no name to damage."""
    m = _RAIL_NAME.match(description)
    if not m:
        return None
    head, name = m.groups()
    idx = [i for i, ch in enumerate(name) if ch.isalpha()]
    i = rng.choice(idx)
    if rng.random() < 0.6:
        return head + name[:i] + name[i + 1:], "dropped"
    swap = _LOOKALIKE_SWAP.get(name[i])
    return (head + name[:i] + swap + name[i + 1:], "swapped") if swap else (head + name[:i] + name[i + 1:], "dropped")


def build_cases(data: Path, n_damaged: int, n_clean: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    names: list[str] = []
    for lp in sorted(data.glob("*.json")):
        label = Label.model_validate_json(lp.read_text(encoding="utf-8"))
        names += [t.description for t in label.statement.transactions if _RAIL_NAME.match(t.description)]
    names = sorted(set(names))
    rng.shuffle(names)
    cases: list[dict[str, Any]] = []
    for desc in names:
        if sum(c["kind"] != "clean" for c in cases) >= n_damaged:
            break
        d = damage(desc, rng)
        if d and squash(d[0]) != squash(desc):
            cases.append({"truth": desc, "read": d[0], "kind": d[1]})
    for desc in names[::-1]:
        if sum(c["kind"] == "clean" for c in cases) >= n_clean:
            break
        if all(c["truth"] != desc for c in cases):
            cases.append({"truth": desc, "read": desc, "kind": "clean"})
    rng.shuffle(cases)
    return cases


def run(client: OllamaClient, cases: list[dict[str, Any]], batch: int = 6) -> list[dict[str, Any]]:
    out = []
    for i in range(0, len(cases), batch):
        chunk = cases[i:i + batch]
        answers = _ask(client, DESCRIPTION_SYSTEM, [{"id": j, "text": c["read"]} for j, c in enumerate(chunk)], DESCRIPTION_SCHEMA)
        for j, c in enumerate(chunk):
            ans = answers.get(j)
            reason = check_description(c["read"], ans) if ans is not None else "unanswered"
            out.append({**c, "answer": ans, "rejected": reason, "accepted": reason is None})
        print(f"  {min(i + batch, len(cases))}/{len(cases)}", flush=True)
    return out


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    damaged = [r for r in results if r["kind"] != "clean"]
    clean = [r for r in results if r["kind"] == "clean"]
    fixed = [r for r in damaged if r["accepted"] and squash(r["answer"]) == squash(r["truth"])]
    wrong = [r for r in damaged if r["accepted"] and squash(r["answer"]) != squash(r["truth"])]
    by_kind = {k: {"n": sum(r["kind"] == k for r in damaged),
                   "fixed": sum(r in fixed and r["kind"] == k for r in damaged)} for k in ("dropped", "swapped")}
    return {"damaged": len(damaged), "fixed": len(fixed), "wrong_suggestion": len(wrong),
            "no_suggestion": len(damaged) - len(fixed) - len(wrong),
            "blocked": dict(Counter(r["rejected"] for r in damaged if r["rejected"])), "by_kind": by_kind,
            "clean": len(clean), "clean_changed": sum(r["accepted"] for r in clean)}


def render(s: dict[str, Any], model: str, seconds: float, calls: int) -> str:
    pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "n/a"  # noqa: E731
    lines = [f"# Dropped-letter probe, model `{model}`", "",
             f"**{s['fixed']} of {s['damaged']} damaged descriptions restored exactly ({pct(s['fixed'], s['damaged'])}); "
             f"{s['clean_changed']} of {s['clean']} undamaged ones wrongly changed.**", "",
             "| outcome | count |", "|---|---|",
             f"| restored exactly | {s['fixed']} |", f"| a suggestion, but the wrong one | {s['wrong_suggestion']} |",
             f"| no suggestion (unchanged or blocked) | {s['no_suggestion']} |", ""]
    for k, v in s["by_kind"].items():
        lines.append(f"- {k} letter: {v['fixed']} of {v['n']} restored ({pct(v['fixed'], v['n'])})")
    lines += ["", f"Blocked by the checks: {s['blocked'] or 'none'}", "",
              f"{calls} model calls, {seconds:.0f}s total. Synthetic damage: use this to compare models, not as scan accuracy."]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="Controlled dropped-letter test for a model.")
    p.add_argument("--data", type=Path, default=Path("data/synthetic"))
    p.add_argument("--model", default=None)
    p.add_argument("--host", default=None)
    p.add_argument("--damaged", type=int, default=60)
    p.add_argument("--clean", type=int, default=30)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--cache", type=Path, default=Path("data/llm_cache"))
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    kwargs: dict[str, Any] = {"cache_dir": args.cache}
    if args.model:
        kwargs["model"] = args.model
    if args.host:
        kwargs["host"] = args.host
    client = OllamaClient(**kwargs)
    client.check()
    cases = build_cases(args.data, args.damaged, args.clean, args.seed)
    if not cases:
        raise SystemExit(f"no payment descriptions found in {args.data}")
    results = run(client, cases)
    report = render(summarize(results), client.model, client.seconds, client.calls)
    print("\n" + report)
    if args.out:
        import json
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "probe.md").write_text(report, encoding="utf-8")
        (args.out / "probe.jsonl").write_text("\n".join(json.dumps(r) for r in results), encoding="utf-8")


if __name__ == "__main__":
    main()
