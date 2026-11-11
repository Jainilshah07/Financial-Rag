"""Generate the layout-varied test set (v2): 8 linked PO + invoice pairs, 2 pairs per layout.

    A  bordered tables, numbered clauses (v1 style)
    B  form-style: header fields as "Label: value" text, side-by-side parties, different wording
    C  borderless line items running onto page 2, repeated page header and footer
    D  terms as unnumbered paragraphs under bold headings

Reuses v1's data model, clause texts and question pools; the v1 set in evals/data/ is untouched.
Like v1, every evidence snippet is checked against the extracted PDF text.

    uv run python -m evals.corpus_v2
"""

import io
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

import pymupdf

from evals.corpus import (
    BUYER, CSS, PO, SITES, VENDORS, amount_in_words, dmy, inr, invoice_dates, invoice_html,
    invoice_questions, invoice_terms, item, norm, po_clauses, po_html, po_questions,
    tax_lines, tax_summary_rows,
)

DATA_DIR = Path(__file__).parent / "data_v2"
PDF_DIR = DATA_DIR / "corpus"

EXTRA_CSS = {
    "B": ".plain td { border: none; padding: 0 6pt 0 0; }",
    "C": "td, th { border: none; padding: 10pt 3pt; } th { background-color: #fff; border-bottom: 0.6pt solid #444; }"
         " body { font-size: 10pt; }",
}

# column headings: v1 wording, and B's alternative wording
PO_COLS = {"default": ["S.No", "Description", "HSN/SAC", "Qty", "Unit", "Rate (Rs.)", "Amount (Rs.)"],
           "B": ["Item", "Description", "HSN Code", "Quantity", "UOM", "Unit Price", "Line Total"]}

NETWORK_ITEMS = [
    ("Network switch, 24-port gigabit, managed", "network switches", "8517", "Nos", 4, 18900),
    ("Wireless access point, Wi-Fi 6, ceiling mount", "access points", "8517", "Nos", 12, 9600),
    ("Cat6 UTP cable box, 305 metre", "Cat6 cable boxes", "8544", "Box", 10, 8400),
    ("RJ45 connector, Cat6, pack of 100", "RJ45 connectors", "8536", "Pack", 10, 950),
    ("Patch panel, 24-port, Cat6", "patch panels", "8536", "Nos", 4, 3200),
    ("Network rack, 12U, wall mount", "network racks", "9403", "Nos", 2, 14500),
    ("UPS, 3 kVA online, with battery bank", "UPS units", "8504", "Nos", 2, 62000),
    ("Patch cord, Cat6, 1 metre", "patch cords", "8544", "Nos", 100, 120),
    ("Fibre optic cable, 6 core, armoured", "fibre cable", "8544", "Metre", 500, 64),
    ("Media converter, single mode", "media converters", "8517", "Nos", 4, 2800),
    ("Cable tray, perforated, 100 mm", "cable trays", "7308", "Metre", 60, 410),
    ("PVC conduit pipe, 25 mm", "conduit pipes", "3917", "Metre", 300, 38),
    ("Face plate, single port, with keystone jack", "face plates", "8536", "Nos", 60, 180),
    ("Cable tie, 300 mm, pack of 100", "cable ties", "3926", "Pack", 20, 140),
    ("Network cable tester, continuity and wiremap", "cable testers", "9030", "Nos", 2, 3600),
    ("Rack PDU, 6 socket, 16 A", "rack PDUs", "8536", "Nos", 4, 2600),
]
STATIONERY_ITEMS = [
    ("A4 copier paper, 75 GSM, ream of 500 sheets", "A4 paper", "4802", "Ream", 400, 265, 12),
    ("Ball pen, blue, box of 50", "ball pens", "9608", "Box", 30, 450),
    ("Whiteboard marker, assorted, box of 10", "whiteboard markers", "9608", "Box", 40, 320),
    ("Stapler, heavy duty, 50 sheets", "staplers", "8472", "Nos", 25, 540),
    ("Staple pins, 24/6, box of 1000", "staple pins", "8305", "Box", 100, 38),
    ("Box file, lever arch, A4", "box files", "4820", "Nos", 200, 95),
    ("Sticky notes, 3 x 3 inch, pad of 100", "sticky notes", "4820", "Pad", 300, 42),
    ("Highlighter, fluorescent, set of 4", "highlighters", "9608", "Set", 60, 160),
    ("Calculator, 12 digit, desktop", "calculators", "8470", "Nos", 30, 620),
    ("Paper shredder, cross cut, 10 sheets", "paper shredders", "8472", "Nos", 3, 8900),
    ("Whiteboard, magnetic, 4 x 3 feet", "whiteboards", "9610", "Nos", 10, 3400),
    ("Desk organiser, mesh, 5 compartments", "desk organisers", "3926", "Nos", 50, 380),
    ("Envelope, white, A4 size, pack of 50", "A4 envelopes", "4817", "Pack", 80, 210),
    ("Correction pen, 7 ml", "correction pens", "9608", "Nos", 100, 45),
    ("Scissors, stainless steel, 8 inch", "scissors", "8213", "Nos", 40, 110),
    ("Printer toner, black, compatible", "printer toner", "8443", "Nos", 20, 2650),
]

