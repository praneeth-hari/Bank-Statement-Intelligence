"""Four deliberately different bank statement PDF layouts (digital, with a text layer).

Each layout varies the things that make real statements hard to parse: column sets,
number formats (Indian vs western grouping, ``Dr``/``Cr`` suffixes), date formats,
wrapped descriptions, repeated headers, carried-forward rows and summary boxes.

All output is marked as synthetic sample data in the footer.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..schema import Statement
from .transactions import BANKS, BankProfile

SYNTHETIC_NOTICE = "SYNTHETIC SAMPLE DOCUMENT - FICTIONAL BANK AND DATA - NOT A REAL STATEMENT"


# ---------------------------------------------------------------- number formats
def fmt_inr(x: Decimal) -> str:
    """Indian digit grouping: 12,34,567.89"""
    s = f"{abs(x):.2f}"
    whole, frac = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if x < 0 else "") + whole + "." + frac


def fmt_west(x: Decimal) -> str:
    """Western digit grouping: 1,234,567.89"""
    return f"{x:,.2f}"


# ---------------------------------------------------------------- shared helpers
class NumberedCanvas(canvas.Canvas):
    """Canvas that prints 'Page x of y' and the synthetic-data notice on every page."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_pages: list[dict] = []

    def showPage(self):
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_pages)
        for state in self._saved_pages:
            self.__dict__.update(state)
            width = self._pagesize[0]
            self.setFont("Helvetica", 7)
            self.setFillColor(colors.HexColor("#666666"))
            self.drawCentredString(width / 2, 8 * mm, f"Page {self._pageNumber} of {total}")
            self.setFont("Helvetica", 5.5)
            self.drawCentredString(width / 2, 5 * mm, SYNTHETIC_NOTICE)
            super().showPage()
        super().save()


def _style(name: str, size: float = 7.5, bold: bool = False, color=colors.black, leading: float | None = None,
           align: int = 0) -> ParagraphStyle:
    return ParagraphStyle(
        name,
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size,
        leading=leading or size * 1.25,
        textColor=color,
        alignment=align,
    )


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text), style)


def _doc(path: Path, pagesize, margins_mm: tuple[float, float, float, float], title: str) -> SimpleDocTemplate:
    left, right, top, bottom = (m * mm for m in margins_mm)
    return SimpleDocTemplate(
        str(path), pagesize=pagesize, leftMargin=left, rightMargin=right, topMargin=top, bottomMargin=bottom,
        title=title, author="stmtai synthetic generator",
    )


def _build(doc: SimpleDocTemplate, story: list) -> None:
    doc.build(story, canvasmaker=NumberedCanvas)


