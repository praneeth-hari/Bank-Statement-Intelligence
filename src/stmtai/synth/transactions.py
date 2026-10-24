"""Generate a realistic synthetic Indian bank statement with a consistent running balance.

Everything here is fictional: bank names, people, account numbers and IFSC codes are
random. No real customer data is used anywhere in this project.
"""

from __future__ import annotations

import calendar
import datetime as dt
import random
from dataclasses import dataclass
from decimal import Decimal

from faker import Faker

from ..schema import Statement, Transaction, money

TWO = Decimal("0.01")


@dataclass(frozen=True)
class BankProfile:
    name: str
    ifsc_prefix: str
    color: str  # brand-like accent colour used by the PDF layouts


BANKS: tuple[BankProfile, ...] = (
    BankProfile("Zephyr Union Bank", "ZUBS", "#1f4e79"),
    BankProfile("Kaveri Mercantile Bank", "KMBS", "#7a1f3d"),
    BankProfile("Sagar Cooperative Bank", "SCBS", "#1d6b4f"),
    BankProfile("Nila Digital Bank", "NDBS", "#3b3b3b"),
)

MERCHANTS = [
    "SWIGGY", "ZOMATO", "AMAZON PAY", "FLIPKART", "BIGBASKET", "UBER INDIA", "IRCTC",
    "JIO PREPAID", "AIRTEL PAYMENTS", "NETFLIX", "SPOTIFY", "APOLLO PHARMACY", "DMART",
    "RELIANCE SMART", "BOOKMYSHOW", "BLINKIT", "ZEPTO", "MYNTRA", "PHARMEASY",
]
COMPANIES = [
    "ORBITAL SOFTWARE PVT LTD", "MERIDIAN TECH SERVICES", "NORTHWIND SERVICES LTD",
    "CASCADE ANALYTICS PVT LTD", "HELIX SYSTEMS INDIA",
]

# (kind, weight) for random day-to-day transactions
_KINDS = [
    ("upi_debit", 50), ("upi_credit", 12), ("pos", 12), ("atm", 6),
    ("imps_out", 5), ("neft_in", 4), ("imps_in", 3),
]


def _digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(n))


def _amount(rng: random.Random, lo: int, hi: int, round_bias: float = 0.4) -> Decimal:
    value = Decimal(rng.randint(lo * 100, hi * 100)) / 100
    if rng.random() < round_bias and value >= 50:
        value = Decimal(round(value / 10) * 10)
    return value.quantize(TWO)


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _clip_day(year: int, month: int, day: int) -> dt.date:
    return dt.date(year, month, min(day, calendar.monthrange(year, month)[1]))