# (layout, PO); vendors are v1's, every PO, item and number is new
PAIRS = [
    ("A", PO(201, "nimbus", date(2026, 4, 20), "hinjewadi",
             [item("Cloud backup service, 2 TB, annual subscription", "cloud backup", "998315", "Months", 12, 18500),
              item("On-site data migration to cloud backup", "data migration", "998316", "Job", 1, 60000)],
             pay_days=30, delivery_days=7, partial=False, fob_destination=True,
             assurance=("sla", 4, 12), ld_pct="1", ld_cap=10, inspect_days=4, cancel_days=20,
             special="Backups must be encrypted at rest and stored only in data centres located in India.",
             quotation="NIT/PROP/2026/52", invoice_after_days=15, invoice_no="NIT/2026/0544")),
    ("A", PO(202, "ganesh", date(2026, 5, 12), "chakan",
             [item("Wooden pallet, 1200 x 1000 mm, heat treated", "wooden pallets", "4415", "Nos", 150, 980, gst=12),
              item("Bubble wrap roll, 1 m x 100 m", "bubble wrap rolls", "3923", "Rolls", 80, 1450)],
             pay_days=45, delivery_days=15, partial=True, fob_destination=False,
             assurance=("warranty", 3, 5), ld_pct="0.5", ld_cap=5, inspect_days=4, cancel_days=20,
             special="Pallets must carry the ISPM-15 heat treatment stamp; deliveries only on weekdays.",
             quotation="GPI/QTN/97", invoice_after_days=11, invoice_no="GPI/2026-27/0388")),
    ("B", PO(203, "kumar", date(2026, 6, 8), "hinjewadi",
             [item("Projector, 4000 lumens, WXGA, with ceiling mount", "projectors", "8528", "Nos", 4, 46500),
              item("Projector screen, motorised, 100 inch", "projector screens", "9010", "Nos", 4, 12800)],
             pay_days=30, delivery_days=12, partial=False, fob_destination=True,
             assurance=("warranty", 24, 3), ld_pct="1", ld_cap=10, inspect_days=3, cancel_days=15,
             special="Projectors must be installed in the training rooms and demonstrated to the admin team.",
             quotation="KOS/Q/1301 dated 01-06-2026", invoice_after_days=10, invoice_no="KOS/26-27/0702")),
    ("B", PO(204, "bharat", date(2026, 7, 1), "chakan",
             [item("Galvanised iron pipe, 50 mm, medium class", "GI pipes", "7306", "MT", 5, 72400),
              item("Seamless steel tube, 25 mm outer diameter", "seamless tubes", "7304", "MT", 2, 98500)],
             pay_days=45, delivery_days=9, partial=True, fob_destination=False,
             assurance=("mtc", "IS 1239:2004 medium grade"), ld_pct="0.5", ld_cap=5, inspect_days=2, cancel_days=10,
             special="Pipes must be delivered with plastic end caps fitted and stacked on timber supports.",
             quotation="BST/RFQ/0744", invoice_after_days=7, invoice_no="BST-1209")),
    ("C", PO(205, "sunrise", date(2026, 7, 22), "hinjewadi", [item(*row) for row in NETWORK_ITEMS],
             pay_days=30, delivery_days=18, partial=True, fob_destination=True,
             assurance=("warranty", 36, 5), ld_pct="0.5", ld_cap=5, inspect_days=5, cancel_days=21,
             special="All network points must be labelled and tested; a cable test report is to be handed over.",
             quotation="SE/QT/2026/455", invoice_after_days=16, invoice_no="SE/INV/2026/1032")),
    ("C", PO(206, "kumar", date(2026, 8, 18), "chakan", [item(*row) for row in STATIONERY_ITEMS],
             pay_days=60, delivery_days=8, partial=True, fob_destination=True,
             assurance=("warranty", 6, 7), ld_pct="0.5", ld_cap=5, inspect_days=3, cancel_days=14,
             special="Stationery must be packed department-wise as per the attached distribution list.",
             quotation="KOS/Q/1342 dated 12-08-2026", invoice_after_days=9, invoice_no="KOS/26-27/0768")),
    ("D", PO(207, "nimbus", date(2026, 9, 9), "hinjewadi",
             [item("Project management software licence, annual, per user", "software licences", "997331", "Users", 60, 7200),
              item("Training workshop for project managers, 2 days", "training workshop", "999293", "Job", 1, 54000)],
             pay_days=30, delivery_days=10, partial=False, fob_destination=True,
             assurance=("sla", 1, 6), ld_pct="1", ld_cap=10, inspect_days=5, cancel_days=30,
             special="Licences must be assigned to named users from the HR list; training to be held at Hinjewadi.",
             quotation="NIT/PROP/2026/77", invoice_after_days=14, invoice_no="NIT/2026/0611")),
    ("D", PO(208, "ganesh", date(2026, 10, 14), "chakan",
             [item("Kraft paper roll, 120 GSM, 1 metre width", "kraft paper rolls", "4804", "Rolls", 200, 2350, gst=12),
              item("Packing tape, brown, 48 mm x 65 m", "packing tape", "3919", "Nos", 1500, 38)],
             pay_days=45, delivery_days=14, partial=True, fob_destination=False,
             assurance=("warranty", 3, 10), ld_pct="0.5", ld_cap=5, inspect_days=5, cancel_days=20,
             special="Rolls must be wrapped in moisture-proof film and delivered on pallets of 20 rolls.",
             quotation="GPI/QTN/121", invoice_after_days=12, invoice_no="GPI/2026-27/0455")),
]


