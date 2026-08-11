from db import get_connection, get_active_business_id
from gst_utils import financial_year, calculate_item, invoice_totals, number_to_words_indian


def next_invoice_number(invoice_date, business):
    fy = financial_year(invoice_date)
    prefix = (business.get("invoice_prefix") or "INV").strip()
    sep = business.get("invoice_separator") or "/"
    digits = int(business.get("invoice_digits") or 3)
    stem = f"{prefix}{sep}{fy}{sep}"

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT invoice_no FROM invoices WHERE business_id=? AND invoice_no LIKE ?",
            (get_active_business_id(), stem + "%")
        ).fetchall()

    max_seq = 0
    for row in rows:
        try:
            max_seq = max(max_seq, int(row["invoice_no"].split(sep)[-1]))
        except (ValueError, IndexError):
            pass
    sequence_floor = max(1, int(business.get("invoice_sequence_start") or 1))
    next_seq = max(max_seq + 1, sequence_floor)
    return f"{stem}{str(next_seq).zfill(digits)}"


def format_import_invoice_number(raw_invoice_no, invoice_date, business):
    raw = str(raw_invoice_no or "").strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    if not raw.isdigit():
        return raw
    fy = financial_year(invoice_date)
    prefix = (business.get("invoice_prefix") or "INV").strip()
    sep = business.get("invoice_separator") or "/"
    digits = int(business.get("invoice_digits") or 3)
    return f"{prefix}{sep}{fy}{sep}{str(int(raw)).zfill(digits)}"


def build_invoice(invoice_date, client_id, place_state, place_code, business, raw_items,
                  notes="", invoice_no=None):
    if not business.get("state_code"):
        raise ValueError("Business State Code is not configured.")
    tax_type = "INTRA" if business["state_code"] == place_code else "INTER"
    items = [calculate_item(x, tax_type) for x in raw_items]
    totals = invoice_totals(items)

    invoice = {
        "invoice_no": invoice_no or next_invoice_number(invoice_date, business),
        "invoice_date": invoice_date.isoformat() if hasattr(invoice_date, "isoformat") else str(invoice_date),
        "client_id": client_id,
        "place_of_supply_state": place_state,
        "place_of_supply_code": place_code,
        "tax_type": tax_type,
        "subtotal": totals["gross_value"],
        "discount_total": totals["discount_amount"],
        "taxable_total": totals["taxable_value"],
        "cgst_total": totals["cgst_amount"],
        "sgst_total": totals["sgst_amount"],
        "igst_total": totals["igst_amount"],
        "grand_total": totals["line_total"],
        "amount_in_words": number_to_words_indian(totals["line_total"]),
        "notes": notes or ""
    }
    return invoice, items