# ---------------------------------------------------------------- layout A: classic grid
def render_classic_grid(st: Statement, path: Path, bank: BankProfile) -> None:
    doc = _doc(path, A4, (12, 12, 14, 16), f"{st.bank_name} statement")
    d = lambda x: x.strftime("%d/%m/%Y")
    cell = _style("cellA", 7.5)
    head = _style("headA", 7.5, bold=True)
    label = _style("labelA", 7.5, bold=True)

    story: list = [
        Paragraph(f"<b>{escape(st.bank_name.upper())}</b>", _style("titleA", 14, bold=True, leading=17)),
        Paragraph("STATEMENT OF ACCOUNT", _style("subA", 9, bold=True, leading=12)),
        Spacer(1, 3 * mm),
    ]
    info = [
        [_p("Account Holder", label), _p(st.account_holder, cell), _p("Account No", label), _p(st.account_number, cell)],
        [_p("Branch", label), _p(st.branch, cell), _p("IFSC", label), _p(st.ifsc, cell)],
        [_p("Statement Period", label), _p(f"{d(st.period_start)} to {d(st.period_end)}", cell),
         _p("Currency", label), _p(st.currency, cell)],
        [_p("Opening Balance", label), _p(fmt_inr(st.opening_balance), cell),
         _p("Closing Balance", label), _p(fmt_inr(st.closing_balance), cell)],
    ]
    t_info = Table(info, colWidths=[32 * mm, 62 * mm, 28 * mm, 64 * mm])
    t_info.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    story += [t_info, Spacer(1, 4 * mm)]

    rows = [[_p(h, head) for h in ["Date", "Narration", "Chq./Ref.No.", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"]]]
    for t in st.transactions:
        rows.append([
            _p(d(t.date), cell), _p(t.description, cell), _p(t.ref or "", cell),
            fmt_inr(t.debit) if t.debit is not None else "",
            fmt_inr(t.credit) if t.credit is not None else "",
            fmt_inr(t.balance),
        ])
    table = Table(rows, colWidths=[20 * mm, 66 * mm, 28 * mm, 24 * mm, 24 * mm, 24 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d9d9d9")),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 7.5),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(table)
    _build(doc, story)


# ---------------------------------------------------------------- layout B: modern zebra
def render_modern_zebra(st: Statement, path: Path, bank: BankProfile) -> None:
    doc = _doc(path, A4, (12, 12, 14, 16), f"{st.bank_name} statement")
    d = lambda x: x.strftime("%d %b %Y")
    accent = colors.HexColor(bank.color)
    cell = _style("cellB", 7.5)
    small = _style("smallB", 8, color=colors.HexColor("#333333"), leading=11)

    story: list = [
        Paragraph(f'<font color="{bank.color}"><b>{escape(st.bank_name)}</b></font>',
                  _style("titleB", 18, bold=True, leading=22)),
        Paragraph("Account Statement", _style("subB", 10, color=colors.HexColor("#555555"), leading=13)),
        Spacer(1, 3 * mm),
        Paragraph(f"<b>{escape(st.account_holder)}</b>", _style("holderB", 10, leading=13)),
        Paragraph(f"Account number: {escape(st.account_number)} &nbsp;|&nbsp; IFSC: {escape(st.ifsc)} &nbsp;|&nbsp; "
                  f"Branch: {escape(st.branch)}", small),
        Paragraph(f"Period: {d(st.period_start)} - {d(st.period_end)} &nbsp;|&nbsp; Currency: {st.currency}", small),
        Paragraph(f"Opening balance: {fmt_west(st.opening_balance)} &nbsp;|&nbsp; "
                  f"Closing balance: {fmt_west(st.closing_balance)}", small),
        Spacer(1, 4 * mm),
    ]
    head = _style("headB", 8, bold=True, color=colors.white)
    rows = [[_p(h, head) for h in ["Date", "Description", "Debit", "Credit", "Balance"]]]
    for t in st.transactions:
        rows.append([
            _p(d(t.date), cell), _p(t.description, cell),
            fmt_west(t.debit) if t.debit is not None else "",
            fmt_west(t.credit) if t.credit is not None else "",
            fmt_west(t.balance),
        ])
    table = Table(rows, colWidths=[24 * mm, 80 * mm, 26 * mm, 26 * mm, 30 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), accent),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f0f0")]),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 7.5),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)

    total_debit = sum((t.debit for t in st.transactions if t.debit is not None), Decimal("0"))
    total_credit = sum((t.credit for t in st.transactions if t.credit is not None), Decimal("0"))
    summary = Table(
        [["Summary", ""], ["Total debits", fmt_west(total_debit)], ["Total credits", fmt_west(total_credit)],
         ["Closing balance", fmt_west(st.closing_balance)]],
        colWidths=[40 * mm, 40 * mm], hAlign="RIGHT",
    )
    summary.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("BOX", (0, 0), (-1, -1), 0.5, accent),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, accent),
    ]))
    story += [Spacer(1, 6 * mm), summary]
    _build(doc, story)


# ---------------------------------------------------------------- layout C: single amount column with Dr/Cr
def render_drcr_single_amount(st: Statement, path: Path, bank: BankProfile) -> None:
    doc = _doc(path, A4, (14, 14, 14, 16), f"{st.bank_name} statement")
    d = lambda x: x.strftime("%d-%b-%y")
    accent = colors.HexColor(bank.color)
    cell = _style("cellC", 7.5)
    head = _style("headC", 7.5, bold=True)
    line = _style("lineC", 8, leading=11)

    story: list = [
        Paragraph(f'<font color="{bank.color}"><b>{escape(st.bank_name)}</b></font>',
                  _style("titleC", 15, bold=True, leading=18)),
        Spacer(1, 2 * mm),
        Paragraph(f"<b>Account Statement for the period {d(st.period_start)} to {d(st.period_end)}</b>", line),
        Paragraph(f"Name: {escape(st.account_holder)}", line),
        Paragraph(f"A/c No.: {escape(st.account_number)} &nbsp;&nbsp; IFSC: {escape(st.ifsc)} &nbsp;&nbsp; "
                  f"Branch: {escape(st.branch)}", line),
        Paragraph(f"Opening Balance: {fmt_west(st.opening_balance)} Cr &nbsp;&nbsp; "
                  f"Closing Balance: {fmt_west(st.closing_balance)} Cr &nbsp;&nbsp; Currency: {st.currency}", line),
        Spacer(1, 4 * mm),
    ]
    rows = [[_p(h, head) for h in ["Date", "Particulars", "Amount", "Balance"]]]
    for t in st.transactions:
        amount = f"{fmt_west(t.debit)} Dr" if t.debit is not None else f"{fmt_west(t.credit)} Cr"
        rows.append([_p(d(t.date), cell), _p(t.description, cell), amount, f"{fmt_west(t.balance)} Cr"])
    table = Table(rows, colWidths=[22 * mm, 92 * mm, 34 * mm, 34 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONT", (0, 1), (-1, -1), "Helvetica", 7.5),
        ("LINEABOVE", (0, 0), (-1, 0), 1.0, accent), ("LINEBELOW", (0, 0), (-1, 0), 1.0, accent),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#bbbbbb")),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    _build(doc, story)


# ---------------------------------------------------------------- layout D: landscape, two dates, wrapped, B/F rows
def render_wrapped_two_date(st: Statement, path: Path, bank: BankProfile, rows_per_page: int = 18) -> None:
    doc = _doc(path, landscape(A4), (14, 14, 12, 16), f"{st.bank_name} statement")
    d = lambda x: x.strftime("%d-%m-%Y")
    accent = colors.HexColor(bank.color)
    cell = _style("cellD", 7.5)
    head = _style("headD", 7.5, bold=True, color=colors.white)
    bold = _style("boldD", 7.5, bold=True)
    small = _style("smallD", 8, leading=11)
    widths = [24 * mm, 24 * mm, 66 * mm, 40 * mm, 35 * mm, 35 * mm, 45 * mm]
    labels = ["Txn Date", "Value Date", "Description", "Ref No.", "Debit", "Credit", "Balance"]

    def page_header() -> list:
        return [
            Paragraph(f'<font color="{bank.color}"><b>{escape(st.bank_name)}</b></font>',
                      _style("titleD", 14, bold=True, leading=17)),
            Paragraph(f"{escape(st.account_holder)} &nbsp;|&nbsp; A/C {escape(st.account_number)} &nbsp;|&nbsp; "
                      f"IFSC {escape(st.ifsc)} &nbsp;|&nbsp; {escape(st.branch)}", small),
            Paragraph(f"Statement period {d(st.period_start)} to {d(st.period_end)} &nbsp;|&nbsp; "
                      f"Currency {st.currency}", small),
            Spacer(1, 3 * mm),
        ]

    txns = st.transactions
    chunks = [txns[i:i + rows_per_page] for i in range(0, len(txns), rows_per_page)] or [[]]
    story: list = []
    running = st.opening_balance
    for page_index, chunk in enumerate(chunks):
        story += page_header()
        rows = [[_p(h, head) for h in labels]]
        label = "Opening Balance" if page_index == 0 else "Balance Brought Forward"
        rows.append(["", "", _p(label, bold), "", "", "", fmt_inr(running)])
        for t in chunk:
            rows.append([
                _p(d(t.date), cell), _p(d(t.value_date or t.date), cell), _p(t.description, cell), _p(t.ref or "", cell),
                fmt_inr(t.debit) if t.debit is not None else "",
                fmt_inr(t.credit) if t.credit is not None else "",
                fmt_inr(t.balance),
            ])
            running = t.balance
        last = page_index == len(chunks) - 1
        rows.append(["", "", _p("Closing Balance" if last else "Balance Carried Forward", bold), "", "", "",
                     fmt_inr(st.closing_balance if last else running)])
        table = Table(rows, colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), accent),
            ("FONT", (0, 1), (-1, -1), "Helvetica", 7.5),
            ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#cccccc")),
            ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#eeeeee")),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eeeeee")),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(table)
        if not last:
            story.append(PageBreak())
    _build(doc, story)


# ---------------------------------------------------------------- registry
@dataclass(frozen=True)
class Layout:
    name: str
    bank: BankProfile
    render: Callable[..., None]
    fmt: Callable[[Decimal], str]
    fields: tuple[str, ...]  # transaction fields printed as separate columns/values


LAYOUTS: tuple[Layout, ...] = (
    Layout("classic_grid", BANKS[0], render_classic_grid, fmt_inr,
           ("date", "description", "ref", "debit", "credit", "balance")),
    Layout("modern_zebra", BANKS[1], render_modern_zebra, fmt_west,
           ("date", "description", "debit", "credit", "balance")),
    Layout("drcr_single_amount", BANKS[2], render_drcr_single_amount, fmt_west,
           ("date", "description", "debit", "credit", "balance")),
    Layout("wrapped_two_date", BANKS[3], render_wrapped_two_date, fmt_inr,
           ("date", "value_date", "description", "ref", "debit", "credit", "balance")),
)
LAYOUT_BY_NAME = {l.name: l for l in LAYOUTS}


def render(layout_name: str, st: Statement, path: Path) -> None:
    layout = LAYOUT_BY_NAME[layout_name]
    layout.render(st, path, layout.bank)