# ---------------------------------------------------------------- HTML building blocks


def fields(layout: str, pairs: list[tuple[str, str]]) -> str:
    """Header fields: a 4-column grid, or "Label: value" lines for the form-style layout."""
    if layout == "B":
        return "".join(f"<p>{k}: <b>{v}</b></p>" for k, v in pairs)
    rows = [pairs[i:i + 2] for i in range(0, len(pairs), 2)]
    return "<table>" + "".join(
        "<tr>" + "".join(f"<td>{k}</td><td>{v}</td>" for k, v in row) + "</tr>" for row in rows) + "</table>"


def party(title: str, name: str, lines: list[str]) -> str:
    return f"<h3>{title}</h3><p><b>{name}</b><br>{'<br>'.join(lines)}</p>"


def parties(layout: str, left: str, right: str) -> str:
    return f"<table class='plain'><tr><td>{left}</td><td>{right}</td></tr></table>" if layout == "B" else left + right


def site(key: str) -> tuple[str, list[str]]:
    name, *rest = SITES[key].split(",")
    return name, [", ".join(rest).strip()]


def items_table(layout: str, rows, intra: bool, total_label: str, totals) -> str:
    taxable, round_off, total = totals
    head = "".join(f"<th>{c}</th>" for c in PO_COLS.get(layout, PO_COLS["default"]))
    body = "".join(
        f"<tr><td>{i}</td><td>{it.desc}</td><td>{it.hsn}</td><td class='r'>{it.qty}</td><td>{it.unit}</td>"
        f"<td class='r'>{inr(it.rate)}</td><td class='r'>{inr(it.amount)}</td></tr>"
        for i, (it, _) in enumerate(rows, 1))
    total_row = lambda label, value: f"<tr><td colspan='6' class='r'>{label}</td><td class='r'>{value}</td></tr>"
    return (f"<table><tr>{head}</tr>{body}{total_row('Sub Total', inr(taxable))}"
            f"{tax_summary_rows(rows, intra, colspan=6)}{total_row('Round Off', inr(round_off))}"
            f"{total_row(f'<b>{total_label}</b>', f'<b>{inr(total)}</b>')}</table>")


