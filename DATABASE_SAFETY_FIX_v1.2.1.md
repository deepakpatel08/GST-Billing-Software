# GST Billing Utility v1.2.1 - Database Safety Fix

## Purpose

This release fixes the data-reset behavior caused by the application silently falling
back from PostgreSQL to SQLite when `DATABASE_URL` was unavailable.

### New behavior

**Streamlit Cloud**
- `DATABASE_URL` present -> PostgreSQL
- `DATABASE_URL` missing -> application stops with a clear error
- PostgreSQL connection failure -> application stops
- It will NEVER silently use a temporary SQLite database in cloud mode.

**Local Windows**
- `DATABASE_URL` present -> PostgreSQL
- `DATABASE_URL` absent -> local SQLite (`data/gst_billing.db`)

The active business context also no longer silently defaults to Business ID 1.

## IMPORTANT: No database migration

Do NOT run:
- `migrate_sqlite_to_postgres.py`
- any import/migration script

Do NOT create a new PostgreSQL database.

Your existing PostgreSQL database remains the source of truth.

## Step 1 - Replace the file

Replace only:

    db.py

The supplied `db.py` is a complete replacement.

## Step 2 - Local test

From the project folder:

    streamlit run app.py

If you want to test the PostgreSQL backend locally, keep your existing `DATABASE_URL`
environment variable set.

If you want to test local SQLite, remove `DATABASE_URL` from the PowerShell session:

    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue

Then run:

    streamlit run app.py

## Step 3 - GitHub

Upload/replace:
    db.py
    .streamlit/secrets.toml.example

Do NOT upload:
- real `.streamlit/secrets.toml`
- PostgreSQL passwords
- data/
- .venv/
- database backups

## Step 4 - Streamlit Cloud Secrets

Open:

Streamlit Cloud -> Your App -> Settings -> Secrets

Use:

    DATABASE_URL = "YOUR EXISTING POSTGRESQL CONNECTION STRING"
    GST_BILLING_ENV = "cloud"

Do not send the actual connection string/password in chat.

## Step 5 - Restart / redeploy

Redeploy the app or use Reboot in Streamlit Cloud.

The application should connect to the existing PostgreSQL database.

## Step 6 - Verify before entering data

Confirm that:
- the database is PostgreSQL
- Jalaram Enterprises is visible
- existing Clients are visible
- existing Items are visible
- existing Invoices are visible
- Users are visible
- the active business is correct

Do NOT re-import the 49 invoices.

## If DATABASE_URL is wrong

The application will now stop and show an error instead of showing an empty database.

This is intentional and safer for GST data.
