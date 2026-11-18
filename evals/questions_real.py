"""Step 10a: 40 questions over corpus v2, worded the way users ask (synonyms, month names, quarters, short
vendor names, few document numbers), across six kinds: lookup, clause, filter, aggregate, list, compare.

Gold answers are computed from the generator's data (corpus_v2.PAIRS), never typed by hand. Evidence rules:
  1. It supports every fact in the gold answer and every accepted value (sub totals too, as the amount before
     GST is accepted when the answer says so).
  2. Supplier-specific answers include the supplier's name in each document they rely on.
  3. "Which / how many / total of" questions include the deciding field (date, site, supplier, item) for every
     candidate document, not only the matching ones.
  4. Comparisons include the compared fields on both sides and the invoice's reference to its PO.
  5. Table facts are whole rows (description, HSN, qty, unit, rate, amount). Snippets carry their printed label.
Gold answers name a document only when the question asks which one; citations are checked separately.
Every snippet is located in the PDF text (file and page). The corpus is only read.

    uv run python -m evals.questions_real

Corpus v2 limitation: each item is bought once, every invoice matches its PO, and no month has two POs, so
filter questions can be answered without a real filter, and compare questions only have "it matches" verdicts.
"""

import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pymupdf

from evals.corpus import BUYER, SITES, VENDORS, dmy, inr, invoice_dates, invoice_interest_snippet, norm, tax_lines
from evals.corpus_v2 import DATA_DIR, PAIRS, PDF_DIR

TODAY = date(2026, 10, 31)  # fixed reference date for "last month", "overdue", "so far"
P = {po.seq: po for _, po in PAIRS}
LAYOUT = {po.seq: layout for layout, po in PAIRS}
ALL = sorted(P)
FILES = {d["number"]: d["file"] for d in json.loads((DATA_DIR / "documents.json").read_text(encoding="utf-8"))}
GST_BASIS = "amounts include GST (the printed totals); the amount before GST is accepted if the answer says so"
FY = "fiscal year April–March (ADR-003)"


def flat(text: str) -> str:
    """Comparable text: Markdown table pipes removed, then corpus.norm (NFKC, collapsed spaces, lower case)."""
    return norm(text.replace("|", " "))


# ---------------------------------------------------------------- facts from the generator


def vendor(n):
    return VENDORS[P[n].vendor]


def intra(n) -> bool:
    return vendor(n)["state_code"] == BUYER["state_code"]


def totals(n):  # taxable, tax, total
    _, taxable, tax, _, total = tax_lines(P[n].items, intra(n))
    return taxable, tax, total


def taxable(n):
    return totals(n)[0]


def total(n):
    return totals(n)[2]


def inv_date(n):
    return invoice_dates(P[n])[0]


def due(n):
    return invoice_dates(P[n])[1]


def quarter(d: date) -> int:  # fiscal quarter, April = Q1
    return (d.month - 4) % 12 // 3 + 1


def rs(x) -> str:
    return "₹" + inr(Decimal(x)).removesuffix(".00")


def po(n):
    return P[n].number


def inv(n):
    return P[n].invoice_no


def item(n, start):
    return next(it for it in P[n].items if it.desc.startswith(start))


# ---------------------------------------------------------------- snippets, labelled as each document prints them
# doc is "po" or "inv". Layout A invoices use corpus.invoice_html: format "A" for Nimbus, "GST INVOICE" for Ganesh.


def number(n, doc):
    return po(n) if doc == "po" else inv(n)


def v1(n, doc) -> bool:
    return doc == "inv" and LAYOUT[n] == "A"


def v1_gst(n, doc) -> bool:
    return v1(n, doc) and vendor(n)["layout"] != "A"


def form(n) -> bool:  # layout B: "Label: value" fields
    return LAYOUT[n] == "B"


def number_s(n, doc):
    """A document's own number needs no label: it is unambiguous in its own document (field and, in layout C,
    running header). Docling splits label and value across chunks in layout C. Dates keep their labels."""
    return number(n, doc)


def date_s(n, doc):
    if doc == "po":
        return f"Order Date: {dmy(P[n].po_date)}" if form(n) else f"PO Date {dmy(P[n].po_date)}"
    if v1_gst(n, doc):
        return f"Bill Date {dmy(inv_date(n))}"
    return f"Invoice Date{':' if form(n) else ''} {dmy(inv_date(n))}"