def terms(layout: str, clauses: list[tuple[str, str]]) -> str:
    """Numbered "1. Heading: body" lines, or bold headings over plain paragraphs (layout D)."""
    if layout == "D":
        return "".join(f"<p><b>{h}</b></p><p>{b}</p>" if h else f"<p>{b}</p>" for h, b in clauses)
    return "".join(f"<p>{n}. {h + ': ' if h else ''}{b}</p>" for n, (h, b) in enumerate(clauses, 1))


# ---------------------------------------------------------------- documents


def po_doc(layout: str, po: PO) -> str:
    if layout == "A":
        return po_html(po)
    v = VENDORS[po.vendor]
    intra = v["state_code"] == BUYER["state_code"]
    rows, taxable, _, round_off, total = tax_lines(po.items, intra)
    label = (lambda a, b: b if layout == "B" else a)  # v1 wording, or B's alternative
    return f"""
<p><b>{BUYER['name']}</b><br>{BUYER['address']}<br>GSTIN: {BUYER['gstin']}</p>
<h1>{label('PURCHASE ORDER', 'Purchase Order')}</h1>
{fields(layout, [(label('PO No.', 'Order Number'), po.number), (label('PO Date', 'Order Date'), dmy(po.po_date)),
                 (label('Quotation Ref.', 'Your Quote'), po.quotation), ('Currency', 'INR')])}
{parties(layout, party(label('Vendor', 'Supplier'), v['name'], [v['address'], f"GSTIN: {v['gstin']}"]),
         party(label('Ship To', 'Deliver To'), *site(po.site)))}
{items_table(layout, rows, intra, label('Grand Total (INR)', 'Order Value (INR)'), (taxable, round_off, total))}
<p>Amount in words: {amount_in_words(total)}</p>
<h3>Special Instructions</h3>
<p>{po.special}</p>
<h3>{label('TERMS AND CONDITIONS', 'Conditions of Purchase')}</h3>
{terms(layout, list(po_clauses(po).values()))}
<p>For {BUYER['name']}<br><br>Authorised Signatory</p>
"""


def invoice_doc(layout: str, po: PO) -> str:
    if layout == "A":
        return invoice_html(po)
    v = VENDORS[po.vendor]
    intra = v["state_code"] == BUYER["state_code"]
    rows, taxable, _, round_off, total = tax_lines(po.items, intra)
    inv_date, due = invoice_dates(po)
    label = (lambda a, b: b if layout == "B" else a)
    bank = fields(layout, [("Bank", v["bank"]), ("Account No.", v["account"]), ("IFSC", v["ifsc"]), ("PAN", v["pan"])])
    return f"""
<p><b>{v['name']}</b><br>{v['address']}<br>GSTIN: {v['gstin']}</p>
<h1>TAX INVOICE</h1>
{fields(layout, [(label('Invoice No.', 'Invoice Number'), po.invoice_no), ('Invoice Date', dmy(inv_date)),
                 (label("Buyer's Order No.", 'Against P.O. #'), po.number), (label('Due Date', 'Payment Due'), dmy(due))])}
{parties(layout, party('Bill To', BUYER['name'], [BUYER['address'], f"GSTIN: {BUYER['gstin']}"]),
         party('Ship To', *site(po.site)))}
{items_table(layout, rows, intra, label('Invoice Total (INR)', 'Amount Payable (INR)'), (taxable, round_off, total))}
<p>Amount in words: {amount_in_words(total)}</p>
<h3>Bank Details</h3>
{bank}
<h3>Terms and Conditions</h3>
{terms(layout, [("", t) for t in invoice_terms(po, v, due)])}
<p>For {v['name']}<br><br>Authorised Signatory</p>
"""


