"""Plain-language reasons for review items, so a reviewer never has to read an internal flag name."""

from __future__ import annotations

FLAG_REASONS: dict[str, str] = {
    "balance_chain_break": "The running balance does not add up on this row.",
    "both_debit_and_credit": "Both a debit and a credit were read for this row.",
    "closing_mismatch": "The last balance does not match the closing balance in the statement header.",
    "date_out_of_order": "This date comes before the previous transaction's date.",
    "date_outside_period": "This date falls outside the statement period.",
    "value_date_inconsistent": "The value date is not within a few days after the transaction date.",
    "implausible_correction": "The balance arithmetic suggests a different value, but it is too far from what was read to be a "
                              "reading error. A row may be missing.",
    "ocr_repaired": "The text was damaged by the scan and repaired automatically. Check it against the page.",
    "prefix_snapped": "A damaged payment prefix (UPI/IMPS) was restored automatically.",
    "rule_suggested": "A text rule proposed this correction (look-alike characters, spacing or a lost separator). The arithmetic "
                      "cannot check it, so compare it with the scan.",
    "llm_suggested": "A language model proposed this correction. The arithmetic cannot check it, so compare it with the scan.",
    "suggestion_verified": "A neighbouring row confirms the suggested value.",
    "suggest_clear": "The balance arithmetic suggests this cell should be empty.",
    "human_corrected": "Corrected by a reviewer.",
    "human_verified": "Confirmed by a reviewer.",
}
INFORMATIONAL = {"chain_verified", "date_order_verified", "value_date_consistent", "reference_matches", "matches_description",
                 "suggestion_verified", "human_corrected", "human_verified"}


def reasons_for(flags: list[str], confidence: float, source: str = "") -> list[str]:
    """Most serious reason first (the order of FLAG_REASONS). Informational flags are not reasons to look."""
    out = [FLAG_REASONS[f] for f in FLAG_REASONS if f in flags and f not in INFORMATIONAL]
    if not out:
        out = ["The OCR engine was not confident about this text." if source == "ocr"
               else "The extractor was not confident about this value."]
    return out
