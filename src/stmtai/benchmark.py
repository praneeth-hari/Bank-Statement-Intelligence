"""Engine-independent OCR benchmark: how many of the true amounts does an engine read correctly?

Some engines (vision-language models) return block text with layout markup instead of word boxes, so they
cannot drive the geometric table extractor. What every engine does produce is text. This benchmark scores
that text directly against the ground truth, which makes all engines comparable:

* **amount recall**: share of true debit/credit/balance amounts that appear among the engine's numeric
  tokens (compared on digits only, so ``1,23,456.78`` and ``123456.78`` match; this is lenient about
  separators, deliberately: it isolates *digit* reading, the failure that matters for reconciliation);
* **amount precision**: share of the engine's money-shaped tokens that are true amounts (hallucinated or
  garbled numbers lower it);
* **date recall** (digits of transaction dates) and **reference recall** (long digit runs).

Engine output lives in ``<root>/<engine>/<doc_id>__<kind>.txt``. ``export`` writes that for any engine that
has OCR cache entries here.

    python -m stmtai.benchmark export --engine rapidocr --data data/synthetic
    python -m stmtai.benchmark score  --data data/synthetic --root data/bench --kinds scan_light scan_medium scan_heavy
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from decimal import Decimal
from pathlib import Path

from .schema import Label

MONEY_TOKEN = re.compile(r"\d[\d,.:]*\d")  # a run of digits and separators, at least two digits
DIGITS = re.compile(r"\D")


def _digits(s: str) -> str:
    return DIGITS.sub("", s)


def truth_tokens(label: Label) -> dict[str, Counter]:
    amounts: Counter = Counter()
    dates: Counter = Counter()
    refs: Counter = Counter()
    for t in label.statement.transactions:
        for v in (t.debit, t.credit, t.balance):
            if v is not None and Decimal(v) != 0:
                amounts[_digits(f"{Decimal(v):.2f}")] += 1
        dates[t.date.strftime("%d%m%Y")] += 1
        if t.ref and len(_digits(t.ref)) >= 10:
            refs[_digits(t.ref)] += 1
    return {"amount": amounts, "date": dates, "ref": refs}


def _money_like(tok: str) -> bool:
    """Token shaped like an amount: ends in a two-digit fraction, or has no separator-only structure."""
    return bool(re.search(r"[.,:]\d{2}$", tok)) or "," in tok


def engine_tokens(text: str) -> dict[str, Counter]:
    toks = MONEY_TOKEN.findall(text)
    amounts = Counter(_digits(t) for t in toks if _money_like(t))
    all_digits = Counter(_digits(t) for t in toks)
    return {"amount": amounts, "all": all_digits}


def _present(truth: Counter, found: Counter) -> tuple[int, int]:
    total = sum(truth.values())
    hit = sum(min(n, found.get(k, 0)) for k, n in truth.items())
    return hit, total


def score_doc(label: Label, text: str) -> dict[str, int]:
    t = truth_tokens(label)
    e = engine_tokens(text)
    # dates are printed in many formats; match the engine's digit runs for dd mm yyyy or dd mm yy
    date_pool: Counter = Counter()
    for d in re.findall(r"\d{1,2}[ \t/\-.]+(?:\d{1,2}|[A-Za-z]{3})[ \t/\-.]+\d{2,4}", text):
        date_pool[_digits(d)] += 1
    month_names = {m: f"{i:02d}" for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
    for d, m, y in re.findall(r"(\d{1,2})[ \t/\-.]*([A-Za-z]{3})[A-Za-z]*[ \t/\-.]*(\d{2,4})", text):
        mm = month_names.get(m.lower())
        if mm:
            date_pool[f"{int(d):02d}{mm}{y if len(y) == 4 else '20' + y}"] += 1
    date_pool = Counter({(k if len(k) != 6 else k[:4] + "20" + k[4:]): v for k, v in date_pool.items()})
    out: dict[str, int] = {}
    out["amount_hit"], out["amount_total"] = _present(t["amount"], e["amount"])
    out["date_hit"], out["date_total"] = _present(t["date"], date_pool)
    out["ref_hit"], out["ref_total"] = _present(t["ref"], e["all"])
    true_amt = t["amount"]
    out["found_money"] = sum(e["amount"].values())
    out["found_true"] = sum(min(n, true_amt.get(k, 0)) for k, n in e["amount"].items())
    return out


def score_engine(data_dir: Path, root: Path, engine: str, kind: str) -> dict | None:
    agg: Counter = Counter()
    docs = 0
    for lp in sorted(Path(data_dir).glob("*.json")):
        label = Label.model_validate_json(lp.read_text(encoding="utf-8"))
        f = root / engine / f"{label.doc_id}__{kind}.txt"
        if not f.exists():
            continue
        agg.update(score_doc(label, f.read_text(encoding="utf-8")))
        docs += 1
    if not docs:
        return None
    r = lambda a, b: round(a / b, 4) if b else None  # noqa: E731
    return {"engine": engine, "kind": kind, "docs": docs,
            "amount_recall": r(agg["amount_hit"], agg["amount_total"]),
            "amount_precision": r(agg["found_true"], agg["found_money"]),
            "date_recall": r(agg["date_hit"], agg["date_total"]),
            "ref_recall": r(agg["ref_hit"], agg["ref_total"]),
            "true_amounts": agg["amount_total"]}


def export_from_cache(engine: str, data_dir: Path, root: Path, cache_dir: Path, kinds: list[str],
                      preprocess: str = "none") -> int:
    from .extract.ocr import CachedOnlyBackend, get_backend, ocr_pdf

    backend = get_backend(engine) if not engine.startswith("cached:") else CachedOnlyBackend(engine[7:])
    n = 0
    for lp in sorted(Path(data_dir).glob("*.json")):
        label = Label.model_validate_json(lp.read_text(encoding="utf-8"))
        for kind in kinds:
            pdf = Path(data_dir) / f"{label.doc_id}__{kind}.pdf"
            if not pdf.exists():
                continue
            pages = ocr_pdf(pdf, backend, cache_dir=cache_dir, preprocess=preprocess)
            lines = []
            for p in pages:  # reading order: top to bottom, then left to right
                segs = sorted(p.segments, key=lambda s: (round(sum(pt[1] for pt in s[0]) / 4 / 12), s[0][0][0]))
                lines += [s[1] for s in segs]
                lines.append("")
            label_dir = backend.name if preprocess == "none" else f"{backend.name}+{preprocess}"
            out = root / label_dir / f"{label.doc_id}__{kind}.txt"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("\n".join(lines), encoding="utf-8")
            n += 1
    return n


def render(results: list[dict]) -> str:
    pct = lambda x: "n/a" if x is None else f"{x:.1%}"  # noqa: E731
    rows = ["| Engine | Scan | Docs | Amount recall | Amount precision | Date recall | Reference recall |",
            "|---|---|---|---|---|---|---|"]
    for r in results:
        rows.append(f"| {r['engine']} | {r['kind'].replace('scan_', '')} | {r['docs']} | {pct(r['amount_recall'])} | "
                    f"{pct(r['amount_precision'])} | {pct(r['date_recall'])} | {pct(r['ref_recall'])} |")
    return "\n".join(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("--engine", required=True)
    e.add_argument("--data", type=Path, default=Path("data/synthetic"))
    e.add_argument("--root", type=Path, default=Path("data/bench"))
    e.add_argument("--cache-dir", type=Path, default=Path("data/ocr_cache"))
    e.add_argument("--kinds", nargs="+", default=["scan_light", "scan_medium", "scan_heavy"])
    e.add_argument("--preprocess", default="none", help="image-cleanup recipe (see extract/preprocess.py)")
    s = sub.add_parser("score")
    s.add_argument("--data", type=Path, default=Path("data/synthetic"))
    s.add_argument("--root", type=Path, default=Path("data/bench"))
    s.add_argument("--kinds", nargs="+", default=["scan_light", "scan_medium", "scan_heavy"])
    s.add_argument("--out", type=Path, default=None)
    a = ap.parse_args()
    if a.cmd == "export":
        print(f"exported {export_from_cache(a.engine, a.data, a.root, a.cache_dir, a.kinds, a.preprocess)} documents")
        return
    results = []
    for eng in sorted(p.name for p in a.root.iterdir() if p.is_dir()):
        for kind in a.kinds:
            r = score_engine(a.data, a.root, eng, kind)
            if r:
                results.append(r)
    md = render(results)
    print(md)
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "ocr-benchmark.md").write_text(md + "\n", encoding="utf-8")
        (a.out / "ocr-benchmark.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
