"""Rule-based document identity (type, number, vendor) from page 1 of a PDF.

Used to build the chunk context prefix. A field that can't be identified reliably is None.
"""

import re
from dataclasses import dataclass

import pymupdf

from financial_rag.chunking import normalise

TITLES = [  # checked in order; the first match in the top lines wins
    ("purchase_order", "Purchase Order", re.compile(r"\bpurchase\s+order\b", re.I)),
    ("invoice", "Proforma Invoice", re.compile(r"\bpro\s*-?\s*forma\s+invoice\b", re.I)),
    ("invoice", "Invoice", re.compile(r"\b(tax|gst|sales)?\s*invoice\b", re.I)),
]
NUMBER_LABELS = {
    "purchase_order": re.compile(r"^(po|purchase\s+order)\s*(no|number|#)\.?\s*:?\s*(.*)$", re.I),
    "invoice": re.compile(r"^(invoice|bill)\s*(no|number|#)\.?\s*:?\s*(.*)$", re.I),
}
VENDOR_HEADINGS = re.compile(r"^(vendor|supplier|to)\s*:?$", re.I)
COMPANY = re.compile(r"\b(pvt|private|ltd|limited|llp|inc|corporation|company|co\.|industries|traders|"
                     r"enterprises|services|solutions)\b", re.I)
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/\-_.]{2,40}$")


@dataclass
class DocInfo:
    doc_type: str | None = None  # purchase_order | invoice
    title: str | None = None  # e.g. "Purchase Order", "Proforma Invoice"
    number: str | None = None
    vendor: str | None = None

    def context(self) -> str | None:
        """e.g. 'Purchase Order PO/2026-27/0101 | Vendor: Kumar Office Solutions Pvt Ltd'"""
        head = " ".join(p for p in (self.title, self.number) if p)
        parts = [p for p in (head, self.vendor and f"Vendor: {self.vendor}") if p]
        return " | ".join(parts) or None


def _lines(doc: pymupdf.Document) -> list[str]:
    return [l.strip() for l in normalise(doc[0].get_text()).splitlines() if l.strip()] if doc.page_count else []


def _number(lines: list[str], doc_type: str) -> str | None:
    label = NUMBER_LABELS[doc_type]
    for i, line in enumerate(lines):
        m = label.match(line)
        if m:
            value = m.group(3).strip() or (lines[i + 1] if i + 1 < len(lines) else "")
            # first token only: extraction can merge the next cell ("PO/2026-27/0102 PO Date")
            value = value.split()[0] if value else ""
            return value if IDENTIFIER.match(value) and re.search(r"\d", value) else None
    return None


def _vendor(lines: list[str], doc_type: str, title_index: int) -> str | None:
    if doc_type == "purchase_order":  # the buyer issues a PO; the vendor is named under a heading
        candidates = [lines[i + 1] for i, l in enumerate(lines[:-1]) if VENDOR_HEADINGS.match(l)]
    else:  # the vendor issues the invoice; its name heads the letterhead
        candidates = [l for i, l in enumerate(lines[:6]) if i != title_index]
    return next((c for c in candidates if COMPANY.search(c) and len(c) <= 100), None)


def extract_doc_info(doc: pymupdf.Document) -> DocInfo:
    lines = _lines(doc)
    for i, line in enumerate(lines[:15]):
        for doc_type, title, pattern in TITLES:
            if pattern.search(line) and len(line) <= 40:  # a title, not a sentence mentioning it
                return DocInfo(doc_type, title, _number(lines, doc_type), _vendor(lines, doc_type, i))
    return DocInfo()