def generate_statement(
    seed: int,
    bank: BankProfile,
    months: int = 1,
    txns_per_month: tuple[int, int] = (22, 40),
) -> Statement:
    rng = random.Random(seed)
    fake = Faker("en_IN")
    fake.seed_instance(seed)

    # Statement period: whole calendar months between Jan 2025 and Sep 2026.
    first_index = rng.randint(0, 20 - months)  # 0 = Jan 2025
    year, month = _add_months(2025, 1, first_index)
    period_start = dt.date(year, month, 1)
    end_year, end_month = _add_months(year, month, months - 1)
    period_end = dt.date(end_year, end_month, calendar.monthrange(end_year, end_month)[1])

    has_emi = rng.random() < 0.7
    emi_amount = _amount(rng, 4000, 28000, round_bias=0.9)
    emi_ref = f"LN{_digits(rng, 8)}"
    salary_company = rng.choice(COMPANIES)
    salary_amount = _amount(rng, 32000, 160000, round_bias=0.95)

    # 1) collect events as (date, kind, seq)
    events: list[tuple[dt.date, str]] = []
    for m in range(months):
        y, mo = _add_months(year, month, m)
        events.append((_clip_day(y, mo, rng.choice([1, 2, 3, 28])), "salary"))
        if has_emi:
            events.append((_clip_day(y, mo, rng.randint(5, 10)), "emi"))
        events.append((_clip_day(y, mo, rng.randint(10, 25)), "charge"))
        events.append((_clip_day(y, mo, 28), "interest"))
        kinds, weights = zip(*_KINDS)
        for _ in range(rng.randint(*txns_per_month)):
            events.append((_clip_day(y, mo, rng.randint(1, 31)), rng.choices(kinds, weights)[0]))
    events = [e for e in sorted(enumerate(events), key=lambda x: (x[1][0], x[0]))]
    ordered = [e for _, e in events]

    opening = _amount(rng, 5000, 150000, round_bias=0.0)
    balance = opening
    txns: list[Transaction] = []

    def person() -> str:
        return fake.name().upper()

    for d, kind in ordered:
        ref: str | None = None
        debit: Decimal | None = None
        credit: Decimal | None = None
        value_date = d

        if kind == "salary":
            credit = salary_amount
            ref = f"N{_digits(rng, 15)}"
            desc = f"NEFT-{ref}-{salary_company}-SALARY"
        elif kind == "emi":
            debit = emi_amount
            ref = emi_ref
            desc = f"ECS/EMI HOME LOAN {emi_ref}"
        elif kind == "charge":
            debit = rng.choice([Decimal("17.70"), Decimal("23.60"), Decimal("11.80")])
            desc = rng.choice(["SMS ALERT CHARGES", "DEBIT CARD AMC", "GST ON SERVICE CHARGES"])
        elif kind == "interest":
            credit = _amount(rng, 18, 320, round_bias=0.0)
            desc = "SAVINGS INTEREST CREDIT"
        elif kind == "upi_debit":
            debit = _amount(rng, 20, 6500)
            ref = _digits(rng, 12)
            party = rng.choice(MERCHANTS) if rng.random() < 0.6 else person()
            desc = f"UPI/{ref}/{party}"
        elif kind == "upi_credit":
            credit = _amount(rng, 100, 9000)
            ref = _digits(rng, 12)
            desc = f"UPI/{ref}/{person()}"
        elif kind == "pos":
            debit = _amount(rng, 150, 9500)
            desc = f"POS {rng.choice(MERCHANTS)} {fake.city().upper()}"
        elif kind == "atm":
            debit = Decimal(rng.choice([500, 1000, 2000, 3000, 5000, 10000])).quantize(TWO)
            desc = f"ATM WDL {_digits(rng, 6)} {fake.city().upper()}"
        elif kind == "imps_out":
            debit = _amount(rng, 500, 25000)
            ref = _digits(rng, 12)
            desc = f"IMPS/{ref}/{person()}"
        elif kind == "imps_in":
            credit = _amount(rng, 500, 25000)
            ref = _digits(rng, 12)
            desc = f"IMPS/{ref}/{person()}"
        else:  # neft_in
            credit = _amount(rng, 2000, 60000)
            ref = f"N{_digits(rng, 15)}"
            desc = f"NEFT-{ref}-{person()}"

        # Never overdraw: shrink the debit or drop it if the balance is too low.
        if debit is not None:
            if balance - debit < Decimal("0"):
                if balance < Decimal("60"):
                    continue
                debit = (balance * Decimal(rng.randint(10, 60)) / 100).quantize(TWO)
                if debit <= 0:
                    continue

        if kind in ("neft_in", "imps_in", "imps_out", "salary", "emi") and rng.random() < 0.3:
            value_date = d + dt.timedelta(days=1)
            if value_date > period_end:
                value_date = d

        balance = (balance + (credit or Decimal("0")) - (debit or Decimal("0"))).quantize(TWO)
        txns.append(
            Transaction(
                date=d, value_date=value_date, description=desc, ref=ref,
                debit=debit, credit=credit, balance=balance,
            )
        )

    return Statement(
        bank_name=bank.name,
        account_holder=person(),
        account_number=str(rng.randint(1, 9)) + _digits(rng, rng.choice([10, 11, 13, 14])),
        ifsc=f"{bank.ifsc_prefix}0{rng.randint(0, 999999):06d}",
        branch=f"{fake.city().upper()} MAIN BRANCH",
        currency="INR",
        period_start=period_start,
        period_end=period_end,
        opening_balance=money(opening),
        closing_balance=money(balance),
        transactions=txns,
    )
