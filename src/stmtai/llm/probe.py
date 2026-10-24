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
from .vocab import Vocabulary, hints_for, vocab_rule

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


def _others(everything: list[str], desc: str) -> list[str]:
    """The rest of the statement, as the extractor would see it: the cell's own description is not in it."""
    out = list(everything)
    out.remove(desc)
    return out


def build_cases(data: Path, n_damaged: int, n_clean: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    names: list[str] = []
    context: dict[str, list[str]] = {}  # description -> every description on the same statement (the rest of its page)
    by_doc: dict[str, list[str]] = {}
    owner: dict[str, str] = {}
    for lp in sorted(data.glob("*.json")):
        label = Label.model_validate_json(lp.read_text(encoding="utf-8"))
        everything = [t.description for t in label.statement.transactions]
        by_doc[label.doc_id] = everything
        for d in everything:
            if _RAIL_NAME.match(d) and d not in context:
                context[d] = everything
                owner[d] = label.doc_id
        names += [d for d in everything if _RAIL_NAME.match(d)]
    pooled = {doc: [d for other, ds in by_doc.items() if other != doc for d in ds] for doc in by_doc}
    names = sorted(set(names))
    rng.shuffle(names)
    cases: list[dict[str, Any]] = []
    for desc in names:
        if sum(c["kind"] != "clean" for c in cases) >= n_damaged:
            break
        d = damage(desc, rng)
        if d and squash(d[0]) != squash(desc):
            cases.append({"truth": desc, "read": d[0], "kind": d[1], "context": _others(context[desc], desc),
                          "pool": pooled[owner[desc]]})
    for desc in names[::-1]:
        if sum(c["kind"] == "clean" for c in cases) >= n_clean:
            break
        if all(c["truth"] != desc for c in cases):
            cases.append({"truth": desc, "read": desc, "kind": "clean", "context": _others(context[desc], desc),
                          "pool": pooled[owner[desc]]})
    rng.shuffle(cases)
    return cases


def run(client: OllamaClient, cases: list[dict[str, Any]], batch: int = 6, hints: bool = False) -> list[dict[str, Any]]:
    out = []
    for i in range(0, len(cases), batch):
        chunk = cases[i:i + batch]
        payload = []
        for j, c in enumerate(chunk):
            item: dict[str, Any] = {"id": j, "text": c["read"]}
            seen = hints_for(c["read"], Vocabulary(c["context"] + c["pool"])) if hints else []
            if seen:
                item["seen_names"] = seen
            payload.append(item)
        answers = _ask(client, DESCRIPTION_SYSTEM, payload, DESCRIPTION_SCHEMA)
        for j, c in enumerate(chunk):
            ans = answers.get(j)
            reason = check_description(c["read"], ans) if ans is not None else "unanswered"
            out.append({**c, "answer": ans, "rejected": reason, "accepted": reason is None})
        print(f"  {min(i + batch, len(cases))}/{len(cases)}", flush=True)
    return out


def _vocab_fix(c: dict[str, Any], pooled: bool) -> Optional[str]:
    out = vocab_rule(c["read"], Vocabulary(c["context"] + (c["pool"] if pooled else [])))
    return out if out and check_description(c["read"], out) is None else None


def versus_rule(results: list[dict[str, Any]]) -> dict[str, int]:
    """Model against the vocabulary rule on the same damaged cases: who got what."""
    both = only_model = only_rule = neither = 0
    for r in results:
        if r["kind"] == "clean":
            continue
        model_ok = r["accepted"] and squash(r["answer"]) == squash(r["truth"])
        fix = _vocab_fix(r, True)
        rule_ok = fix is not None and squash(fix) == squash(r["truth"])
        both += model_ok and rule_ok
        only_model += model_ok and not rule_ok
        only_rule += rule_ok and not model_ok
        neither += not model_ok and not rule_ok
    return {"both": both, "only_model": only_model, "only_rule": only_rule, "neither": neither}


def vocabulary_only(cases: list[dict[str, Any]], pooled: bool = False) -> dict[str, int]:
    """Repeated names as the only tool, no model: this statement's own, or also those of other (approved) statements."""
    damaged = [c for c in cases if c["kind"] != "clean"]
    clean = [c for c in cases if c["kind"] == "clean"]
    def fix(c):
        return _vocab_fix(c, pooled)
    right = sum(1 for c in damaged if (fix(c) or "") and squash(fix(c)) == squash(c["truth"]))
    wrong = sum(1 for c in damaged if fix(c) and squash(fix(c)) != squash(c["truth"]))
    return {"damaged": len(damaged), "restored": right, "wrong": wrong, "clean": len(clean),
            "clean_changed": sum(1 for c in clean if fix(c))}


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


def render(s: dict[str, Any], model: str, seconds: float, calls: int, vocab: Optional[dict[str, dict[str, int]]] = None,
           hints: bool = False, versus: Optional[dict[str, int]] = None) -> str:
    pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "n/a"  # noqa: E731
    lines = [f"# Dropped-letter probe, model `{model}`" + (" (given names seen on this and other statements)" if hints else ""), "",
             f"**{s['fixed']} of {s['damaged']} damaged descriptions restored exactly ({pct(s['fixed'], s['damaged'])}); "
             f"{s['clean_changed']} of {s['clean']} undamaged ones wrongly changed.**", "",
             "| outcome | count |", "|---|---|",
             f"| restored exactly | {s['fixed']} |", f"| a suggestion, but the wrong one | {s['wrong_suggestion']} |",
             f"| no suggestion (unchanged or blocked) | {s['no_suggestion']} |", ""]
    for k, v in s["by_kind"].items():
        lines.append(f"- {k} letter: {v['fixed']} of {v['n']} restored ({pct(v['fixed'], v['n'])})")
    for label, v in (vocab or {}).items():
        lines += ["", f"No model, {label}: {v['restored']} of {v['damaged']} restored, {v['wrong']} wrong, "
                      f"{v['clean_changed']} of {v['clean']} undamaged changed."]
    if versus:
        lines += ["", "Model against the vocabulary rule (names also seen on other statements), on the damaged cases:",
                  f"- both restored it: {versus['both']}", f"- only the model: {versus['only_model']}",
                  f"- only the rule: {versus['only_rule']}", f"- neither: {versus['neither']}"]
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
    p.add_argument("--hints", action="store_true", help="give the model the names seen elsewhere on the statement")
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
    results = run(client, cases, hints=args.hints)
    report = render(summarize(results), client.model, client.seconds, client.calls, {"only this statement's repeated names": vocabulary_only(cases),
                                                                                        "names also seen on other statements": vocabulary_only(cases, True)}, args.hints,
                    versus_rule(results))
    print("\n" + report)
    if args.out:
        import json
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "probe.md").write_text(report, encoding="utf-8")
        (args.out / "probe.jsonl").write_text("\n".join(json.dumps({k: v for k, v in r.items() if k not in ("context", "pool")}) for r in results), encoding="utf-8")


if __name__ == "__main__":
    main()
