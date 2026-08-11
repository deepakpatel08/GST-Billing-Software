# GST Billing Utility v1.2.0 — Freeze Release

## Implemented before freeze

### Multi-business
- Separate business context for Clients, Item Master, Invoices and reports.
- Business selector in sidebar.
- Active Business + GSTIN displayed in top header.
- User-to-business access control.
- Administrator-controlled user-created businesses.
- Business creator can edit their own created business.
- Administrator can archive and restore businesses.

### Users
- Add User.
- Change Role.
- Business Access management.
- Reset Password.
- Activate/Deactivate.
- Permanent deletion with safeguards.

### Invoice controls
- Edit.
- Duplicate to a new invoice number.
- Cancel with mandatory reason.
- Cancelled invoice retention.
- Permanent deletion only after cancellation.
- Payment tracking and balance due.
- Cancelled invoices excluded from GST sales/report calculations.

### Item Master
- Business-specific Item Code.
- Automatic Item Code generation for new items when blank.
- Item Code shown in Item Master.
- Existing invoice-driven item creation retained.

### Audit
- Administrator-only Audit Log.
- Records key CREATE/UPDATE/CANCEL/DELETE/PAYMENT/ACTIVATE/DEACTIVATE actions.

### Cloud / Logo
- SQLite local mode retained.
- PostgreSQL cloud mode retained.
- Public Logo URL retained for cloud deployment.
- Local logo upload retained for desktop deployment.

## Important operational rule

Do not hard-delete an issued invoice. Cancel it with a reason. Permanent deletion is available only after cancellation and should be reserved for genuine cleanup/correction cases.

## Database upgrade

The v1.2.0 `init_db()` performs additive schema upgrades. Existing data is retained. Take a PostgreSQL backup before deploying the new code to a live database.

## Release status

**FROZEN — v1.2.0**
