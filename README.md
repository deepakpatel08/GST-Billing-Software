# GST Billing & Reporting Utility — v1.2.0 Freeze Release

Lightweight GST Billing & Reporting Utility built with Python, Streamlit and SQLite/PostgreSQL.

## v1.2.0 freeze features

- Multi-business support with business-wise Clients, Items and Invoices
- Business selector in the sidebar and prominent active Business/GSTIN header
- User access to one or multiple businesses
- Administrator-controlled User self-service Business creation
- Business creator can maintain the Business Setup for businesses created by that user
- Administrator can archive/restore Businesses; archived Businesses retain all data
- User activation/deactivation and protected permanent user deletion
- Invoice edit and duplicate/copy to a new invoice number
- Invoice cancellation with mandatory reason and audit trail
- Cancelled invoices are retained and excluded from GST sales/report totals
- Permanent invoice deletion allowed only after cancellation
- Invoice payment tracking: Unpaid / Partially Paid / Paid and balance due
- Item Master with business-specific Item Code; automatic ITM001/ITM002... codes for new items when code is blank
- Existing item selection and automatic Item Master creation/update from saved invoices
- Client-wise invoice filtering and invoice/client/GSTIN search
- Configurable default State, UQC, GST rate, invoice notes and report period
- Configurable invoice sequence start/floor for mid-year continuation
- Historical invoice import with validation and duplicate protection
- Public Logo URL support, including public Google Drive image links
- Local logo upload retained for desktop deployments
- PostgreSQL support through DATABASE_URL for Streamlit Cloud
- Administrator-only Audit Log for key business, user, client, item and invoice actions
- Success messages persist across Streamlit reruns
- Existing data remains backward compatible; database upgrades are additive

## Run locally

```text
pip install -r requirements.txt
streamlit run app.py
```

For PostgreSQL, set `DATABASE_URL` in the environment or Streamlit Secrets.
If `DATABASE_URL` is absent, the application uses `data/gst_billing.db`.

## Existing production data

Do NOT run the old SQLite-to-PostgreSQL migration again if the database has already been migrated.
The v1.2.0 database initialization adds the required fields/tables automatically.

Before upgrading a live database, take a PostgreSQL backup.

## Data and security

Do not commit:

- `data/`
- `gst_billing.db`
- `.venv/`
- `.streamlit/secrets.toml`
- PostgreSQL credentials or connection strings
- client/invoice exports or backups

For remote deployment, keep PostgreSQL credentials in Streamlit Secrets and do not expose Streamlit port 8501 directly to the Internet.

## Logo

Business Setup supports either:

1. Local logo upload; or
2. Public Logo URL.

For cloud deployment, a public Google Drive image link may be used for the business logo. Only use public URLs for non-confidential logo assets.

## GST reporting

Cancelled invoices are retained for audit purposes but are excluded from sales/GST reporting totals.

## Release status

**v1.2.0 — Freeze Release**

Further changes should be treated as a new version and tested separately rather than modifying this release in production.
