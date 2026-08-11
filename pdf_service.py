from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image,
    KeepTogether
)

from db import INVOICE_DIR


# ---------------------------------------------------------------------------
# Professional invoice theme
# ---------------------------------------------------------------------------

INK = colors.HexColor("#1F2937")
MUTED = colors.HexColor("#6B7280")
BORDER = colors.HexColor("#D1D5DB")
SOFT = colors.HexColor("#F3F4F6")
SOFT_2 = colors.HexColor("#F9FAFB")
ACCENT = colors.HexColor("#17365D")
WHITE = colors.white


def _google_drive_direct_url(url):
    parsed = urlparse(url)
    file_id = ""
    match = re.search(r"/file/d/([a-zA-Z0-9_-]+)", parsed.path)
    if match:
        file_id = match.group(1)
    if not file_id:
        file_id = parse_qs(parsed.query).get("id", [""])[0]
    if file_id:
        return f"https://drive.google.com/uc?export=download&id={file_id}"
    return url


def _prepare_logo_source(logo_source):
    """Return a local logo path and whether it should be cleaned up."""
    source = str(logo_source or "").strip()
    if not source:
        return None, False

    local_path = Path(source)
    if local_path.exists():
        return str(local_path), False

    if not source.lower().startswith(("http://", "https://")):
        return None, False

    url = _google_drive_direct_url(source)
    suffix = ".png"
    lower_url = url.lower()
    for candidate in (".jpg", ".jpeg", ".png", ".webp"):
        if candidate in lower_url:
            suffix = candidate
            break

    temp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = temp.name
    temp.close()
    try:
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 GST-Billing-Utility"})
        with urlopen(request, timeout=15) as response, open(temp_path, "wb") as output:
            output.write(response.read())
        if Path(temp_path).stat().st_size == 0:
            raise ValueError("Downloaded logo is empty.")
        return temp_path, True
    except Exception:
        try:
            Path(temp_path).unlink(missing_ok=True)
        except Exception:
            pass
        return None, False


def _esc(value):
    """Basic XML escaping for ReportLab Paragraph text."""
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def _money(value):
    return f"{float(value or 0):,.2f}"


def _qty(value):
    value = float(value or 0)
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}"


def _display_date(value):
    """Display ISO dates as 06-Aug-2026; leave other formats unchanged."""
    from datetime import datetime, date as date_type
    if isinstance(value, date_type):
        return value.strftime("%d-%b-%Y")
    value = str(value or "")
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d-%b-%Y")
    except ValueError:
        return value


def _p(text, style):
    return Paragraph(_esc(text), style)


def _html(text, style):
    """Paragraph where caller intentionally supplies simple ReportLab markup."""
    return Paragraph(text, style)


def _numeric_paragraph(text, base_style, font_size=7.0):
    """
    Keep large monetary values inside fixed-width table cells.
    ReportLab Paragraphs can wrap at punctuation/space boundaries; using a
    slightly smaller dedicated numeric style gives large Indian-formatted
    amounts enough room without changing the rest of the invoice typography.
    """
    value = str(text or "")
    size = font_size
    if len(value) >= 15:
        size = 5.8
    elif len(value) >= 12:
        size = 6.2
    elif len(value) >= 10:
        size = 6.6

    style = ParagraphStyle(
        f"Numeric_{size}",
        parent=base_style,
        fontSize=size,
        leading=size + 1.2,
        alignment=TA_RIGHT,
        wordWrap=None,
    )
    return Paragraph(_esc(value), style)