def due_s(n, doc="inv"):
    if v1_gst(n, doc):
        return f"Payment Due By {dmy(due(n))}"
    return f"Payment Due: {dmy(due(n))}" if form(n) else f"Due Date {dmy(due(n))}"


def po_ref_s(n, doc="inv"):
    """The invoice's reference to its PO."""
    if v1_gst(n, doc):
        return f"Your PO Ref. {po(n)}"
    return f"Against P.O. #: {po(n)}" if form(n) else f"Buyer's Order No. {po(n)}"


def subtotal_s(n, doc):
    label = ("Taxable Amount" if v1_gst(n, doc) else "Total Taxable Value") if v1(n, doc) else "Sub Total"
    return f"{label} {inr(taxable(n))}"


def total_s(n, doc):
    if doc == "po":
        label = "Order Value" if form(n) else "Grand Total"
    elif v1(n, doc):
        label = "Net Payable" if v1_gst(n, doc) else "Invoice Total"
    else:
        label = "Amount Payable" if form(n) else "Invoice Total"
    return f"{label} (INR) {inr(total(n))}"


def vendor_s(n, doc=None):
    return vendor(n)["name"]


def vendor_address_s(n, doc=None):
    return f"{vendor(n)['name']} {vendor(n)['address']}"


def gstin_s(n, doc):
    return f"{vendor_address_s(n)} GSTIN{'/UIN' if v1_gst(n, doc) else ''}: {vendor(n)['gstin']}"


def site_s(n, doc=None):
    """The site name: on a PO it only appears as the ship-to (layout B's "Deliver To" label is lost by Docling)."""
    return SITES[P[n].site].split(",")[0]


def site_address_s(n, doc=None):
    name, rest = SITES[P[n].site].split(",", 1)
    return f"{name} {rest.strip()}"


def row_s(it):
    return f"{it.desc} {it.hsn} {it.qty} {it.unit} {inr(it.rate)} {inr(it.amount)}"


