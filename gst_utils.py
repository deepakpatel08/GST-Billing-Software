import re
from decimal import Decimal, ROUND_HALF_UP
from datetime import date

GST_RATES = [0, 5, 12, 18, 28]

INDIA_STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab",
    "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana", "07": "Delhi",
    "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram",
    "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh",
    "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep",
    "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana",
    "37": "Andhra Pradesh", "38": "Ladakh", "97": "Other Territory",
    "99": "Centre Jurisdiction"
}
STATE_TO_CODE = {v: k for k, v in INDIA_STATES.items()}

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def validate_gstin(gstin, allow_blank=False):
    gstin = (gstin or "").strip().upper()
    if not gstin and allow_blank:
        return True, ""
    if len(gstin) != 15:
        return False, "GSTIN must contain exactly 15 characters."
    if not GSTIN_RE.match(gstin):
        return False, "GSTIN format is invalid."
    if gstin[:2] not in INDIA_STATES:
        return False, "GSTIN contains an invalid State Code."
    return True, ""


def validate_state_code(code):
    return str(code).zfill(2) in INDIA_STATES


def money(value):
    return float(Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def financial_year(dt):
    if isinstance(dt, str):
        y, m, d = map(int, dt.split("-"))
        dt = date(y, m, d)
    start = dt.year if dt.month >= 4 else dt.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def number_to_words_indian(number):
    number = int(round(float(number)))
    if number == 0:
        return "Zero Rupees Only"

    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
            "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
            "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def two(n):
        return ones[n] if n < 20 else tens[n // 10] + (" " + ones[n % 10] if n % 10 else "")

    def three(n):
        return (ones[n // 100] + " Hundred " if n >= 100 else "") + two(n % 100)

    parts = []
    crore, number = divmod(number, 10000000)
    lakh, number = divmod(number, 100000)
    thousand, number = divmod(number, 1000)
    hundred_rest = number

    if crore: parts.append(three(crore).strip() + " Crore")
    if lakh: parts.append(two(lakh).strip() + " Lakh")
    if thousand: parts.append(two(thousand).strip() + " Thousand")
    if hundred_rest: parts.append(three(hundred_rest).strip())
    return " ".join(parts) + " Rupees Only"


def calculate_item(item, tax_type):
    qty = money(item.get("quantity", 0))
    rate = money(item.get("rate", 0))
    discount_percent = money(item.get("discount_percent", 0))
    gst_rate = money(item.get("gst_rate", 0))

    gross = money(qty * rate)
    discount_amount = money(gross * discount_percent / 100)
    taxable = money(gross - discount_amount)

    if tax_type == "INTRA":
        cgst_rate = gst_rate / 2
        sgst_rate = gst_rate / 2
        igst_rate = 0
        cgst = money(taxable * cgst_rate / 100)
        sgst = money(taxable * sgst_rate / 100)
        igst = 0
    else:
        cgst_rate = sgst_rate = 0
        igst_rate = gst_rate
        cgst = sgst = 0
        igst = money(taxable * igst_rate / 100)

    return {
        **item,
        "quantity": qty, "rate": rate, "discount_percent": discount_percent,
        "gst_rate": gst_rate, "gross_value": gross, "discount_amount": discount_amount,
        "taxable_value": taxable, "cgst_rate": cgst_rate, "sgst_rate": sgst_rate,
        "igst_rate": igst_rate, "cgst_amount": cgst, "sgst_amount": sgst,
        "igst_amount": igst, "line_total": money(taxable + cgst + sgst + igst)
    }


def invoice_totals(items):
    keys = ["gross_value", "discount_amount", "taxable_value", "cgst_amount",
            "sgst_amount", "igst_amount", "line_total"]
    return {k: money(sum(float(i[k]) for i in items)) for k in keys}