def generate_invoice_pdf(invoice, items, business):
    """
    Generate a clean, professional A4 GST Tax Invoice.

    This function is a complete replacement for the existing
    generate_invoice_pdf() implementation.
    """
    safe_no = (
        invoice["invoice_no"]
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
    )
    path = INVOICE_DIR / f"{safe_no}.pdf"

    # -----------------------------------------------------------------------
    # Typography
    # -----------------------------------------------------------------------
    company_style = ParagraphStyle(
        "Company",
        fontName="Helvetica-Bold",
        fontSize=15,
        leading=18,
        textColor=INK,
        spaceAfter=2,
    )

    company_detail = ParagraphStyle(
        "CompanyDetail",
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=INK,
    )

    invoice_title = ParagraphStyle(
        "InvoiceTitle",
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=23,
        alignment=TA_RIGHT,
        textColor=ACCENT,
    )

    invoice_subtitle = ParagraphStyle(
        "InvoiceSubtitle",
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        alignment=TA_RIGHT,
        textColor=MUTED,
    )

    section_title = ParagraphStyle(
        "SectionTitle",
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=ACCENT,
    )

    body = ParagraphStyle(
        "Body",
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=INK,
    )

    body_bold = ParagraphStyle(
        "BodyBold",
        parent=body,
        fontName="Helvetica-Bold",
    )

    small = ParagraphStyle(
        "Small",
        fontName="Helvetica",
        fontSize=7.5,
        leading=9.5,
        textColor=INK,
    )

    small_muted = ParagraphStyle(
        "SmallMuted",
        parent=small,
        textColor=MUTED,
    )

    table_header = ParagraphStyle(
        "TableHeader",
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=8,
        alignment=TA_CENTER,
        textColor=WHITE,
    )

    table_left = ParagraphStyle(
        "TableLeft",
        fontName="Helvetica",
        fontSize=7.3,
        leading=9,
        alignment=TA_LEFT,
        textColor=INK,
    )

    table_right = ParagraphStyle(
        "TableRight",
        parent=table_left,
        alignment=TA_RIGHT,
    )

    table_center = ParagraphStyle(
        "TableCenter",
        parent=table_left,
        alignment=TA_CENTER,
    )

    amount_words = ParagraphStyle(
        "AmountWords",
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=INK,
    )

    footer = ParagraphStyle(
        "Footer",
        fontName="Helvetica",
        fontSize=7,
        leading=9,
        textColor=MUTED,
    )

    sign_style = ParagraphStyle(
        "Sign",
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        alignment=TA_RIGHT,
        textColor=INK,
    )

    # -----------------------------------------------------------------------
    # Document
    # -----------------------------------------------------------------------
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title=f"Tax Invoice - {invoice['invoice_no']}",
        author=business.get("business_name", ""),
    )

    story = []

    # -----------------------------------------------------------------------
    # Header: Logo + Company | TAX INVOICE
    # -----------------------------------------------------------------------
    logo_cell = ""
    logo_path, cleanup_logo = _prepare_logo_source(business.get("logo_path"))
    if logo_path:
        try:
            logo_cell = Image(
                logo_path,
                width=24 * mm,
                height=18 * mm,
                kind="proportional",
            )
        except Exception:
            logo_cell = ""

    company_address = _esc(business.get("address", ""))
    company_html = (
        f"<b>{_esc(business.get('business_name', ''))}</b><br/>"
        f"{company_address}<br/>"
        f"<font color='#6B7280'>GSTIN</font> "
        f"<b>{_esc(business.get('gstin', ''))}</b>"
        f" &nbsp;&nbsp; | &nbsp;&nbsp; "
        f"<font color='#6B7280'>State</font> "
        f"{_esc(business.get('state', ''))} ({_esc(business.get('state_code', ''))})"
    )

    title_html = (
        "<b>TAX INVOICE</b><br/>"
        f"<font size='8' color='#6B7280'>Original for Recipient</font>"
    )

    header = Table(
        [[
            logo_cell,
            _html(company_html, company_detail),
            _html(title_html, invoice_title),
        ]],
        colWidths=[27 * mm, 100 * mm, 58 * mm],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header)

    # Accent rule
    rule = Table([[""]], colWidths=[185 * mm], rowHeights=[1.6 * mm])
    rule.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story += [Spacer(1, 3 * mm), rule, Spacer(1, 4 * mm)]

    # -----------------------------------------------------------------------
    # Invoice information cards
    # -----------------------------------------------------------------------
    bill_to_html = (
        f"<font color='#17365D'><b>BILL TO</b></font><br/><br/>"
        f"<b>{_esc(invoice['client_name'])}</b><br/>"
        f"{_esc(invoice.get('client_address', ''))}<br/>"
        f"<font color='#6B7280'>GSTIN:</font> "
        f"<b>{_esc(invoice.get('client_gstin') or 'Unregistered')}</b><br/>"
        f"<font color='#6B7280'>State:</font> "
        f"{_esc(invoice.get('client_state', ''))} "
        f"({_esc(invoice.get('client_state_code', ''))})"
    )

    meta_html = (
        f"<font color='#17365D'><b>INVOICE DETAILS</b></font><br/><br/>"
        f"<font color='#6B7280'>Invoice No.</font><br/>"
        f"<b>{_esc(invoice['invoice_no'])}</b><br/><br/>"
        f"<font color='#6B7280'>Invoice Date</font><br/>"
        f"<b>{_esc(_display_date(invoice['invoice_date']))}</b>"
    )

    supply_html = (
        f"<font color='#17365D'><b>SUPPLY DETAILS</b></font><br/><br/>"
        f"<font color='#6B7280'>Place of Supply</font><br/>"
        f"<b>{_esc(invoice['place_of_supply_state'])} "
        f"({_esc(invoice['place_of_supply_code'])})</b><br/><br/>"
        f"<font color='#6B7280'>Tax Type</font><br/>"
        f"<b>{'CGST + SGST' if invoice['tax_type'] == 'INTRA' else 'IGST'}</b>"
    )

    info = Table(
        [[
            _html(bill_to_html, body),
            _html(meta_html, body),
            _html(supply_html, body),
        ]],
        colWidths=[85 * mm, 48 * mm, 52 * mm],
    )
    info.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), SOFT_2),
        ("BOX", (0, 0), (-1, -1), 0.55, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.45, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [info, Spacer(1, 5 * mm)]

    # -----------------------------------------------------------------------
    # Line items
    # -----------------------------------------------------------------------
    if invoice["tax_type"] == "INTRA":
        headers = [
            "#", "Description", "HSN/SAC", "Qty", "UQC",
            "Rate", "Disc.", "Taxable",
            "CGST", "SGST", "Amount"
        ]
        # Total = 185 mm (exact printable width).  The final Amount column
        # deliberately gets 25 mm so large invoice values cannot run off-page.
        widths = [
            6 * mm, 37 * mm, 16 * mm, 10 * mm, 10 * mm,
            18 * mm, 12 * mm, 20 * mm,
            15 * mm, 15 * mm, 26 * mm
        ]
    else:
        headers = [
            "#", "Description", "HSN/SAC", "Qty", "UQC",
            "Rate", "Disc.", "Taxable",
            "IGST", "Amount"
        ]
        # Total = 185 mm.  Monetary columns are protected for large values.
        widths = [
            6 * mm, 43 * mm, 17 * mm, 10 * mm, 10 * mm,
            19 * mm, 12 * mm, 21 * mm,
            20 * mm, 27 * mm
        ]

    table_data = [[_html(h, table_header) for h in headers]]

    for idx, item in enumerate(items, 1):
        discount_display = (
            f"{float(item['discount_percent']):.2f}%"
            if float(item["discount_percent"] or 0) else "-"
        )

        common = [
            _html(str(idx), table_center),
            _html(
                f"<b>{_esc(item['description'])}</b>",
                table_left
            ),
            _html(_esc(item["hsn_sac"]), table_center),
            _html(_qty(item["quantity"]), table_right),
            _html(_esc(item["unit"]), table_center),
            _numeric_paragraph(_money(item["rate"]), table_right),
            _html(discount_display, table_right),
            _numeric_paragraph(_money(item["taxable_value"]), table_right),
        ]

        if invoice["tax_type"] == "INTRA":
            row = common + [
                _html(
                    f"{float(item['cgst_rate']):g}%<br/><font size='6.2'>{_money(item['cgst_amount'])}</font>",
                    table_right
                ),
                _html(
                    f"{float(item['sgst_rate']):g}%<br/><font size='6.2'>{_money(item['sgst_amount'])}</font>",
                    table_right
                ),
                _numeric_paragraph(_money(item["line_total"]), table_right),
            ]
        else:
            row = common + [
                _html(
                    f"{float(item['igst_rate']):g}%<br/><font size='6.2'>{_money(item['igst_amount'])}</font>",
                    table_right
                ),
                _numeric_paragraph(_money(item["line_total"]), table_right),
            ]

        table_data.append(row)

    item_table = Table(
        table_data,
        colWidths=widths,
        repeatRows=1,
        hAlign="LEFT",
    )
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

        ("LINEBELOW", (0, 0), (-1, 0), 0.8, ACCENT),
        ("LINEBELOW", (0, 1), (-1, -1), 0.35, BORDER),
        ("LINEBEFORE", (0, 0), (0, -1), 0.35, BORDER),
        ("LINEAFTER", (-1, 0), (-1, -1), 0.35, BORDER),

        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, SOFT_2]),

        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
    ]))
    story += [item_table, Spacer(1, 5 * mm)]

    # -----------------------------------------------------------------------
    # Amount in words + totals
    # -----------------------------------------------------------------------
    words_html = (
        "<font color='#6B7280'>TOTAL AMOUNT IN WORDS</font><br/>"
        f"<b>{_esc(invoice['amount_in_words'])}</b>"
    )

    totals = [
        [_html("Gross Value", small_muted), _numeric_paragraph(_money(invoice["subtotal"]), table_right, font_size=7.3)],
    ]

    if float(invoice.get("discount_total", 0)):
        totals.append([
            _html("Less: Discount", small_muted),
            _numeric_paragraph(_money(invoice["discount_total"]), table_right, font_size=7.3)
        ])

    totals.append([
        _html("Taxable Value", body_bold),
        _numeric_paragraph(_money(invoice["taxable_total"]), table_right, font_size=7.3)
    ])

    if invoice["tax_type"] == "INTRA":
        totals += [
            [_html("CGST", small_muted), _numeric_paragraph(_money(invoice["cgst_total"]), table_right, font_size=7.3)],
            [_html("SGST", small_muted), _numeric_paragraph(_money(invoice["sgst_total"]), table_right, font_size=7.3)],
        ]
    else:
        totals += [
            [_html("IGST", small_muted), _numeric_paragraph(_money(invoice["igst_total"]), table_right, font_size=7.3)],
        ]

    totals_table = Table(totals, colWidths=[37 * mm, 28 * mm])
    totals_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    grand_total = Table(
        [[
            _html("TOTAL", ParagraphStyle(
                "TotalLabel",
                fontName="Helvetica-Bold",
                fontSize=10,
                textColor=WHITE,
            )),
            _html(
                f"<font size='{8 if len(_money(invoice['grand_total'])) >= 12 else 10}'>"
                f"<b>INR {_money(invoice['grand_total'])}</b></font>",
                ParagraphStyle(
                    "TotalValue",
                    fontName="Helvetica-Bold",
                    fontSize=10,
                    leading=11,
                    alignment=TA_RIGHT,
                    textColor=WHITE,
                )
            )
        ]],
        colWidths=[37 * mm, 28 * mm],
    )
    grand_total.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))

    right_totals = Table(
        [[totals_table], [grand_total]],
        colWidths=[65 * mm],
    )
    right_totals.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    amount_area = Table(
        [[
            _html(words_html, amount_words),
            right_totals
        ]],
        colWidths=[120 * mm, 65 * mm],
    )
    amount_area.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("LINEBEFORE", (1, 0), (1, 0), 0.5, BORDER),
        ("LEFTPADDING", (0, 0), (0, 0), 6),
        ("RIGHTPADDING", (0, 0), (0, 0), 6),
        ("TOPPADDING", (0, 0), (0, 0), 7),
        ("BOTTOMPADDING", (0, 0), (0, 0), 7),
        ("LEFTPADDING", (1, 0), (1, 0), 0),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (1, 0), (1, 0), 0),
        ("BOTTOMPADDING", (1, 0), (1, 0), 0),
    ]))
    story += [amount_area, Spacer(1, 5 * mm)]

    # -----------------------------------------------------------------------
    # Bank details / notes / signature
    # -----------------------------------------------------------------------
    bank_html = (
        "<font color='#17365D'><b>BANK DETAILS</b></font><br/><br/>"
        f"<font color='#6B7280'>Account No.</font> "
        f"<b>{_esc(business.get('account_no', ''))}</b><br/>"
        f"<font color='#6B7280'>IFSC</font> "
        f"<b>{_esc(business.get('ifsc', ''))}</b><br/>"
        f"<font color='#6B7280'>Branch</font> "
        f"{_esc(business.get('branch', ''))}"
    )

    note_text = invoice.get("notes") or "Thank you for your business."
    notes_html = (
        "<font color='#17365D'><b>NOTES</b></font><br/><br/>"
        f"{_esc(note_text)}"
    )

    sign_html = (
        f"For <b>{_esc(business.get('business_name', ''))}</b>"
        "<br/><br/><br/><br/>"
        "<b>Authorised Signatory</b>"
    )

    bottom = Table(
        [[
            _html(bank_html, small),
            _html(notes_html, small),
            _html(sign_html, sign_style),
        ]],
        colWidths=[65 * mm, 60 * mm, 60 * mm],
    )
    bottom.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("BACKGROUND", (0, 0), (1, 0), SOFT_2),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(KeepTogether(bottom))

    # Footer declaration
    story += [
        Spacer(1, 4 * mm),
        _html(
            "This is a computer-generated tax invoice.",
            footer
        )
    ]

    try:
        doc.build(story)
    finally:
        if cleanup_logo and logo_path:
            try:
                Path(logo_path).unlink(missing_ok=True)
            except Exception:
                pass
    return path