def render(html: str, layout: str, path: Path, running_header: str) -> None:
    """HTML -> A4 PDF; layout C also gets a header and "Page n of N" footer on every page."""
    buffer = io.BytesIO()
    story = pymupdf.Story(html=html, user_css=CSS + EXTRA_CSS.get(layout, ""))
    writer = pymupdf.DocumentWriter(buffer)
    page, more = pymupdf.paper_rect("a4"), 1
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(page + (36, 48, -36, -48))
        story.draw(device)
        writer.end_page()
    writer.close()

    doc = pymupdf.open("pdf", buffer.getvalue())
    if layout == "C":
        for n, p in enumerate(doc, 1):
            p.insert_text((36, 30), running_header, fontsize=8)
            p.insert_text((36, p.rect.height - 24), f"Page {n} of {doc.page_count}", fontsize=8)
    doc.save(path)


# ---------------------------------------------------------------- main


def main() -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    docs, questions = [], []

    for i, (layout, po) in enumerate(PAIRS):
        v = VENDORS[po.vendor]
        po_pool, inv_pool = po_questions(po), invoice_questions(po)
        # PO: the table question plus two others; invoice: two, rotating so every type is used
        others = [q for q in po_pool if q[0] != "table"]
        po_qs = [next(q for q in po_pool if q[0] == "table"), others[(2 * i) % len(others)],
                 others[(2 * i + 1) % len(others)]]
        inv_qs = [inv_pool[(2 * i) % len(inv_pool)], inv_pool[(2 * i + 1) % len(inv_pool)]]
        specs = [("po", po.number, po_doc(layout, po), po_qs, {}),
                 ("invoice", po.invoice_no, invoice_doc(layout, po), inv_qs, {"po_number": po.number})]

        for doc_type, number, html, picked, extra in specs:
            doc_id = f"{doc_type}-{re.sub(r'[^A-Za-z0-9]+', '-', number).strip('-').lower()}"
            path = PDF_DIR / f"{doc_id}.pdf"
            title = "Purchase Order" if doc_type == "po" else "Tax Invoice"
            render(html, layout, path, f"{v['name']}  |  {title} {number}")

            pdf = pymupdf.open(path)
            text = norm("".join(p.get_text() for p in pdf))
            docs.append({"doc_id": doc_id, "file": path.name, "layout": layout, "doc_type": doc_type,
                         "number": number, "vendor": v["name"], "pages": pdf.page_count, **extra})
            for qtype, question, snippets in picked:
                missing = [s for s in snippets if norm(s) not in text]
                assert not missing, f"{doc_id}: evidence not in PDF text: {missing}"
                questions.append({"id": f"q{len(questions) + 1:02d}", "layout": layout, "type": qtype,
                                  "question": question, "doc_id": doc_id, "evidence": snippets})

    (DATA_DIR / "documents.json").write_text(json.dumps(docs, indent=2), encoding="utf-8")
    with open(DATA_DIR / "questions.jsonl", "w", encoding="utf-8") as f:
        f.writelines(json.dumps(q) + "\n" for q in questions)

    print(f"{len(docs)} documents, {sum(d['pages'] for d in docs)} pages, {len(questions)} questions")
    for layout in "ABCD":
        types = Counter(q["type"] for q in questions if q["layout"] == layout)
        pages = [d["pages"] for d in docs if d["layout"] == layout]
        print(f"  {layout}: pages {pages}  questions {dict(types)}")


if __name__ == "__main__":
    main()
