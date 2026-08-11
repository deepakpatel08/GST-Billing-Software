# Multi-Business Cloud Deployment — v1.2.0

1. Keep the existing PostgreSQL database and take a backup before deployment.
2. Replace the application source files with the v1.2.0 freeze release.
3. Do not run the old `migrate_sqlite_to_postgres.py` again if the PostgreSQL migration has already been completed.
4. Set `DATABASE_URL` in Streamlit Community Cloud Secrets.
5. Deploy from GitHub with `app.py` as the entry point.
6. On first startup, `init_db()` adds the v1.2.0 columns/tables without deleting existing records.
7. Verify the existing Business, Clients, Items, Invoices and Users before creating new businesses.
8. Verify Business Archive/Restore, User Business Access, Invoice Cancellation, Duplicate Invoice, Payment Tracking and Audit Log.

## GitHub exclusions

Never commit `data/`, `.venv/`, `.streamlit/secrets.toml`, database backups, exported client/invoice data, or PostgreSQL credentials.
