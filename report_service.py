from io import BytesIO
import pandas as pd
from db import report_rows


def build_reports(start_date, end_date):
    rows = report_rows(start_date, end_date)
    columns = ["invoice_id","invoice_no","invoice_date","place_of_supply_state","place_of_supply_code",
               "tax_type","invoice_value","client_name","receiver_gstin","description","hsn_sac",
               "quantity","unit","gst_rate","gross_value","taxable_value","cgst_amount","sgst_amount","igst_amount"]
    df = pd.DataFrame(rows, columns=columns)
    if df.empty:
        return df, pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # B2B: line/rate-wise detail, suitable for reconciliation and further portal-schema mapping.
    b2b = df[df["receiver_gstin"].fillna("").str.strip() != ""].copy()
    b2b = b2b.rename(columns={
        "receiver_gstin":"Receiver GSTIN", "client_name":"Receiver Name",
        "invoice_no":"Invoice No", "invoice_date":"Invoice Date",
        "invoice_value":"Invoice Value", "place_of_supply_state":"Place of Supply",
        "place_of_supply_code":"POS Code", "taxable_value":"Taxable Value",
        "gst_rate":"Rate", "cgst_amount":"CGST", "sgst_amount":"SGST", "igst_amount":"IGST"
    })
    b2b = b2b[["Receiver GSTIN","Receiver Name","Invoice No","Invoice Date","Invoice Value",
               "Place of Supply","POS Code","Taxable Value","Rate","CGST","SGST","IGST"]]

    # B2C: unregistered recipients aggregated state-wise and rate-wise.
    b2c = df[df["receiver_gstin"].fillna("").str.strip() == ""].copy()
    if not b2c.empty:
        b2c = b2c.groupby(["place_of_supply_state","place_of_supply_code","gst_rate"], as_index=False).agg(
            Taxable_Value=("taxable_value","sum"),
            CGST=("cgst_amount","sum"), SGST=("sgst_amount","sum"), IGST=("igst_amount","sum")
        )
        b2c = b2c.rename(columns={
            "place_of_supply_state":"Place of Supply", "place_of_supply_code":"POS Code",
            "gst_rate":"Rate", "Taxable_Value":"Taxable Value"
        })

    # HSN/SAC summary.
    hsn = df.groupby(["hsn_sac","description","unit"], as_index=False).agg(
        Total_Qty=("quantity","sum"), Total_Value=("gross_value","sum"),
        Taxable_Value=("taxable_value","sum"), CGST=("cgst_amount","sum"),
        SGST=("sgst_amount","sum"), IGST=("igst_amount","sum")
    )
    hsn = hsn.rename(columns={
        "hsn_sac":"HSN/SAC", "description":"Description", "unit":"UQC",
        "Total_Qty":"Total Qty", "Total_Value":"Total Value", "Taxable_Value":"Taxable Value"
    })
    return df, b2b, b2c, hsn


def excel_bytes(b2b, b2c, hsn):
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        b2b.to_excel(writer, sheet_name="B2B", index=False)
        b2c.to_excel(writer, sheet_name="B2C Summary", index=False)
        hsn.to_excel(writer, sheet_name="HSN Summary", index=False)
        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                max_len = max((len(str(c.value or "")) for c in col), default=10)
                ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 2, 10), 35)
    out.seek(0)
    return out.getvalue()
