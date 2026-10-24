"""Score the question parser against answers computed independently from the ground truth.

    python -m stmtai.query.evaluate                       # rules only, no Ollama needed
    python -m stmtai.query.evaluate --model qwen2.5:3b    # rules, then the model for what the rules refuse
    python -m stmtai.query.evaluate --mode model --model llama3.1:8b

Each question is asked of one synthetic statement. The expected answer is computed here with plain loops over the
true transactions and does not share code with the engine, so a bug in one cannot hide in the other.

Questions come in two kinds. *Plain* ones use ordinary phrasings; *indirect* ones say the same thing in words
a fixed vocabulary is less likely to know. Unanswerable questions (weather, advice, predictions) must be refused.
Three outcomes matter: correct, refused (unhelpful but honest) and **wrong** (a confident wrong number, the one
that cannot be allowed to stay high).
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import json
import random
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from ..schema import Label, Transaction
from .ask import Result, ask
from .data import Row, make_row

Q = dict[str, Any]
TWO = Decimal("0.01")

CAT_PREFIX = {"upi": "UPI/", "imps": "IMPS/", "neft": "NEFT", "pos": "POS ", "atm": "ATM"}
CAT_WORD = {"upi": "UPI", "imps": "IMPS", "neft": "NEFT", "pos": "card swipes", "atm": "ATM"}

REFUSALS = ["Will I be able to afford a car next year?", "What's the weather in Mumbai today?", "Why did my spending go up?",
            "Write me a poem about money", "How much is a bitcoin worth?", "Should I invest in mutual funds?",
            "Who is the governor of the RBI?", "Translate my statement into French"]


# ---------------------------------------------------------------- expected answers, computed independently
def _debits(txns, cat=None, text=None, lo=None, hi=None, over=None):
    out = []
    for t in txns:
        if t.debit is None or (lo and t.date < lo) or (hi and t.date > hi):
            continue
        if cat and not t.description.startswith(CAT_PREFIX[cat]):
            continue
        if text and text.upper() not in t.description.upper():
            continue
        if over is not None and t.debit < over:
            continue
        out.append(t)
    return out


def _month_bounds(y: int, m: int) -> tuple[dt.date, dt.date]:
    return dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1])


def _primary(desc: str) -> str:
    d = desc.upper()
    for name, test in (("salary", "SALARY" in d), ("emi", d.startswith("ECS") or "EMI" in d.split("/")[0]),
                       ("charges", any(k in d for k in ("SMS ALERT", "DEBIT CARD AMC", "GST ON", "CHARGES"))),
                       ("interest", "INTEREST" in d), ("upi", d.startswith("UPI/")), ("imps", d.startswith("IMPS/")),
                       ("neft", d.startswith("NEFT")), ("pos", d.startswith("POS ")), ("atm", d.startswith("ATM"))):
        if test:
            return name
    return "other"


def build_questions(labels: list[Label], per_intent: int = 4, seed: int = 5) -> list[Q]:
    rng = random.Random(seed)
    qs: list[Q] = []

    def pick_doc(k: int) -> Label:
        return labels[(k * 7 + rng.randrange(len(labels))) % len(labels)]

    def add(label: Label, intent: str, level: str, text: str, kind: str, expected: Any) -> None:
        qs.append({"doc": label.doc_id, "intent": intent, "level": level, "question": text, "kind": kind,
                   "expected": expected, "today": label.statement.transactions[-1].date.isoformat()})

    for k in range(per_intent):
        # total of one transaction type in one month
        lb = pick_doc(k)
        tx = lb.statement.transactions
        cat = rng.choice([c for c in CAT_PREFIX if any(t.description.startswith(CAT_PREFIX[c]) and t.debit for t in tx)])
        t0 = next(t for t in tx if t.description.startswith(CAT_PREFIX[cat]) and t.debit)
        y, m = t0.date.year, t0.date.month
        lo, hi = _month_bounds(y, m)
        want = sum((t.debit for t in _debits(tx, cat, lo=lo, hi=hi)), Decimal("0")).quantize(TWO)
        mon = calendar.month_name[m]
        if k % 2 == 0:
            add(lb, "total_by_type_month", "plain", f"How much did I spend on {CAT_WORD[cat]} in {mon} {y}?", "number", str(want))
        else:
            add(lb, "total_by_type_month", "indirect", f"What was the {CAT_WORD[cat]} outflow for {mon} {y}?", "number", str(want))

        # number of credits
        lb = pick_doc(k + 10)
        tx = lb.statement.transactions
        n = sum(1 for t in tx if t.credit is not None)
        if k % 2 == 0:
            add(lb, "count_credits", "plain", "How many credits did I receive?", "number", str(n))
        else:
            add(lb, "count_credits", "indirect", "How many times did money come into my account?", "number", str(n))

        # largest single debit in a month
        lb = pick_doc(k + 20)
        tx = lb.statement.transactions
        t0 = next(t for t in tx if t.debit)
        lo, hi = _month_bounds(t0.date.year, t0.date.month)
        top = max(t.debit for t in _debits(tx, lo=lo, hi=hi))
        mon = calendar.month_name[t0.date.month]
        if k % 2 == 0:
            add(lb, "largest_debit_month", "plain", f"What was my largest debit in {mon} {t0.date.year}?", "number", str(top))
        else:
            add(lb, "largest_debit_month", "indirect", f"What's the single biggest expense in {mon} {t0.date.year}?", "number", str(top))

        # total paid to one name
        lb = pick_doc(k + 30)
        tx = lb.statement.transactions
        names = [d.split("/")[-1] for d in (t.description for t in tx if t.debit and t.description.startswith("UPI/"))]
        common = max(set(names), key=names.count)
        want = sum((t.debit for t in _debits(tx, text=common)), Decimal("0")).quantize(TWO)
        if k % 2 == 0:
            add(lb, "total_to_name", "plain", f"How much did I pay to {common.title()}?", "number", str(want))
        else:
            add(lb, "total_to_name", "indirect", f"What did {common.title()} cost me altogether?", "number", str(want))

        # salary
        lb = pick_doc(k + 40)
        tx = lb.statement.transactions
        want = sum((t.credit for t in tx if t.credit and "SALARY" in t.description.upper()), Decimal("0")).quantize(TWO)
        if k % 2 == 0:
            add(lb, "salary_total", "plain", "How much salary did I receive?", "number", str(want))
        else:
            add(lb, "salary_total", "indirect", "What is the total of my salary credits?", "number", str(want))

        # balance on a date
        lb = pick_doc(k + 50)
        tx = lb.statement.transactions
        t0 = tx[len(tx) // 2]
        day_rows = [t for t in tx if t.date == t0.date]
        bal = day_rows[-1].balance
        stamp = f"{t0.date.day} {calendar.month_name[t0.date.month]} {t0.date.year}"
        if k % 2 == 0:
            add(lb, "balance_on_date", "plain", f"What was my balance on {stamp}?", "number", str(bal))
        else:
            add(lb, "balance_on_date", "indirect", f"Balance at the end of {stamp}?", "number", str(bal))

        # average of one type
        lb = pick_doc(k + 60)
        tx = lb.statement.transactions
        cat = rng.choice([c for c in CAT_PREFIX if len(_debits(tx, c)) >= 2])
        ds = _debits(tx, cat)
        want = (sum((t.debit for t in ds), Decimal("0")) / len(ds)).quantize(TWO)
        if k % 2 == 0:
            add(lb, "average_by_type", "plain", f"What is my average {CAT_WORD[cat]} payment?", "number", str(want))
        else:
            add(lb, "average_by_type", "indirect", f"On average, how big is a {CAT_WORD[cat]} debit?", "number", str(want))

        # spending per month
        lb = pick_doc(k + 70)
        tx = lb.statement.transactions
        by_month: dict[str, Decimal] = defaultdict(Decimal)
        for t in tx:
            if t.debit is not None:
                by_month[f"{t.date:%Y-%m}"] += t.debit
        want = {m_: str(v.quantize(TWO)) for m_, v in by_month.items()}
        if k % 2 == 0:
            add(lb, "spend_per_month", "plain", "How much did I spend each month?", "groups", want)
        else:
            add(lb, "spend_per_month", "indirect", "Give me month-by-month outgoings", "groups", want)

        # spending by type
        lb = pick_doc(k + 80)
        tx = lb.statement.transactions
        by_cat: dict[str, Decimal] = defaultdict(Decimal)
        for t in tx:
            if t.debit is not None:
                by_cat[_primary(t.description)] += t.debit
        want = {c: str(v.quantize(TWO)) for c, v in by_cat.items()}
        if k % 2 == 0:
            add(lb, "spend_by_type", "plain", "Show my spending by category", "groups", want)
        else:
            add(lb, "spend_by_type", "indirect", "Split what I spent by type of transaction", "groups", want)

        # n largest debits
        lb = pick_doc(k + 90)
        tx = lb.statement.transactions
        amounts = sorted((t.debit for t in tx if t.debit), reverse=True)
        n = 3
        if amounts[n - 1] != amounts[n]:
            want = [str(a) for a in amounts[:n]]
            if k % 2 == 0:
                add(lb, "top_debits", "plain", f"Show my {n} largest debits", "amounts", want)
            else:
                add(lb, "top_debits", "indirect", f"Which {n} payments were the most expensive?", "amounts", want)

        # count over a threshold
        lb = pick_doc(k + 100)
        tx = lb.statement.transactions
        threshold = rng.choice([1000, 2000, 5000])
        want = sum(1 for t in tx if t.debit is not None and t.debit >= threshold)
        if k % 2 == 0:
            add(lb, "count_over", "plain", f"How many payments over {threshold}?", "number", str(want))
        else:
            add(lb, "count_over", "indirect", f"How often did I pay {threshold} or more?", "number", str(want))

    for i, text in enumerate(REFUSALS):
        add(labels[i % len(labels)], "refusal", "plain" if i < 4 else "indirect", text, "refuse", None)
    return qs


# ---------------------------------------------------------------- scoring
def rows_from_truth(label: Label) -> list[Row]:
    return [make_row(label.doc_id, label.doc_id + ".pdf", i, t.date, t.description, t.ref, t.debit, t.credit, t.balance)
            for i, t in enumerate(label.statement.transactions)]


def judge(q: Q, res: Result) -> str:
    """correct | wrong | refused"""
    if q["kind"] == "refuse":
        return "refused" if not res.answered else "wrong"
    if not res.answered:
        return "refused"
    a = res.answer
    if q["kind"] == "number":
        return "correct" if a.kind == "number" and str(a.value) == q["expected"] or (
            a.kind == "number" and a.value is not None and Decimal(q["expected"]) == a.value) else "wrong"
    if q["kind"] == "groups":
        got = {k: str(v.quantize(TWO)) for k, v in a.groups} if a.kind == "groups" else None
        return "correct" if got == q["expected"] else "wrong"
    if q["kind"] == "amounts":
        got = sorted((str(r.amount) for r in a.rows), key=Decimal, reverse=True) if a.kind == "rows" else None
        return "correct" if got == q["expected"] else "wrong"
    return "wrong"


def evaluate(data: Path, client: Any, mode: str, per_intent: int, seed: int) -> dict[str, Any]:
    labels = [Label.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(data.glob("*.json"))]
    by_doc = {lb.doc_id: lb for lb in labels}
    results = []
    for q in build_questions(labels, per_intent, seed):
        lb = by_doc[q["doc"]]
        res = ask(q["question"], rows_from_truth(lb), client=client, today=dt.date.fromisoformat(q["today"]), mode=mode)
        results.append({**q, "outcome": judge(q, res), "parser": res.parser, "understood": res.interpretation or res.reason})
    return {"mode": mode, "results": results}


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    def block(items):
        n = len(items)
        c = lambda o: sum(r["outcome"] == o for r in items)  # noqa: E731
        return {"n": n, "correct": c("correct"), "wrong": c("wrong"), "refused": c("refused")}
    answerable = [r for r in results if r["kind"] != "refuse"]
    out = {"overall": block(results), "answerable": block(answerable), "refusal_questions": block([r for r in results if r["kind"] == "refuse"]),
           "plain": block([r for r in answerable if r["level"] == "plain"]), "indirect": block([r for r in answerable if r["level"] == "indirect"]),
           "by_intent": {}}
    for intent in sorted({r["intent"] for r in results}):
        out["by_intent"][intent] = block([r for r in results if r["intent"] == intent])
    return out


def render(summary: dict[str, Any], mode: str, model: Optional[str], failures: list[dict[str, Any]]) -> str:
    s = summary
    pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "n/a"  # noqa: E731
    who = {"rules": "rules only", "model": f"model `{model}` only", "auto": f"rules, then model `{model}`" if model else "rules only"}[mode]
    ans = s["answerable"]
    lines = [f"# Question answering ({who})", "",
             f"**Answerable questions: {ans['correct']} of {ans['n']} correct ({pct(ans['correct'], ans['n'])}), "
             f"{ans['wrong']} confidently wrong, {ans['refused']} refused.**  "
             f"Unanswerable questions refused: {s['refusal_questions']['refused']} of {s['refusal_questions']['n']}.", "",
             "| | questions | correct | wrong | refused |", "|---|---|---|---|---|"]
    for label, key in (("plain phrasing", "plain"), ("indirect phrasing", "indirect")):
        b = s[key]
        lines.append(f"| {label} | {b['n']} | {b['correct']} | {b['wrong']} | {b['refused']} |")
    lines += ["", "| intent | questions | correct | wrong | refused |", "|---|---|---|---|---|"]
    for intent, b in s["by_intent"].items():
        lines.append(f"| {intent} | {b['n']} | {b['correct']} | {b['wrong']} | {b['refused']} |")
    if failures:
        lines += ["", "## Not answered correctly", ""]
        for f in failures[:25]:
            lines.append(f"- [{f['outcome']}] {f['question']} -> {f['understood']}")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description="Evaluate the natural-language query layer.")
    p.add_argument("--data", type=Path, default=Path("data/synthetic"))
    p.add_argument("--model", default=None, help="Ollama model for the model parser (omit for rules only)")
    p.add_argument("--mode", choices=["rules", "model", "auto"], default=None)
    p.add_argument("--per-intent", type=int, default=4)
    p.add_argument("--seed", type=int, default=5)
    p.add_argument("--cache", type=Path, default=Path("data/llm_cache"))
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    client = None
    if args.model:
        from ..llm.client import OllamaClient
        client = OllamaClient(model=args.model, cache_dir=args.cache)
        client.check()
    mode = args.mode or ("auto" if client else "rules")
    run_ = evaluate(args.data, client, mode, args.per_intent, args.seed)
    summary = summarize(run_["results"])
    failures = [r for r in run_["results"] if r["outcome"] != "correct" and not (r["kind"] == "refuse" and r["outcome"] == "refused")]
    report = render(summary, mode, args.model, failures)
    if client:
        report += f"\n\n{client.calls} model calls, {client.seconds:.0f}s, {client.cache_hits} from cache."
    print(report)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "report.md").write_text(report, encoding="utf-8")
        (args.out / "results.json").write_text(json.dumps(run_["results"], indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