def tax_s(n) -> list[str]:
    """The GST lines as printed (corpus.tax_summary_rows): IGST per rate, or CGST + SGST halves."""
    by_rate = {}
    for it in P[n].items:
        gst = (it.amount * it.gst / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
        by_rate[it.gst] = by_rate.get(it.gst, Decimal(0)) + gst
    out = []
    for rate, gst in sorted(by_rate.items()):
        if intra(n):
            half = (gst / 2).quantize(Decimal("0.01"), ROUND_HALF_UP)
            out += [f"CGST @ {rate / 2:g}% {inr(half)}", f"SGST @ {rate / 2:g}% {inr(gst - half)}"]
        else:
            out.append(f"IGST @ {rate}% {inr(gst)}")
    return out


# ---------------------------------------------------------------- evidence groups: every group is required


def ev(n, doc, *snippets):
    """One group per snippet, all in this document."""
    return [[(number(n, doc), s)] for s in snippets]


def either(n, snippet):
    """One group: the snippet (a function of n and doc) in the PO or in its invoice."""
    return [[(po(n), snippet(n, "po")), (inv(n), snippet(n, "inv"))]]


def each(numbers, doc, snippet):
    """The deciding field for every candidate document."""
    return [g for n in numbers for g in ev(n, doc, snippet(n, doc))]


def money(n, doc):
    return ev(n, doc, subtotal_s(n, doc), total_s(n, doc))


def rows(n, doc, items=None):
    return ev(n, doc, *(row_s(it) for it in (items or P[n].items)))


# ---------------------------------------------------------------- scoring


def amount(*values, must=()):
    return {"type": "amount", "values": [f"{Decimal(v):.2f}" for v in values], "must_include": list(must)}


def facts(*must):
    return {"type": "facts", "must_include": list(must)}


def verdict(value, *must):
    return {"type": "verdict", "value": value, "must_include": list(must)}


def count(value):
    return {"type": "count", "value": value}


def choose(expected, candidates):
    return {"type": "set", "expected": list(expected), "candidates": list(candidates)}


# ---------------------------------------------------------------- derived gold values

GANESH = [n for n in ALL if P[n].vendor == "ganesh"]
KUMAR = [n for n in ALL if P[n].vendor == "kumar"]
NIMBUS = [n for n in ALL if P[n].vendor == "nimbus"]
Q2_POS = [n for n in ALL if quarter(P[n].po_date) == 2]
Q3_INVOICES = [n for n in ALL if quarter(inv_date(n)) == 3 and inv_date(n).year == 2026]
MAY_POS = [n for n in ALL if P[n].po_date.month == 5]
LAST_MONTH = [n for n in ALL if (P[n].po_date.year, P[n].po_date.month) == (2026, 9)]
DUE_OCTOBER = [n for n in ALL if (due(n).year, due(n).month) == (2026, 10)]
OVERDUE = [n for n in ALL if due(n) < TODAY]
CHAKAN = [n for n in ALL if P[n].site == "chakan"]
HINJEWADI = [n for n in ALL if P[n].site == "hinjewadi"]
VENDORS_USED = sorted({vendor(n)["short"] for n in ALL})
OUTSIDE = sorted({vendor(n)["short"] for n in ALL if not intra(n)})
SPEND, SPEND_NET = {}, {}
for n in ALL:
    SPEND[vendor(n)["short"]] = SPEND.get(vendor(n)["short"], 0) + total(n)
    SPEND_NET[vendor(n)["short"]] = SPEND_NET.get(vendor(n)["short"], 0) + taxable(n)
TOP, TOP_NET = max(SPEND, key=SPEND.get), max(SPEND_NET, key=SPEND_NET.get)
BIGGEST = max(ALL, key=total)
WORKSHOP, UPS, TAPE = item(207, "Training"), item(205, "UPS"), item(208, "Packing tape")
A4, KRAFT = item(206, "A4 copier paper"), item(208, "Kraft paper")
PAPER = [(206, A4), (208, KRAFT)]  # both 12% GST
PAPER_NET = sum(it.amount for _, it in PAPER)
PAPER_GROSS = sum(it.amount * (100 + it.gst) / 100 for _, it in PAPER)
GST_12 = lambda n: [s for s in tax_s(n) if "@ 6%" in s or "@ 12%" in s]  # noqa: E731

assert MAY_POS == [202] and LAST_MONTH == [207] and Q3_INVOICES == [208] and len(GANESH) == len(NIMBUS) == 2
assert BIGGEST == 205 == max(ALL, key=taxable)  # same winner with or without GST
assert (TOP, TOP_NET) == ("Nimbus IT Services", "Ganesh Packaging")  # r23: the GST basis changes the winner
assert all(it.gst == 12 for _, it in PAPER) and all(len(GST_12(n)) == (2 if intra(n) else 1) for n, _ in PAPER)
assert all(it.gst != 12 for n, p in PAPER for it in P[n].items if it is not p)  # the 12% GST is the paper line's
assert len(tax_s(207)) == 1 and totals(207)[1] == taxable(207) * 18 / 100  # every line of invoice 207 at 18%

QUESTIONS = [
    # ---------------------------------------------------------------- lookup: one fact, one document
    dict(kind="lookup", question="What's the total value of the Bharat Steel order for GI pipes?",
         answer=f"{rs(total(204))} including GST.", score=amount(total(204), taxable(204)),
         evidence=ev(204, "po", vendor_s(204), row_s(item(204, "Galvanised"))) + money(204, "po"),
         assumptions=[GST_BASIS], traps=["short vendor name", "item short name"]),
    dict(kind="lookup", question="When is the Sunrise bill for the network equipment due?",
         answer=f"{dmy(due(205))}.", score=facts(dmy(due(205))),
         evidence=ev(205, "inv", vendor_s(205), row_s(item(205, "Network switch")), due_s(205)),
         traps=["'bill' for invoice", "category instead of item names"]),
    dict(kind="lookup", question="What is Ganesh Packaging's GSTIN?",
         answer=f"{VENDORS['ganesh']['gstin']}.", score=facts(VENDORS["ganesh"]["gstin"]),
         evidence=[[(number(n, d), gstin_s(n, d)) for n in GANESH for d in ("po", "inv")]],
         traps=["in four documents; any one is enough"]),
    dict(kind="lookup", question="Where are the wooden pallets being delivered?",
         answer=f"{SITES['chakan'].removesuffix(', Maharashtra')}.", score=facts("Chakan Warehouse"),
         evidence=ev(202, "po", row_s(item(202, "Wooden pallet")), site_address_s(202)),
         traps=["'pallets' also in the October PO's special instructions"]),
    dict(kind="lookup", question="How many UPS units did we order?",
         answer="2 (UPS, 3 kVA online, with battery bank).", score=count(2),
         evidence=ev(205, "po", row_s(UPS)), traps=["16-line table over two pages"]),
    dict(kind="lookup", question="How much did Nimbus charge for the training workshop?",
         answer=f"{rs(WORKSHOP.amount)} before GST; {rs(WORKSHOP.amount * 118 / 100)} with 18% GST.",
         score=amount(WORKSHOP.amount, WORKSHOP.amount * 118 / 100),
         evidence=ev(207, "inv", vendor_s(207), row_s(WORKSHOP), subtotal_s(207, "inv"), *tax_s(207)),
         assumptions=["18% applies to the workshop line: the invoice's only GST line is IGST @ 18%, which is "
                      "18% of the sub total", "either amount is accepted if its basis is stated"]),

    # ---------------------------------------------------------------- clause: meaning of a term
    dict(kind="clause", question="What warranty do we get on the projectors?",
         answer="24 months from the date of delivery; defective units are repaired or replaced within 3 working days.",
         score=facts("24 months", "3 working days"),
         evidence=ev(203, "po", row_s(item(203, "Projector,")), "period of 24 months from the date of delivery",
                     "repaired or replaced within 3 working days")),
    dict(kind="clause", question="If the GI pipes arrive late, what's the penalty?",
         answer="0.5% of the order value per week of delay, up to a maximum of 5% of the order value.",
         score=facts("0.5% per week", "5% maximum"),
         evidence=ev(204, "po", row_s(item(204, "Galvanised")), "0.5% of the order value per week of delay",
                     "maximum of 5% of the order value")),
    dict(kind="clause", question="How fast does Nimbus have to fix a critical problem with our cloud backup?",
         answer="Respond within 4 hours and resolve within 12 hours of logging; service credits of 5% of the "
                "monthly fee apply for every breach.",
         score=facts("4 hours", "12 hours"),
         evidence=ev(201, "po", vendor_s(201), row_s(item(201, "Cloud backup")), "responded to within 4 hours",
                     "resolved within 12 hours", "Service credits of 5% of the monthly fee apply for every breach")),
    dict(kind="clause", question="Are we paying the freight on the kraft paper order?",
         answer="Yes. Prices are ex-works; freight and transit insurance are borne by the buyer at actuals.",
         score=verdict("yes", "ex-works"),
         evidence=ev(208, "po", row_s(KRAFT),
                     "ex-works basis; freight and transit insurance shall be borne by the buyer at actuals")),
    dict(kind="clause", question="What happens if we pay the stationery bill late?",
         answer=f"Interest at 18% per annum is charged on payments received after the due date ({dmy(due(206))}).",
         score=facts("18% per annum"),
         evidence=ev(206, "inv", row_s(A4), invoice_interest_snippet(vendor(206)), due_s(206))),

    # ---------------------------------------------------------------- filter: date, supplier, site or item constraint
    dict(kind="filter", source="mentor", question="Who had ordered packaging tape in october?",
         answer=f"{BUYER['name']} ordered it from Ganesh Packaging Industries on {dmy(P[208].po_date)}: "
                "1500 packing tape (brown, 48 mm x 65 m) at ₹38 each.",
         score=facts("Shreeji Infra Projects Pvt Ltd as the buyer"),
         evidence=ev(208, "po", BUYER["name"], vendor_s(208), row_s(TAPE), date_s(208, "po")),
         assumptions=["'who' = the buyer; naming the supplier too is better"],
         traps=["packaging vs packing", "month name vs dd-mm-yyyy", "who = buyer or supplier"]),
    dict(kind="filter", question="What did we order from Ganesh in May?",
         answer="150 wooden pallets at ₹980 each and 80 bubble wrap rolls at ₹1,450 each.",
         score=choose(["Wooden pallet", "Bubble wrap"], ["Wooden pallet", "Bubble wrap", "Kraft paper", "Packing tape"]),
         evidence=each(ALL, "po", date_s) + ev(202, "po", vendor_s(202)) + rows(202, "po"),
         traps=["supplier with two orders", "month name", "PO dates of all 8 decide"]),
    dict(kind="filter", question="What rate did we pay Nimbus per user for the software in September?",
         answer="₹7,200 per user (60 users).", score=amount(item(207, "Project management").rate),
         evidence=either(207, vendor_s) + either(207, lambda n, d: row_s(item(n, "Project management")))
                  + either(207, date_s), assumptions=["rate = the printed unit price, before GST"],
         traps=["supplier with two orders", "month name"]),
    dict(kind="filter", question="Which supplier sent us the ethernet cable?",
         answer="Sunrise Electronics LLP (Cat6 UTP cable box, 305 metre).", score=facts("Sunrise Electronics"),
         evidence=either(205, vendor_s) + either(205, lambda n, d: row_s(item(n, "Cat6 UTP"))),
         traps=["ethernet vs Cat6 UTP"]),
    dict(kind="filter", question="When did we buy pallets?",
         answer=f"On {dmy(P[202].po_date)}, from Ganesh Packaging Industries (150 wooden pallets).",
         score=facts(f"{dmy(P[202].po_date)} (the invoice date {dmy(inv_date(202))} is also acceptable)"),
         evidence=ev(202, "po", vendor_s(202), row_s(item(202, "Wooden pallet"))) + either(202, date_s),
         traps=["'pallets' also in the October PO's special instructions (delivery on pallets)"]),
    dict(kind="filter", question="What payment terms did we agree on the order we placed last month?",
         answer=f"Last month = September 2026: the Nimbus IT Services order dated {dmy(P[207].po_date)}. Payment "
                f"within {P[207].pay_days} days of receiving a valid tax invoice, subject to satisfactory delivery "
                "and acceptance of the goods.",
         score=facts("September 2026", "30 days from receipt of a valid tax invoice"), expected="answer_with_assumption",
         evidence=each(ALL, "po", date_s) + ev(207, "po", vendor_s(207),
                                               "within 30 days from the date of receipt of a valid tax invoice"),
         assumptions=["last month = September 2026 (reference date 31-10-2026)"],
         traps=["relative date", "PO dates of all 8 decide"]),
    dict(kind="filter", question="Which Kumar order went to the Chakan warehouse, and what was it worth?",
         answer=f"{po(206)}, worth {rs(total(206))} including GST.",
         score=amount(total(206), taxable(206), must=[po(206)]),
         evidence=each(ALL, "po", vendor_s) + each(KUMAR, "po", site_s) + ev(206, "po", number_s(206, "po"))
                  + money(206, "po"), assumptions=[GST_BASIS], traps=["supplier with two orders; site decides"]),
    dict(kind="filter", question="What's the total on the Ganesh order?", expected="clarify_or_all",
         answer=f"Ganesh Packaging has two orders: May {rs(total(202))} and October {rs(total(208))} (including "
                "GST). Ask which one, or give both.",
         score={"type": "behaviour", "value": "asks which order, or gives both totals"},
         evidence=each(ALL, "po", vendor_s) + each(GANESH, "po", date_s) + [g for n in GANESH for g in money(n, "po")],
         traps=["ambiguous: two matching orders, different results"]),

    # ---------------------------------------------------------------- aggregate: every contributing record and value
    dict(kind="aggregate", source="mentor", question="What was the Q3 revenue", expected="answer_with_assumption",
         answer=f"The documents are {BUYER['name']}'s purchase orders and supplier invoices, so they show spend, "
                f"not revenue. Spend invoiced in Q3 FY 2026-27 (01-10-2026 to 31-12-2026): {rs(total(208))} "
                f"including GST ({rs(taxable(208))} before GST), from one invoice dated {dmy(inv_date(208))}.",
         score=amount(total(208), taxable(208), must=["spend, not revenue", "Q3 = Oct–Dec 2026"]),
         evidence=each(ALL, "inv", date_s) + money(208, "inv"),
         assumptions=["revenue → purchase spend (the documents record purchases)", f"Q3 = Oct–Dec 2026, {FY}",
                      "spend = invoice totals", GST_BASIS],
         traps=["wrong term for the documents", "fiscal quarter", "invoice dates of all 8 decide"]),
    dict(kind="aggregate", question="How much have we spent with Ganesh Packaging so far?",
         answer=f"{rs(sum(total(n) for n in GANESH))} including GST: {rs(total(202))} (May) + {rs(total(208))} (October).",
         score=amount(sum(total(n) for n in GANESH), sum(taxable(n) for n in GANESH)), expected="answer_with_assumption",
         evidence=each(ALL, "inv", vendor_s) + [g for n in GANESH for g in ev(n, "inv", date_s(n, "inv"))
                                               + money(n, "inv")],
         assumptions=["spend = invoice totals", "so far = up to 31-10-2026", GST_BASIS],
         traps=["supplier of all 8 invoices decides"]),
    dict(kind="aggregate", question="What was our total purchase value in Q2?", expected="answer_with_assumption",
         answer=f"{rs(sum(total(n) for n in Q2_POS))} including GST ({rs(sum(taxable(n) for n in Q2_POS))} before "
                f"GST), across {len(Q2_POS)} POs dated Jul–Sep 2026.",
         score=amount(sum(total(n) for n in Q2_POS), sum(taxable(n) for n in Q2_POS)),
         evidence=each(ALL, "po", date_s) + [g for n in Q2_POS for g in money(n, "po")],
         assumptions=[f"Q2 = Jul–Sep 2026, {FY}", "by PO date", GST_BASIS], traps=["fiscal quarter", "PO dates of all 8"]),
    dict(kind="aggregate", question="Which supplier have we spent the most with?", expected="answer_with_assumption",
         answer=f"{TOP}: {rs(SPEND[TOP])} including GST. Before GST the ranking changes: {TOP_NET} "
                f"{rs(SPEND_NET[TOP_NET])} vs {TOP} {rs(SPEND_NET[TOP])}.",
         score=amount(SPEND[TOP], SPEND_NET[TOP_NET],
                      must=[f"supplier matches the stated basis: {TOP} (including GST) or {TOP_NET} (before GST)"]),
         evidence=each(ALL, "inv", vendor_s) + [g for n in ALL for g in money(n, "inv")],
         assumptions=["spend = invoice totals", "the GST basis changes the winner, so it must be stated"],
         traps=["all 8 invoices", "close second place", "basis-dependent result"]),
    dict(kind="aggregate", question="How much GST have we paid on all our purchases?", expected="answer_with_assumption",
         answer=f"{rs(sum(totals(n)[1] for n in ALL))} across all 8 invoices.",
         score=amount(sum(totals(n)[1] for n in ALL)), evidence=[g for n in ALL for g in ev(n, "inv", *tax_s(n))],
         assumptions=["paid = GST charged on the supplier invoices"], traps=["all 8 invoices; CGST + SGST halves"]),
    dict(kind="aggregate", question="What's the biggest single order we've placed?",
         answer=f"{po(BIGGEST)}, the {vendor(BIGGEST)['name']} order: {rs(total(BIGGEST))} including GST "
                f"({rs(taxable(BIGGEST))} before GST).",
         score=amount(total(BIGGEST), taxable(BIGGEST), must=[f"{po(BIGGEST)} ({vendor(BIGGEST)['name']})"]),
         evidence=[g for n in ALL for g in money(n, "po")] + ev(BIGGEST, "po", number_s(BIGGEST, "po"), vendor_s(BIGGEST)),
         assumptions=[GST_BASIS], traps=["all 8 POs", "close second"]),
    dict(kind="aggregate", question="How much did we spend on paper?", expected="answer_with_assumption",
         answer=f"A4 copier paper {rs(A4.amount)} + kraft paper rolls {rs(KRAFT.amount)} = {rs(PAPER_NET)} before "
                f"GST; {rs(PAPER_GROSS)} with 12% GST.",
         score=amount(PAPER_NET, PAPER_GROSS),
         evidence=[g for n in ALL for it in P[n].items for g in either(n, lambda m, d, it=it: row_s(it))]
                  + [g for n, _ in PAPER for s in GST_12(n) for g in either(n, lambda m, d, s=s: s)],
         assumptions=["paper = A4 copier paper and kraft paper rolls (not envelopes, sticky notes or box files)",
                      "the 12% GST lines belong to the paper lines (the only 12% items)", "GST basis stated"],
         traps=["category across two suppliers", "every line item of every order decides", "'paper shredder'"]),
    dict(kind="aggregate", question="What's the total value of everything we ordered for the Hinjewadi site?",
         answer=f"{rs(sum(total(n) for n in HINJEWADI))} including GST ({rs(sum(taxable(n) for n in HINJEWADI))} "
                f"before GST), across {len(HINJEWADI)} POs.",
         score=amount(sum(total(n) for n in HINJEWADI), sum(taxable(n) for n in HINJEWADI)),
         evidence=each(ALL, "po", site_s) + [g for n in HINJEWADI for g in money(n, "po")],
         assumptions=[GST_BASIS], traps=["ship-to of all 8 POs decides"]),

    # ---------------------------------------------------------------- list / count: complete sets
    dict(kind="list", question="How many purchase orders did we place in Q2?", expected="answer_with_assumption",
         answer=f"{len(Q2_POS)} (POs dated Jul–Sep 2026).", score=count(len(Q2_POS)),
         evidence=each(ALL, "po", date_s), assumptions=[f"Q2 = Jul–Sep 2026, {FY}"],
         traps=["fiscal quarter", "PO dates of all 8"]),
    dict(kind="list", question="List all invoices from Kumar Office Solutions.",
         answer=", ".join(f"{inv(n)} ({dmy(inv_date(n))})" for n in KUMAR) + ".",
         score=choose([inv(n) for n in KUMAR], [inv(n) for n in ALL]),
         evidence=each(ALL, "inv", vendor_s) + [g for n in KUMAR for g in ev(n, "inv", number_s(n, "inv"),
                                                                           date_s(n, "inv"))],
         traps=["supplier of all 8 invoices decides"]),
    dict(kind="list", question="Which invoices fell due in October?",
         answer=", ".join(f"{inv(n)} (due {dmy(due(n))})" for n in DUE_OCTOBER) + ".",
         score=choose([inv(n) for n in DUE_OCTOBER], [inv(n) for n in ALL]),
         evidence=each(ALL, "inv", due_s) + each(DUE_OCTOBER, "inv", number_s), traps=["due dates of all 8"]),
    dict(kind="list", question="Which invoices are overdue?", expected="answer_with_assumption",
         answer="Payment status isn't in the documents. Due date before 31-10-2026: "
                + ", ".join(inv(n) for n in OVERDUE) + ". Not yet due: "
                + ", ".join(f"{inv(n)} (due {dmy(due(n))})" for n in ALL if n not in OVERDUE) + ".",
         score=choose([inv(n) for n in OVERDUE], [inv(n) for n in ALL]),
         evidence=each(ALL, "inv", due_s) + each(ALL, "inv", number_s),
         assumptions=["payments are not recorded; overdue = due date before 31-10-2026"],
         traps=["unknowable part (payment)", "relative date", "7 of 8"]),
    dict(kind="list", question="Which of our suppliers are outside Maharashtra?",
         answer=", ".join(f"{k} ({VENDORS[next(key for key, v in VENDORS.items() if v['short'] == k)]['address'].split(', ')[-1]})"
                          for k in OUTSIDE) + ".",
         score=choose(OUTSIDE, VENDORS_USED),
         evidence=[[(number(n, d), vendor_address_s(n)) for n in ALL if vendor(n)["short"] == k for d in ("po", "inv")]
                   for k in VENDORS_USED], traps=["name and address of all 5 suppliers"]),
    dict(kind="list", question="Which orders were shipped to the Chakan warehouse?",
         answer=", ".join(f"{po(n)} ({vendor(n)['short']})" for n in CHAKAN) + ".",
         score=choose([po(n) for n in CHAKAN], [po(n) for n in ALL]),
         evidence=each(ALL, "po", site_s) + [g for n in CHAKAN for g in ev(n, "po", number_s(n, "po"), vendor_s(n))],
         traps=["ship-to of all 8 POs"]),
    dict(kind="list", question="How many different items were on the stationery order?",
         answer=f"{len(P[206].items)} line items.", score=count(len(P[206].items)), evidence=rows(206, "po"),
         traps=["one document, table over two pages"]),

    # ---------------------------------------------------------------- compare: compared fields on both sides
    dict(kind="compare", question="Does the Ganesh invoice from October match what we ordered?",
         answer=f"Yes. The October invoice matches {po(208)} line for line: 200 kraft paper rolls at ₹2,350 and 1500 "
                f"packing tape at ₹38; both total {rs(total(208))}.",
         score=verdict("yes", "same quantities, rates and totals"),
         evidence=ev(208, "inv", vendor_s(208), date_s(208, "inv"), po_ref_s(208))
                  + rows(208, "po") + rows(208, "inv") + money(208, "po") + money(208, "inv")),
    dict(kind="compare", question="Did Sunrise bill the network equipment at the PO rates?",
         answer=f"Yes. All {len(P[205].items)} lines on the invoice have the same quantity and rate as the PO; both "
                f"total {rs(total(205))}.",
         score=verdict("yes", "all 16 lines match"),
         evidence=ev(205, "inv", vendor_s(205), po_ref_s(205)) + rows(205, "po") + rows(205, "inv")
                  + money(205, "po") + money(205, "inv"),
         traps=["16 rows × 2 documents, tables over two pages"]),
    dict(kind="compare", question="Which was the bigger order: Bharat's pipes or Sunrise's network equipment?",
         answer=f"Sunrise's: {rs(total(205))} vs {rs(total(204))} including GST (difference "
                f"{rs(total(205) - total(204))}); also bigger before GST ({rs(taxable(205))} vs {rs(taxable(204))}).",
         score=verdict("Sunrise", "both order values"),
         evidence=ev(204, "po", vendor_s(204), row_s(item(204, "Galvanised"))) + money(204, "po")
                  + ev(205, "po", vendor_s(205), row_s(item(205, "Network switch"))) + money(205, "po")),
    dict(kind="compare", question="How do our two Nimbus orders compare in value?",
         answer=f"April {rs(total(201))}, September {rs(total(207))}: September is larger by "
                f"{rs(total(207) - total(201))} including GST ({rs(taxable(207) - taxable(201))} before GST).",
         score=amount(total(207) - total(201), taxable(207) - taxable(201), must=["both order values"]),
         evidence=each(ALL, "po", vendor_s) + [g for n in NIMBUS for g in ev(n, "po", date_s(n, "po")) + money(n, "po")],
         assumptions=[GST_BASIS], traps=["supplier of all 8 POs decides 'two'"]),
    dict(kind="compare", question="Which Ganesh order has the quicker repair promise?",
         answer="The May order: repair or replacement within 5 working days, against 10 working days for the October "
                "order. Both have a 3-month warranty.",
         score=verdict("the May order", "5 vs 10 working days"),
         evidence=each(ALL, "po", vendor_s) + [g for n in GANESH for g in ev(
             n, "po", date_s(n, "po"), "period of 3 months from the date of delivery",
             f"repaired or replaced within {P[n].assurance[2]} working days")]),
    dict(kind="compare", question="How long after our order did Kumar invoice the stationery?",
         answer=f"{(inv_date(206) - P[206].po_date).days} days: ordered {dmy(P[206].po_date)}, invoiced "
                f"{dmy(inv_date(206))}.",
         score=count((inv_date(206) - P[206].po_date).days),
         evidence=ev(206, "po", row_s(A4), date_s(206, "po"))
                  + ev(206, "inv", vendor_s(206), po_ref_s(206), date_s(206, "inv")),
         traps=["date arithmetic across two documents"]),
]


def locate(num: str, snippet: str, pages: dict) -> dict:
    """The snippet's file and first page (None if the PDF text doesn't contain it)."""
    file = FILES[num]
    found = [i for i, text in enumerate(pages[file], 1) if flat(snippet) in text]
    return {"file": file, "snippet": snippet, "page": found[0] if found else None}


def main() -> None:
    pages = {f: [flat(p.get_text()) for p in pymupdf.open(PDF_DIR / f)] for f in FILES.values()}
    out_rows = []
    for i, q in enumerate(QUESTIONS, 1):
        out_rows.append({"id": f"r{i:02d}", "kind": q["kind"], "source": q.get("source", "10a"),
                         "question": q["question"], "expected": q.get("expected", "answer"), "answer": q["answer"],
                         "score": q["score"], "assumptions": q.get("assumptions", []), "traps": q.get("traps", []),
                         "evidence": [[locate(num, s, pages) for num, s in g] for g in q["evidence"]]})
    missing = sorted({(r["id"], e["file"], e["snippet"]) for r in out_rows for g in r["evidence"] for e in g
                      if not e["page"]})
    assert not missing, "not in PDF text:\n" + "\n".join(map(str, missing))
    out = DATA_DIR / "questions_real.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in out_rows)
    kinds = {}
    for r in out_rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    print(f"{len(out_rows)} questions {kinds} -> {out.name}")


if __name__ == "__main__":
    main()
