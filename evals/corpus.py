"""Generate a small, linked purchase-order + invoice corpus with ground truth.

Every document is rendered to a real PDF (HTML -> PDF with PyMuPDF), so the
evaluation reads text exactly the way ingestion does. Each question records the
document and the exact text ("evidence snippets") that answers it; the generator
checks every snippet is present in the extracted PDF text, so labels can't drift.

    uv run python -m evals.corpus
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pymupdf

DATA_DIR = Path(__file__).parent / "data"
PDF_DIR = DATA_DIR / "corpus"

D = Decimal


# ---------------------------------------------------------------- formatting


def inr(x: Decimal) -> str:
    """Indian digit grouping: 1234567.5 -> 12,34,567.50"""
    whole, frac = f"{x.quantize(D('0.01'), ROUND_HALF_UP):.2f}".split(".")
    if len(whole) > 3:
        head, groups = whole[:-3], []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        whole = ",".join(([head] if head else []) + groups + [whole[-3:]])
    return f"{whole}.{frac}"


ONES = ("Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen "
        "Fourteen Fifteen Sixteen Seventeen Eighteen Nineteen").split()
TENS = "_ _ Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()


def _below_1000(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    words = [f"{ONES[hundreds]} Hundred"] if hundreds else []
    if rest:
        words.append(ONES[rest] if rest < 20 else
                     TENS[rest // 10] + (f" {ONES[rest % 10]}" if rest % 10 else ""))
    return " ".join(words)


def in_words(n: int) -> str:
    """Indian numbering system: 500000 -> Five Lakh"""
    parts = []
    for name, size in (("Crore", 10**7), ("Lakh", 10**5), ("Thousand", 1000)):
        q, n = divmod(n, size)
        if q:
            parts.append(f"{in_words(q) if q >= 1000 else _below_1000(q)} {name}")
    if n:
        parts.append(_below_1000(n))
    return " ".join(parts) or "Zero"


def amount_in_words(x: Decimal) -> str:
    rupees = int(x)
    paise = int((x - rupees) * 100)
    text = f"Rupees {in_words(rupees)}"
    return text + (f" and {in_words(paise)} Paise Only" if paise else " Only")


def dmy(d: date) -> str:
    return d.strftime("%d-%m-%Y")


# ---------------------------------------------------------------- master data

BUYER = {
    "name": "Shreeji Infra Projects Pvt Ltd",
    "address": "Office 704, Kalpataru Square, Senapati Bapat Road, Pune - 411016, Maharashtra",
    "gstin": "27AAKCS4821M1Z9",
    "state_code": "27",
}

SITES = {
    "hinjewadi": "Shreeji Infra - Hinjewadi Site Office, Plot 18, Phase 2, Hinjewadi, Pune - 411057, Maharashtra",
    "chakan": "Shreeji Infra - Chakan Warehouse, Gat No. 412, Chakan MIDC, Pune - 410501, Maharashtra",
}

VENDORS = {
    "kumar": dict(name="Kumar Office Solutions Pvt Ltd", short="Kumar Office Solutions",
                  address="Unit 12, Marol Industrial Estate, Andheri East, Mumbai - 400059, Maharashtra",
                  state_code="27", gstin="27AAFCK7310Q1Z2", pan="AAFCK7310Q",
                  bank="HDFC Bank, Andheri East", account="50200048817263", ifsc="HDFC0000542",
                  layout="A", inv_prefix="KOS/26-27/", city="Mumbai", interest=18, dispute_days=7),
    "sunrise": dict(name="Sunrise Electronics LLP", short="Sunrise Electronics",
                    address="No. 44, EPIP Zone, Whitefield, Bengaluru - 560066, Karnataka",
                    state_code="29", gstin="29AAQFS2289K1ZD", pan="AAQFS2289K",
                    bank="ICICI Bank, Whitefield", account="003905017342", ifsc="ICIC0000039",
                    layout="B", inv_prefix="SE/INV/", city="Bengaluru", interest=24, dispute_days=10),
    "bharat": dict(name="Bharat Steel Traders", short="Bharat Steel Traders",
                   address="Plot C-27, Hingna MIDC, Nagpur - 440016, Maharashtra",
                   state_code="27", gstin="27AAJFB5562L1ZK", pan="AAJFB5562L",
                   bank="State Bank of India, Hingna Road", account="38817250944", ifsc="SBIN0011457",
                   layout="A", inv_prefix="BST-", city="Nagpur", interest=15, dispute_days=5),
    "ganesh": dict(name="Ganesh Packaging Industries", short="Ganesh Packaging",
                   address="Shed 9, Naroda GIDC, Ahmedabad - 382330, Gujarat",
                   state_code="24", gstin="24AAKFG9902C1Z7", pan="AAKFG9902C",
                   bank="Bank of Baroda, Naroda", account="27380200001184", ifsc="BARB0NARODA",
                   layout="B", inv_prefix="GPI/2026-27/", city="Ahmedabad", interest=18, dispute_days=3),
    "nimbus": dict(name="Nimbus IT Services Pvt Ltd", short="Nimbus IT Services",
                   address="Level 5, Cyber Towers, HITEC City, Hyderabad - 500081, Telangana",
                   state_code="36", gstin="36AADCN4471B1ZP", pan="AADCN4471B",
                   bank="Axis Bank, HITEC City", account="921020044718391", ifsc="UTIB0001772",
                   layout="A", inv_prefix="NIT/", city="Hyderabad", interest=12, dispute_days=15),
}


@dataclass
class Item:
    desc: str
    short: str  # how a person would refer to it in a question
    hsn: str
    unit: str
    qty: Decimal
    rate: Decimal
    gst: int  # percent

    @property
    def amount(self) -> Decimal:
        return (self.qty * self.rate).quantize(D("0.01"))


@dataclass
class PO:
    seq: int
    vendor: str
    po_date: date
    site: str
    items: list[Item]
    pay_days: int
    delivery_days: int
    partial: bool
    fob_destination: bool
    assurance: tuple  # ("warranty", months, repair_days) | ("mtc", standard) | ("sla", respond_h, resolve_h)
    ld_pct: str
    ld_cap: int
    inspect_days: int
    cancel_days: int
    special: str
    advance_pct: int = 0
    quotation: str = ""
    # invoice side
    invoice_after_days: int = 0
    invoice_no: str = ""
    invoice_changes: dict = field(default_factory=dict)  # item index -> {"qty"|"rate": value}

    @property
    def number(self) -> str:
        return f"PO/2026-27/{self.seq:04d}"


def item(desc, short, hsn, unit, qty, rate, gst=18):
    return Item(desc, short, hsn, unit, D(str(qty)), D(str(rate)), gst)


POS = [
    PO(101, "kumar", date(2026, 4, 14), "hinjewadi",
       [item("Laptop - Dell Latitude 5450, Intel Core i5, 16 GB RAM, 512 GB SSD", "laptops", "8471", "Nos", 10, 50000),
        item("Laptop backpack, padded, 15.6 inch", "laptop bags", "4202", "Nos", 10, 1200)],
       pay_days=45, delivery_days=10, partial=False, fob_destination=True,
       assurance=("warranty", 36, 2), ld_pct="0.5", ld_cap=5, inspect_days=3, cancel_days=15,
       special="Laptops must be pre-loaded with Windows 11 Pro and Microsoft Office 2024, and asset-tagged with Shreeji Infra labels before dispatch.",
       quotation="KOS/Q/1182 dated 08-04-2026", invoice_after_days=9, invoice_no="KOS/26-27/0457"),
    PO(102, "sunrise", date(2026, 5, 6), "hinjewadi",
       [item("LED monitor, 24 inch, Full HD, IPS panel, HDMI and DisplayPort", "monitors", "8528", "Nos", 25, 9800),
        item("HDMI cable, 1.5 metre, braided", "HDMI cables", "8544", "Nos", 25, 350)],
       pay_days=30, delivery_days=14, partial=True, fob_destination=True,
       assurance=("warranty", 24, 5), ld_pct="1", ld_cap=10, inspect_days=5, cancel_days=21,
       special="Monitors must be delivered with VESA wall-mount brackets; each carton must carry the PO number on its label.",
       quotation="SE/QT/2026/314", invoice_after_days=12, invoice_no="SE/INV/2026/0789"),
    PO(103, "bharat", date(2026, 6, 2), "chakan",
       [item("TMT bars Fe500D, 12 mm diameter", "TMT bars", "7214", "MT", 18, 56500),
        item("Binding wire, 18 gauge, annealed", "binding wire", "7217", "Kg", 500, 78)],
       pay_days=60, delivery_days=7, partial=True, fob_destination=False,
       assurance=("mtc", "IS 1786:2008 grade Fe500D"), ld_pct="0.5", ld_cap=5, inspect_days=2, cancel_days=10,
       special="Unloading at the Chakan warehouse is permitted only between 8 AM and 6 PM; trucks must carry a weighbridge slip.",
       advance_pct=20, quotation="BST/RFQ/0611", invoice_after_days=6, invoice_no="BST-1123"),
    PO(104, "ganesh", date(2026, 6, 25), "chakan",
       [item("Corrugated box, 5-ply, 600 x 400 x 400 mm, brown kraft", "corrugated boxes", "4819", "Nos", 4000, 42, gst=12),
        item("Stretch film roll, 23 micron, 500 mm width", "stretch film rolls", "3920", "Rolls", 120, 650)],
       pay_days=45, delivery_days=20, partial=True, fob_destination=False,
       assurance=("warranty", 6, 7), ld_pct="0.5", ld_cap=5, inspect_days=7, cancel_days=30,
       special="Boxes must be printed with the Shreeji Infra logo in one colour as per the approved artwork; bundles of 25 boxes each.",
       quotation="GPI/QTN/88", invoice_after_days=18, invoice_no="GPI/2026-27/0342"),
    PO(105, "nimbus", date(2026, 7, 15), "hinjewadi",
       [item("Annual IT support and maintenance services for head office and site offices", "IT support contract", "998713", "Months", 12, 45000),
        item("Network firewall configuration and security audit", "firewall configuration", "998316", "Job", 1, 85000)],
       pay_days=30, delivery_days=15, partial=False, fob_destination=True,
       assurance=("sla", 2, 8), ld_pct="1", ld_cap=10, inspect_days=5, cancel_days=30,
       special="The support engineer must be on site at Hinjewadi every Tuesday and Friday; monthly uptime reports are to be emailed to it.admin@shreejiinfra.in.",
       quotation="NIT/PROP/2026/41", invoice_after_days=20, invoice_no="NIT/2026/0518"),
    PO(106, "kumar", date(2026, 8, 11), "hinjewadi",
       [item("Ergonomic office chair, mesh back, adjustable armrests", "office chairs", "9401", "Nos", 40, 7450),
        item("Workstation desk, 1500 x 750 mm, with cable tray", "workstation desks", "9403", "Nos", 20, 14200)],
       pay_days=60, delivery_days=21, partial=True, fob_destination=True,
       assurance=("warranty", 12, 3), ld_pct="1", ld_cap=10, inspect_days=3, cancel_days=15,
       special="Furniture must be assembled and installed at the site by the supplier; packaging waste must be removed the same day.",
       quotation="KOS/Q/1260 dated 05-08-2026", invoice_after_days=19, invoice_no="KOS/26-27/0631",
       invoice_changes={0: {"qty": D("42")}}),  # planted mismatch: billed 42 chairs, ordered 40
    PO(107, "sunrise", date(2026, 9, 3), "chakan",
       [item("Laser printer - HP LaserJet Pro, duplex, network enabled", "laser printers", "8443", "Nos", 6, 23900),
        item("Toner cartridge, black, high yield", "toner cartridges", "8443", "Nos", 24, 4150)],
       pay_days=30, delivery_days=10, partial=False, fob_destination=True,
       assurance=("warranty", 12, 4), ld_pct="0.5", ld_cap=5, inspect_days=5, cancel_days=14,
       special="Printers must be configured on the warehouse network and test pages printed in the presence of the store-keeper.",
       quotation="SE/QT/2026/402", invoice_after_days=8, invoice_no="SE/INV/2026/0951",
       invoice_changes={1: {"rate": D("4350")}}),  # planted mismatch: toner billed at 4,350 vs 4,150
    PO(108, "bharat", date(2026, 10, 5), "chakan",
       [item("MS angle, 50 x 50 x 5 mm", "MS angles", "7216", "MT", 6, 61200),
        item("Structural steel plate, 10 mm thickness", "steel plates", "7208", "MT", 4, 63800)],
       pay_days=45, delivery_days=12, partial=True, fob_destination=False,
       assurance=("mtc", "IS 2062:2011 grade E250"), ld_pct="0.5", ld_cap=5, inspect_days=2, cancel_days=10,
       special="Material must be delivered cut to 6 metre lengths; each bundle must be tagged with heat number and weight.",
       quotation="BST/RFQ/0702", invoice_after_days=10, invoice_no="BST-1187"),
]


# ---------------------------------------------------------------- clauses
# Clause texts are the single source for both the PDF and the question evidence.


def po_clauses(po: PO) -> dict[str, tuple[str, str]]:
    """key -> (heading, body)"""
    if po.advance_pct:
        pay = (f"An advance of {po.advance_pct}% of the order value shall be released against the supplier's "
               f"proforma invoice. The balance shall be paid within {po.pay_days} days from the date of receipt "
               f"of a valid tax invoice, subject to satisfactory delivery and acceptance of the goods.")
    else:
        pay = (f"Payment shall be made within {po.pay_days} days from the date of receipt of a valid tax invoice, "
               f"subject to satisfactory delivery and acceptance of the goods.")
    partial = ("Partial deliveries are permitted with prior written approval of the buyer."
               if po.partial else "Partial deliveries are not accepted.")
    basis = ("Prices are firm and on F.O.R. destination basis, inclusive of packing, forwarding and freight up to the ship-to address."
             if po.fob_destination else
             "Prices are firm and on ex-works basis; freight and transit insurance shall be borne by the buyer at actuals.")
    kind = po.assurance[0]
    if kind == "warranty":
        assurance = ("Warranty", f"The supplier warrants the goods against manufacturing defects for a period of "
                     f"{po.assurance[1]} months from the date of delivery. Defective units shall be repaired or "
                     f"replaced within {po.assurance[2]} working days of being reported.")
    elif kind == "mtc":
        assurance = ("Quality Certification", f"Each consignment must be accompanied by a mill test certificate "
                     f"confirming conformance to {po.assurance[1]}. Material not meeting the specification will be "
                     f"rejected and returned at the supplier's cost.")
    else:
        assurance = ("Service Levels", f"Critical incidents shall be responded to within {po.assurance[1]} hours "
                     f"and resolved within {po.assurance[2]} hours of being logged. Service credits of 5% of the "
                     f"monthly fee apply for every breach.")
    return {
        "payment": ("Payment Terms", pay),
        "delivery": ("Delivery Schedule", f"The goods shall be delivered to the ship-to address within "
                     f"{po.delivery_days} days from the date of this purchase order. {partial}"),
        "price_basis": ("Price Basis", f"{basis} GST shall be charged extra as applicable."),
        "assurance": assurance,
        "penalty": ("Late Delivery Penalty", f"If delivery is delayed beyond the agreed schedule, liquidated damages "
                    f"of {po.ld_pct}% of the order value per week of delay shall be deducted, subject to a maximum "
                    f"of {po.ld_cap}% of the order value."),
        "inspection": ("Inspection and Acceptance", f"All goods are subject to inspection at the delivery site within "
                       f"{po.inspect_days} days of receipt. Rejected goods shall be taken back and replaced by the "
                       f"supplier at its own cost."),
        "cancellation": ("Cancellation", f"The buyer reserves the right to cancel this order, in whole or in part, "
                         f"if the goods are not delivered within {po.cancel_days} days of the scheduled delivery date."),
        "invoicing": ("Invoicing", "Invoices must quote this purchase order number and be addressed to the billing "
                      "address above, along with the delivery challan and e-way bill."),
        "jurisdiction": ("Jurisdiction", "Any dispute arising out of this order shall be subject to the exclusive "
                         "jurisdiction of the courts at Pune."),
    }


def invoice_terms(po: PO, v: dict, due: date) -> list[str]:
    if v["layout"] == "A":
        return [
            f"Payment is due within {po.pay_days} days of the invoice date, i.e. on or before {dmy(due)}.",
            f"Interest @{v['interest']}% per annum will be charged on payments received after the due date.",
            f"Any discrepancy in this invoice must be reported within {v['dispute_days']} days of its receipt.",
            "Goods once sold will not be taken back.",
            f"Subject to {v['city']} jurisdiction.",
        ]
    return [
        f"Kindly remit the amount by {dmy(due)} through NEFT or RTGS to the bank account given below.",
        f"Overdue amounts attract interest at {v['interest']}% p.a. from the due date until payment.",
        f"Claims for shortage or transit damage will not be entertained after {v['dispute_days']} days from delivery.",
        f"All disputes are subject to the courts of {v['city']} only.",
    ]


def invoice_interest_snippet(v: dict) -> str:
    return (f"Interest @{v['interest']}% per annum" if v["layout"] == "A"
            else f"interest at {v['interest']}% p.a.")


def invoice_dispute_snippet(v: dict) -> str:
    return (f"reported within {v['dispute_days']} days of its receipt" if v["layout"] == "A"
            else f"not be entertained after {v['dispute_days']} days from delivery")


# ---------------------------------------------------------------- tax


def tax_lines(items: list[Item], intra_state: bool):
    rows, taxable, tax = [], D(0), D(0)
    for it in items:
        gst = (it.amount * it.gst / 100).quantize(D("0.01"), ROUND_HALF_UP)
        rows.append((it, gst))
        taxable += it.amount
        tax += gst
    total = taxable + tax
    rounded = total.quantize(D("1"), ROUND_HALF_UP)
    return rows, taxable, tax, rounded - total, rounded


# ---------------------------------------------------------------- HTML

CSS = """
body { font-size: 9pt; }
h1 { font-size: 14pt; text-align: center; margin: 2pt 0 6pt 0; }
h3 { font-size: 10pt; margin: 8pt 0 2pt 0; }
p { margin: 2pt 0; }
table { width: 100%; border-collapse: collapse; margin: 4pt 0; }
td, th { border: 0.6pt solid #444; padding: 2pt 3pt; vertical-align: top; }
th { background-color: #e8e8e8; }
.r { text-align: right; }
"""


def party(title, name, lines):
    return f"<h3>{title}</h3><p><b>{name}</b><br>{'<br>'.join(lines)}</p>"


def po_html(po: PO) -> str:
    v = VENDORS[po.vendor]
    intra = v["state_code"] == BUYER["state_code"]
    rows, taxable, tax, round_off, total = tax_lines(po.items, intra)
    item_rows = "".join(
        f"<tr><td>{i}</td><td>{it.desc}</td><td>{it.hsn}</td><td class='r'>{it.qty}</td><td>{it.unit}</td>"
        f"<td class='r'>{inr(it.rate)}</td><td class='r'>{inr(it.amount)}</td></tr>"
        for i, (it, _) in enumerate(rows, 1))
    tax_rows = tax_summary_rows(rows, intra, colspan=6)
    clauses = "".join(f"<p>{n}. {head}: {body}</p>"
                      for n, (head, body) in enumerate(po_clauses(po).values(), 1))
    return f"""
<p><b>{BUYER['name']}</b><br>{BUYER['address']}<br>GSTIN: {BUYER['gstin']}</p>
<h1>PURCHASE ORDER</h1>
<table>
<tr><td>PO No.</td><td><b>{po.number}</b></td><td>PO Date</td><td>{dmy(po.po_date)}</td></tr>
<tr><td>Quotation Ref.</td><td>{po.quotation}</td><td>Currency</td><td>INR</td></tr>
</table>
{party('Vendor', v['name'], [v['address'], f"GSTIN: {v['gstin']}"])}
{party('Ship To', SITES[po.site].split(',')[0], [', '.join(SITES[po.site].split(',')[1:]).strip()])}
<table>
<tr><th>S.No</th><th>Description</th><th>HSN/SAC</th><th>Qty</th><th>Unit</th><th>Rate (Rs.)</th><th>Amount (Rs.)</th></tr>
{item_rows}
<tr><td colspan='6' class='r'>Sub Total</td><td class='r'>{inr(taxable)}</td></tr>
{tax_rows}
<tr><td colspan='6' class='r'>Round Off</td><td class='r'>{inr(round_off)}</td></tr>
<tr><td colspan='6' class='r'><b>Grand Total (INR)</b></td><td class='r'><b>{inr(total)}</b></td></tr>
</table>
<p>Amount in words: {amount_in_words(total)}</p>
<h3>Special Instructions</h3>
<p>{po.special}</p>
<h3>TERMS AND CONDITIONS</h3>
{clauses}
<p>For {BUYER['name']}<br><br>Authorised Signatory</p>
"""


def tax_summary_rows(rows, intra, colspan):
    by_rate: dict[int, Decimal] = {}
    for it, gst in rows:
        by_rate[it.gst] = by_rate.get(it.gst, D(0)) + gst
    out = ""
    for rate, gst in sorted(by_rate.items()):
        if intra:
            half = (gst / 2).quantize(D("0.01"), ROUND_HALF_UP)
            out += (f"<tr><td colspan='{colspan}' class='r'>CGST @ {rate / 2:g}%</td><td class='r'>{inr(half)}</td></tr>"
                    f"<tr><td colspan='{colspan}' class='r'>SGST @ {rate / 2:g}%</td><td class='r'>{inr(gst - half)}</td></tr>")
        else:
            out += f"<tr><td colspan='{colspan}' class='r'>IGST @ {rate}%</td><td class='r'>{inr(gst)}</td></tr>"
    return out


def invoice_items(po: PO) -> list[Item]:
    items = []
    for i, it in enumerate(po.items):
        change = po.invoice_changes.get(i, {})
        items.append(Item(it.desc, it.short, it.hsn, it.unit,
                          change.get("qty", it.qty), change.get("rate", it.rate), it.gst))
    return items


def invoice_dates(po: PO) -> tuple[date, date]:
    inv_date = po.po_date + timedelta(days=po.invoice_after_days)
    return inv_date, inv_date + timedelta(days=po.pay_days)


def invoice_html(po: PO) -> str:
    v = VENDORS[po.vendor]
    intra = v["state_code"] == BUYER["state_code"]
    items = invoice_items(po)
    rows, taxable, tax, round_off, total = tax_lines(items, intra)
    inv_date, due = invoice_dates(po)
    terms = "".join(f"<p>{n}. {t}</p>" for n, t in enumerate(invoice_terms(po, v, due), 1))
    place = f"Maharashtra ({BUYER['state_code']})"
    bank = (f"<h3>Bank Details</h3><table><tr><td>Bank</td><td>{v['bank']}</td></tr>"
            f"<tr><td>Account No.</td><td>{v['account']}</td></tr><tr><td>IFSC</td><td>{v['ifsc']}</td></tr></table>")

    if v["layout"] == "A":
        item_rows = "".join(
            f"<tr><td>{i}</td><td>{it.desc}</td><td>{it.hsn}</td><td class='r'>{it.qty} {it.unit}</td>"
            f"<td class='r'>{inr(it.rate)}</td><td class='r'>{inr(it.amount)}</td><td class='r'>{it.gst}%</td>"
            f"<td class='r'>{inr(gst)}</td><td class='r'>{inr(it.amount + gst)}</td></tr>"
            for i, (it, gst) in enumerate(rows, 1))
        return f"""
<p><b>{v['name']}</b><br>{v['address']}<br>GSTIN: {v['gstin']} | PAN: {v['pan']}</p>
<h1>TAX INVOICE</h1>
<table>
<tr><td>Invoice No.</td><td><b>{po.invoice_no}</b></td><td>Invoice Date</td><td>{dmy(inv_date)}</td></tr>
<tr><td>Buyer's Order No.</td><td>{po.number}</td><td>Order Date</td><td>{dmy(po.po_date)}</td></tr>
<tr><td>Place of Supply</td><td>{place}</td><td>Due Date</td><td>{dmy(due)}</td></tr>
</table>
{party('Bill To', BUYER['name'], [BUYER['address'], f"GSTIN: {BUYER['gstin']}"])}
{party('Ship To', SITES[po.site].split(',')[0], [', '.join(SITES[po.site].split(',')[1:]).strip()])}
<table>
<tr><th>S.No</th><th>Description of Goods / Services</th><th>HSN/SAC</th><th>Qty</th><th>Rate</th><th>Taxable Value</th><th>GST Rate</th><th>GST Amount</th><th>Total</th></tr>
{item_rows}
</table>
<table>
<tr><td class='r'>Total Taxable Value</td><td class='r'>{inr(taxable)}</td></tr>
{tax_summary_rows(rows, intra, colspan=1)}
<tr><td class='r'>Round Off</td><td class='r'>{inr(round_off)}</td></tr>
<tr><td class='r'><b>Invoice Total (INR)</b></td><td class='r'><b>{inr(total)}</b></td></tr>
</table>
<p>Amount Chargeable (in words): {amount_in_words(total)}</p>
{bank}
<h3>Terms and Conditions</h3>
{terms}
<p>For {v['name']}<br><br>Authorised Signatory</p>
"""

    item_rows = "".join(
        f"<tr><td>{i}</td><td>{it.desc}</td><td>{it.hsn}</td><td class='r'>{it.qty}</td><td>{it.unit}</td>"
        f"<td class='r'>{inr(it.rate)}</td><td class='r'>{inr(it.amount)}</td></tr>"
        for i, (it, _) in enumerate(rows, 1))
    return f"""
<h1>GST INVOICE</h1>
<p><b>{v['name']}</b><br>{v['address']}<br>GSTIN/UIN: {v['gstin']} | PAN: {v['pan']}</p>
<table>
<tr><td>Bill No.</td><td><b>{po.invoice_no}</b></td><td>Bill Date</td><td>{dmy(inv_date)}</td></tr>
<tr><td>Your PO Ref.</td><td>{po.number} dated {dmy(po.po_date)}</td><td>Payment Due By</td><td>{dmy(due)}</td></tr>
<tr><td>State of Supply</td><td>{place}</td><td>Reverse Charge</td><td>No</td></tr>
</table>
{party('Billed To', BUYER['name'], [BUYER['address'], f"GSTIN: {BUYER['gstin']}"])}
{party('Consignee', SITES[po.site].split(',')[0], [', '.join(SITES[po.site].split(',')[1:]).strip()])}
<table>
<tr><th>#</th><th>Item Description</th><th>HSN</th><th>Qty</th><th>UOM</th><th>Unit Price</th><th>Value (Rs.)</th></tr>
{item_rows}
<tr><td colspan='6' class='r'>Taxable Amount</td><td class='r'>{inr(taxable)}</td></tr>
{tax_summary_rows(rows, intra, colspan=6)}
<tr><td colspan='6' class='r'>Round Off</td><td class='r'>{inr(round_off)}</td></tr>
<tr><td colspan='6' class='r'><b>Net Payable (INR)</b></td><td class='r'><b>{inr(total)}</b></td></tr>
</table>
<p>Rupees in words: {amount_in_words(total)}</p>
<h3>Terms of Sale</h3>
{terms}
{bank}
<p>For {v['name']}<br><br>Partner / Authorised Signatory</p>
"""


def render_pdf(html: str, path: Path) -> None:
    story = pymupdf.Story(html=html, user_css=CSS)
    writer = pymupdf.DocumentWriter(str(path))
    page = pymupdf.paper_rect("a4")
    where = page + (36, 36, -36, -36)
    more = 1
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()


# ---------------------------------------------------------------- questions


def po_questions(po: PO) -> list[dict]:
    v = VENDORS[po.vendor]
    who, what = v["short"], po.items[0].short
    c = {k: body for k, (_, body) in po_clauses(po).items()}
    first = po.items[0]
    kind = po.assurance[0]
    if kind == "warranty":
        assurance_q = (f"For how long is {who} responsible if the {what} turn out to be faulty?",
                       [f"period of {po.assurance[1]} months from the date of delivery"])
    elif kind == "mtc":
        assurance_q = (f"What paperwork has to come with the {what} from {who} to prove their quality?",
                       ["mill test certificate", po.assurance[1]])
    else:
        assurance_q = (f"How quickly must {who} react when something critical breaks?",
                       [f"responded to within {po.assurance[1]} hours"])
    pay_snip = f"within {po.pay_days} days from the date of receipt of a valid tax invoice"
    pool = [
        ("identifier", f"What are the payment terms in purchase order {po.number}?",
         [pay_snip] + ([f"advance of {po.advance_pct}%"] if po.advance_pct else [])),
        ("paraphrase", f"How soon does {who} have to get the {what} to us?",
         [f"within {po.delivery_days} days from the date of this purchase order"]),
        ("paraphrase", f"If {who} is late with the {what}, how much money can we hold back?",
         [f"{po.ld_pct}% of the order value per week of delay", f"maximum of {po.ld_cap}%"]),
        ("paraphrase", *assurance_q),
        ("table", f"At what rate per {first.unit.rstrip('s').lower()} did we order the {what} from {who}?",
         [first.desc, inr(first.rate)]),
        ("paraphrase", f"Who pays for transport on the {what} order from {who}?",
         ["F.O.R. destination basis" if po.fob_destination else "freight and transit insurance shall be borne by the buyer"]),
        ("paraphrase", f"Can {who} send the {what} in several lots?",
         ["Partial deliveries are permitted" if po.partial else "Partial deliveries are not accepted"]),
        ("identifier", f"What special instructions are given in {po.number}?", [po.special[:60]]),
        ("paraphrase", f"After how much delay can we call off the {what} order with {who}?",
         [f"not delivered within {po.cancel_days} days of the scheduled delivery date"]),
        ("identifier", f"How many days do we have to inspect the goods received under {po.number}?",
         [f"within {po.inspect_days} days of receipt"]),
    ]
    assert all(s.lower() in " ".join(c.values()).lower() or s in (first.desc, inr(first.rate), po.special[:60])
               for _, _, snips in pool for s in snips)
    return pool


def invoice_questions(po: PO) -> list[dict]:
    v = VENDORS[po.vendor]
    who, what = v["short"], po.items[0].short
    _, due = invoice_dates(po)
    inv_item = invoice_items(po)[1 if 1 in po.invoice_changes else 0]
    return [
        ("identifier", f"When is payment due for invoice {po.invoice_no}?", [dmy(due)]),
        ("paraphrase", f"Which bank account should we pay {who} into for the {what}?", [v["account"]]),
        ("identifier", f"Which purchase order is invoice {po.invoice_no} raised against?", [po.number]),
        ("paraphrase", f"What happens if we settle {who}'s bill for the {what} after the deadline?",
         [invoice_interest_snippet(v)]),
        ("identifier", f"How long do we have to raise a complaint about invoice {po.invoice_no}?",
         [invoice_dispute_snippet(v)]),
        ("table", f"What unit price did {who} bill us for the {inv_item.short}?",
         [inv_item.desc, inr(inv_item.rate)]),
    ]


def norm(text: str) -> str:
    # NFKC expands PDF ligatures ("oﬃce" -> "office") and turns non-breaking spaces into spaces
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().lower()


# ---------------------------------------------------------------- main


def main():
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    docs, questions = [], []

    for i, po in enumerate(POS):
        v = VENDORS[po.vendor]
        inv_date, due = invoice_dates(po)
        intra = v["state_code"] == BUYER["state_code"]
        specs = [
            ("po", po.number, po_html(po), po.items, po_questions(po), {}),
            ("invoice", po.invoice_no, invoice_html(po), invoice_items(po), invoice_questions(po),
             {"po_number": po.number, "invoice_date": inv_date.isoformat(), "due_date": due.isoformat()}),
        ]
        for doc_type, number, html, items, pool, extra in specs:
            doc_id = f"{doc_type}-{re.sub(r'[^A-Za-z0-9]+', '-', number).strip('-').lower()}"
            path = PDF_DIR / f"{doc_id}.pdf"
            render_pdf(html, path)
            text = norm("".join(p.get_text() for p in pymupdf.open(path)))
            _, taxable, tax, round_off, total = tax_lines(items, intra)
            docs.append({
                "doc_id": doc_id, "file": path.name, "doc_type": doc_type, "number": number,
                "vendor": v["name"], "vendor_gstin": v["gstin"], "buyer": BUYER["name"],
                "date": (po.po_date if doc_type == "po" else inv_date).isoformat(),
                "currency": "INR", "intra_state": intra,
                "items": [{"desc": it.desc, "hsn": it.hsn, "qty": str(it.qty), "unit": it.unit,
                           "rate": str(it.rate), "amount": str(it.amount), "gst_pct": it.gst} for it in items],
                "taxable": str(taxable), "tax": str(tax), "round_off": str(round_off), "total": str(total),
                "pages": pymupdf.open(path).page_count,
                **extra,
                **({"planted_mismatches": po.invoice_changes and
                    {str(k): {kk: str(vv) for kk, vv in ch.items()} for k, ch in po.invoice_changes.items()}}
                   if doc_type == "invoice" else {}),
            })
            # rotate through the question pool so every question type is used across the corpus
            per_doc = 4 if doc_type == "po" else 3
            for j in range(per_doc):
                qtype, question, snippets = pool[(i * per_doc + j) % len(pool)]
                missing = [s for s in snippets if norm(s) not in text]
                assert not missing, f"{doc_id}: evidence not in PDF text: {missing}"
                questions.append({"id": f"q{len(questions) + 1:02d}", "type": qtype, "question": question,
                                  "doc_id": doc_id, "evidence": snippets})

    (DATA_DIR / "documents.json").write_text(json.dumps(docs, indent=2), encoding="utf-8")
    with open(DATA_DIR / "questions.jsonl", "w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q) + "\n")

    types = {}
    for q in questions:
        types[q["type"]] = types.get(q["type"], 0) + 1
    print(f"{len(docs)} documents, {sum(d['pages'] for d in docs)} pages, {len(questions)} questions {types}")


if __name__ == "__main__":
    main()
