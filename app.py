import html
import hashlib
import hmac
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from db import (
    init_db, get_business, save_business, list_clients, get_client, save_client,
    delete_client, insert_invoice, update_invoice, delete_invoice, get_invoice,
    list_invoices, list_items, get_item, save_item, delete_item, UPLOAD_DIR,
    find_client_for_import, invoice_number_exists, get_user_by_username,
    count_users, create_user, list_users, update_user_password, set_user_active,
    update_login_failure, reset_login_failure, update_user_role,
    list_businesses_for_user, create_business, get_user_business_access,
    set_user_business_access, set_active_business_id, get_active_business_id,
    get_application_setting, set_application_setting, allow_user_business_creation,
    archive_business, restore_business, list_all_businesses, list_audit_logs,
    cancel_invoice, update_invoice_payment, delete_user
)
from gst_utils import INDIA_STATES, STATE_TO_CODE, GST_RATES, validate_gstin
from invoice_service import build_invoice, next_invoice_number, format_import_invoice_number
from pdf_service import generate_invoice_pdf
from report_service import build_reports, excel_bytes

UQC_OPTIONS = ["NOS","PCS","KGS","MTR","LTR","BOX","SET","HRS","OTH"]
REPORT_PERIODS = ["Current Month","Current Quarter","Current Financial Year","Custom"]

APP_NAME = "GST Billing Utility"
APP_VERSION = "1.2.0"
COPYRIGHT_YEAR = "2026"

st.set_page_config(page_title="GST Billing Utility", page_icon="🧾", layout="wide")
init_db()


def is_valid_http_url(value):
    try:
        parsed = urlparse(str(value or '').strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def render_business_header(active_business):
    name = active_business.get("business_name") or "Business Not Configured"
    gstin = active_business.get("gstin") or "GSTIN not set"
    state = active_business.get("state") or ""
    state_code = active_business.get("state_code") or ""
    location = f"{state} ({state_code})" if state_code else state
    st.markdown(
        f"""
        <div style="padding: 4px 0 14px 0; margin-bottom: 8px;">
            <div style="font-size:30px;font-weight:700;line-height:1.15;color:#111827;">{html.escape(str(name))}</div>
            <div style="font-size:14px;color:#6B7280;margin-top:5px;">
                GSTIN: <strong>{html.escape(str(gstin))}</strong>
                &nbsp;&nbsp;•&nbsp;&nbsp; {html.escape(str(location))}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def hash_password(password, salt=None):
    """PBKDF2-SHA256 password hashing; passwords are never stored as plain text."""
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"pbkdf2_sha256$200000${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"),
            bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def password_is_valid(password):
    if len(password) < 10:
        return False, "Password must contain at least 10 characters."
    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter."
    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter."
    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one number."
    return True, ""


MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCK_MINUTES = 15
SESSION_TIMEOUT_HOURS = 8


def _parse_lock_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _login_lock_remaining(locked_until):
    lock_time = _parse_lock_time(locked_until)
    if not lock_time:
        return 0
    remaining = int((lock_time - datetime.now()).total_seconds())
    return max(0, remaining)


def _session_expired():
    last = st.session_state.get("last_activity_at")
    if not last:
        return False
    return (datetime.now() - last).total_seconds() > SESSION_TIMEOUT_HOURS * 3600


if "authenticated_user" not in st.session_state:
    st.session_state.authenticated_user = None
if "last_activity_at" not in st.session_state:
    st.session_state.last_activity_at = None
if "flash_message" not in st.session_state:
    st.session_state.flash_message = None
if "flash_type" not in st.session_state:
    st.session_state.flash_type = "success"


def set_flash(message, kind="success"):
    st.session_state.flash_message = str(message)
    st.session_state.flash_type = kind


def show_flash():
    message = st.session_state.pop("flash_message", None)
    kind = st.session_state.pop("flash_type", "success")
    if not message:
        return
    if kind == "error":
        st.error(message)
    elif kind == "warning":
        st.warning(message)
    elif kind == "info":
        st.info(message)
    else:
        st.success(message)

# First run: force creation of the first Admin account.
if count_users() == 0:
    st.title("GST Billing Utility - First Time Setup")
    st.info("Create the Administrator login. This is required only once on this database.")
    with st.form("first_admin_setup"):
        username = st.text_input("Administrator Username")
        password = st.text_input("Password", type="password")
        confirm = st.text_input("Confirm Password", type="password")
        submitted = st.form_submit_button("Create Administrator", type="primary")
        if submitted:
            valid, err = password_is_valid(password)
            if not username.strip():
                st.error("Username is required.")
            elif not valid:
                st.error(err)
            elif password != confirm:
                st.error("Passwords do not match.")
            else:
                try:
                    new_user_id = create_user(username.strip(), hash_password(password), "Admin")
                    set_user_business_access(new_user_id, [1])
                    st.success("Administrator created. Please sign in.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not create administrator: {e}")
    st.stop()

# Login gate.
if not st.session_state.authenticated_user:
    st.title("GST Billing Utility")
    st.caption("Sign in to continue.")
    with st.form("login_form"):
        username = st.text_input("Username", autocomplete="username")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        login = st.form_submit_button("Login", type="primary")
        if login:
            user = get_user_by_username(username)
            if not user or not user["active"]:
                st.error("Invalid username/password or inactive account.")
            else:
                remaining = _login_lock_remaining(user.get("locked_until", ""))
                if remaining > 0:
                    st.error(f"Account temporarily locked. Try again in {max(1, (remaining + 59) // 60)} minute(s).")
                elif verify_password(password, user["password_hash"]):
                    reset_login_failure(user["id"])
                    st.session_state.authenticated_user = {
                        "id": user["id"], "username": user["username"], "role": user["role"]
                    }
                    st.session_state.last_activity_at = datetime.now()
                    st.rerun()
                else:
                    failed = int(user.get("failed_login_count", 0)) + 1
                    if failed >= MAX_LOGIN_ATTEMPTS:
                        locked_until = datetime.now().replace(microsecond=0) + timedelta(minutes=LOGIN_LOCK_MINUTES)
                        update_login_failure(user["id"], 0, locked_until.isoformat())
                        st.error(f"Too many failed attempts. Account locked for {LOGIN_LOCK_MINUTES} minutes.")
                    else:
                        update_login_failure(user["id"], failed, "")
                        st.error(f"Invalid username/password. {MAX_LOGIN_ATTEMPTS - failed} attempt(s) remaining.")
    st.stop()

# Application session timeout. Cloudflare Access remains the outer authentication layer.
if _session_expired():
    st.session_state.authenticated_user = None
    st.session_state.last_activity_at = None
    st.warning("Your application session expired. Please sign in again.")
    st.rerun()

st.session_state.last_activity_at = datetime.now()

# ---------------------------------------------------------------------------
# Active business context
# ---------------------------------------------------------------------------
current_user = st.session_state.authenticated_user
available_businesses = list_businesses_for_user(
    current_user["id"], current_user.get("role", "User")
)

if not available_businesses:
    st.error("No business has been assigned to your user account. Please contact an Administrator.")
    st.stop()

available_ids = [int(x["id"]) for x in available_businesses]
active_business_id = st.session_state.get("active_business_id")
if active_business_id not in available_ids:
    set_active_business_id(available_ids[0])

st.markdown("""
<style>
.block-container {padding-top:1.2rem; padding-bottom:3.5rem; max-width:1500px;}
div[data-testid="stMetric"] {border:1px solid #e5e7eb; padding:12px; border-radius:10px;}
.invoice-preview {background:white;color:#111;border:1px solid #ddd;padding:22px;font-family:Arial,sans-serif;}
.invoice-preview table {width:100%;border-collapse:collapse;margin-top:12px;}
.invoice-preview th,.invoice-preview td {border:1px solid #aaa;padding:6px;font-size:12px;}
.invoice-preview th {background:#eee;}

.gst-footer {
    position: fixed;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 999;
    padding: 6px 12px;
    text-align: center;
    font-size: 11px;
    color: #6b7280;
    background: rgba(255,255,255,0.96);
    border-top: 1px solid #e5e7eb;
}
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="gst-footer">
    {APP_NAME} v{APP_VERSION} &nbsp;|&nbsp;
    Concept & Tax Domain: Deepak Patel, CA &nbsp;|&nbsp;
    Software Development Assistance: OpenAI's ChatGPT
    &nbsp;|&nbsp; © {COPYRIGHT_YEAR}
</div>
""", unsafe_allow_html=True)

if "page" not in st.session_state:
    st.session_state.page = "Dashboard"
if "draft_items" not in st.session_state:
    st.session_state.draft_items = []
if "editing_invoice_id" not in st.session_state:
    st.session_state.editing_invoice_id = None
if "edit_loaded_id" not in st.session_state:
    st.session_state.edit_loaded_id = None

def nav(page):
    st.session_state.page = page
    st.rerun()

with st.sidebar:
    st.title("GST Utility")
    st.caption(f'Signed in as: {st.session_state.authenticated_user["username"]}')
    if st.button("Logout", use_container_width=True):
        st.session_state.authenticated_user = None
        st.session_state.last_activity_at = None
        st.session_state.active_business_id = None
        st.rerun()

    business_labels = {
        int(x["id"]): f'{x["business_name"]} | {x["gstin"] or "GSTIN not set"}'
        for x in available_businesses
    }
    business_ids = list(business_labels.keys())
    selected_business_id = st.selectbox(
        "Active Business",
        business_ids,
        index=business_ids.index(get_active_business_id()) if get_active_business_id() in business_ids else 0,
        format_func=lambda x: business_labels[x],
        key="active_business_selector"
    )
    if selected_business_id != get_active_business_id():
        set_active_business_id(selected_business_id)
        st.session_state.editing_invoice_id = None
        st.session_state.edit_loaded_id = None
        st.session_state.draft_items = []
        st.session_state.last_invoice_id = None
        st.rerun()

    for label in ["Dashboard","New Invoice","Invoices","Import Invoices","Reports","Clients","Items","Business Setup","Users","Audit Log","About"]:
        if st.button(label, use_container_width=True,
                     type="primary" if st.session_state.page == label else "secondary"):
            if label == "New Invoice":
                st.session_state.editing_invoice_id = None
                st.session_state.edit_loaded_id = None
                st.session_state.draft_items = []
            nav(label)

business = get_business()
page = st.session_state.page
render_business_header(business)
show_flash()

def state_select(label, current=None, key=None, fallback=None):
    states = list(INDIA_STATES.values())
    chosen = current if current in states else (fallback if fallback in states else "Maharashtra")
    return st.selectbox(label, states, index=states.index(chosen), key=key)

def gstin_input(label, value="", key=None):
    return st.text_input(label, value=value or "", key=key).strip().upper()

def show_business_warning():
    if not business.get("business_name") or not business.get("state_code"):
        st.warning("Complete Business Setup before creating invoices.")
        return True
    return False

def start_edit_invoice(invoice_id):
    inv, items = get_invoice(invoice_id)
    st.session_state.editing_invoice_id = invoice_id
    st.session_state.edit_loaded_id = invoice_id
    st.session_state.draft_items = [{
        "description":x["description"], "hsn_sac":x["hsn_sac"], "quantity":x["quantity"],
        "unit":x["unit"], "rate":x["rate"], "discount_percent":x["discount_percent"],
        "gst_rate":x["gst_rate"]
    } for x in items]
    st.session_state.page = "New Invoice"
    st.rerun()

def render_create_business_form(current_user, form_key="new_business_form", heading="Add New Business"):
    st.subheader(heading)
    with st.form(form_key):
        nb_name=st.text_input("Business Name *",key=f"{form_key}_name")
        nb_gstin=gstin_input("GSTIN *",key=f"{form_key}_gstin")
        nb_address=st.text_area("Address *",key=f"{form_key}_address")
        nb_state=state_select("Business State *","Maharashtra",f"{form_key}_state")
        nb_state_code=STATE_TO_CODE[nb_state]

        a,b,c=st.columns(3)
        nb_account=a.text_input("Account No.",key=f"{form_key}_account")
        nb_ifsc=b.text_input("IFSC",key=f"{form_key}_ifsc")
        nb_branch=c.text_input("Branch",key=f"{form_key}_branch")

        a,b,c=st.columns(3)
        nb_prefix=a.text_input("Invoice Prefix","INV",key=f"{form_key}_prefix")
        nb_separator=b.text_input("Separator","/",max_chars=2,key=f"{form_key}_separator")
        nb_digits=c.number_input("Sequence Digits",2,8,3,key=f"{form_key}_digits")
        nb_sequence=st.number_input("Invoice Sequence Start",1,999999999,1,key=f"{form_key}_sequence")

        a,b,c=st.columns(3)
        nb_default_state=state_select("Default State","Maharashtra",f"{form_key}_default_state","Maharashtra")
        nb_default_unit=b.selectbox("Default UQC",UQC_OPTIONS,index=0,key=f"{form_key}_default_unit")
        nb_default_gst=c.selectbox("Default GST Rate %",GST_RATES,index=3,key=f"{form_key}_default_gst")
        nb_notes=st.text_area("Default Invoice Notes",key=f"{form_key}_notes")
        nb_period=st.selectbox("Default Report Period",REPORT_PERIODS,index=0,key=f"{form_key}_period")
        nb_logo=st.file_uploader("Upload Logo",type=["png","jpg","jpeg"],key=f"{form_key}_logo")
        nb_logo_url=st.text_input(
            "Public Logo URL",key=f"{form_key}_logo_url",
            help="Optional. Use a public HTTPS image URL, including a Google Drive shared image link."
        )

        if st.form_submit_button("Create Business",type="primary"):
            valid,err=validate_gstin(nb_gstin)
            if not nb_name.strip() or not nb_address.strip():
                st.error("Business Name and Address are required.")
                return
            if not valid:
                st.error(err)
                return
            if nb_logo_url.strip() and not is_valid_http_url(nb_logo_url):
                st.error("Public Logo URL must be a valid http:// or https:// URL.")
                return

            new_id=create_business({
                "business_name":nb_name.strip(),"gstin":nb_gstin,"address":nb_address.strip(),
                "state":nb_state,"state_code":nb_state_code,
                "account_no":nb_account.strip(),"ifsc":nb_ifsc.strip(),"branch":nb_branch.strip(),
                "logo_path":"","invoice_prefix":nb_prefix.strip() or "INV",
                "invoice_separator":nb_separator or "/","invoice_digits":int(nb_digits),
                "default_state":nb_default_state,"default_state_code":STATE_TO_CODE[nb_default_state],
                "default_unit":nb_default_unit,"default_gst_rate":nb_default_gst,
                "default_invoice_notes":nb_notes,"default_report_period":nb_period,
                "invoice_sequence_start":int(nb_sequence),
                "created_by_user_id":current_user["id"]
            })

            logo_path=nb_logo_url.strip()
            if nb_logo:
                path=UPLOAD_DIR/f"business_logo_{new_id}{Path(nb_logo.name).suffix.lower()}"
                path.write_bytes(nb_logo.getbuffer())
                logo_path=str(path)
            if logo_path:
                old_active=get_active_business_id()
                set_active_business_id(new_id)
                save_business({
                    "business_name":nb_name.strip(),"gstin":nb_gstin,"address":nb_address.strip(),
                    "state":nb_state,"state_code":nb_state_code,
                    "account_no":nb_account.strip(),"ifsc":nb_ifsc.strip(),"branch":nb_branch.strip(),
                    "logo_path":logo_path,"invoice_prefix":nb_prefix.strip() or "INV",
                    "invoice_separator":nb_separator or "/","invoice_digits":int(nb_digits),
                    "default_state":nb_default_state,"default_state_code":STATE_TO_CODE[nb_default_state],
                    "default_unit":nb_default_unit,"default_gst_rate":nb_default_gst,
                    "default_invoice_notes":nb_notes,"default_report_period":nb_period,
                    "invoice_sequence_start":int(nb_sequence)
                })
            add_access=get_user_business_access(current_user["id"])
            set_user_business_access(current_user["id"],[x["id"] for x in add_access]+[new_id])
            set_active_business_id(new_id)
            set_flash(f"Business '{nb_name.strip()}' created successfully and added to your Business Access.")
            st.rerun()


if page == "Dashboard":
    st.title("Dashboard")
    st.caption("Invoice generation, GST reporting and business-wise sales management.")
    c1,c2,c3 = st.columns(3)
    if c1.button("➕ New Invoice", use_container_width=True):
        st.session_state.editing_invoice_id=None; st.session_state.draft_items=[]; nav("New Invoice")
    if c2.button("📊 View Reports", use_container_width=True): nav("Reports")
    if c3.button("👤 Add Client", use_container_width=True): nav("Clients")

    today=date.today()
    fy_start=date(today.year if today.month>=4 else today.year-1,4,1)
    invoices=list_invoices(fy_start.isoformat(),today.isoformat())
    values=[
        sum(x["grand_total"] for x in invoices), sum(x["taxable_total"] for x in invoices),
        sum(x["cgst_total"] for x in invoices), sum(x["sgst_total"] for x in invoices),
        sum(x["igst_total"] for x in invoices)
    ]
    st.subheader("Current Financial Year")
    for col,label,val in zip(st.columns(5),["Total Sales","Taxable Value","CGST","SGST","IGST"],values):
        col.metric(label,f"₹ {val:,.2f}")
    st.subheader("Recent Invoices")
    recent=list_invoices()[:10]
    if recent:
        st.dataframe(pd.DataFrame([{"Invoice No":x["invoice_no"],"Date":x["invoice_date"],
            "Client":x["client_name"],"Taxable":x["taxable_total"],"Total":x["grand_total"]}
            for x in recent]),use_container_width=True,hide_index=True)
    else: st.info("No invoices created yet.")


elif page == "Users":
    st.title("User Management")
    current_user = st.session_state.authenticated_user
    if current_user.get("role") != "Admin":
        st.error("Only an Administrator can manage users.")
        st.stop()

    st.markdown("#### Business Creation Permission")
    current_setting = allow_user_business_creation()
    allow_creation = st.checkbox(
        "Allow Users to create their own Business",
        value=current_setting,
        help="When enabled, non-Administrator users can open Business Setup and create a new Business. They are automatically given access to the Business they create. They cannot edit existing Business profiles unless they are an Administrator."
    )
    if allow_creation != current_setting:
        set_application_setting("allow_user_business_creation", "1" if allow_creation else "0")
        set_flash("Business creation permission updated successfully.")
        st.rerun()

    users=list_users()
    all_businesses=list_businesses_for_user(current_user["id"],"Admin")
    business_name_map={int(x["id"]):x["business_name"] for x in all_businesses}

    if users:
        rows=[]
        for u in users:
            access=get_user_business_access(u["id"])
            names=", ".join(x["business_name"] for x in access) if access else ("All Businesses" if u["role"]=="Admin" else "None")
            rows.append({
                "Username":u["username"],"Role":u["role"],
                "Active":"Yes" if u["active"] else "No",
                "Businesses":names,"Created":u["created_at"]
            })
        st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)

    st.markdown("#### Add User")
    with st.form("add_user_form"):
        new_username=st.text_input("New Username")
        new_password=st.text_input("New Password",type="password")
        new_confirm=st.text_input("Confirm New Password",type="password")
        new_role=st.selectbox("Role",["User","Admin"],index=0)
        business_options={int(x["id"]):x["business_name"] for x in all_businesses}
        selected_business_ids=st.multiselect(
            "Business Access",
            options=list(business_options.keys()),
            format_func=lambda x:business_options[x],
            default=list(business_options.keys()) if new_role=="Admin" else []
        )
        st.caption("Administrators can access all businesses. For a User, select one or more businesses.")
        if st.form_submit_button("Create User",type="primary"):
            valid,err=password_is_valid(new_password)
            if not new_username.strip(): st.error("Username is required.")
            elif not valid: st.error(err)
            elif new_password!=new_confirm: st.error("Passwords do not match.")
            elif new_role=="User" and not selected_business_ids: st.error("Select at least one business for a User.")
            else:
                try:
                    user_id=create_user(new_username.strip(),hash_password(new_password),new_role)
                    set_user_business_access(user_id,selected_business_ids if new_role=="User" else list(business_options.keys()))
                    set_flash(f"User '{new_username.strip()}' created successfully.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not create user. That username may already exist. {e}")

    if users:
        st.markdown("#### Manage User")
        user_map={u["username"]:u for u in users}
        selected_username=st.selectbox("User",list(user_map.keys()),key="manage_user_select")
        selected_user=user_map[selected_username]
        current_access=get_user_business_access(selected_user["id"])
        current_access_ids=[int(x["id"]) for x in current_access]
        selected_role=st.selectbox(
            "Role",
            ["User","Admin"],
            index=0 if selected_user["role"]!="Admin" else 1,
            key=f"role_{selected_user['id']}"
        )
        selected_access=st.multiselect(
            "Business Access",
            options=list(business_name_map.keys()),
            default=current_access_ids if selected_user["role"]!="Admin" else list(business_name_map.keys()),
            format_func=lambda x:business_name_map[x],
            key=f"access_{selected_user['id']}"
        )
        new_pw=st.text_input("Replacement Password",type="password",key="reset_pw")
        c1,c2,c3,c4=st.columns(4)
        if c1.button("Save Access / Role",use_container_width=True):
            if selected_role=="User" and not selected_access:
                st.error("A User must have at least one business.")
            else:
                update_user_role(selected_user["id"],selected_role)
                set_user_business_access(
                    selected_user["id"],
                    selected_access if selected_role=="User" else list(business_name_map.keys())
                )
                if selected_user["id"]==current_user["id"] and selected_role!="Admin":
                    allowed=[x["id"] for x in get_user_business_access(selected_user["id"])]
                    if get_active_business_id() not in allowed and allowed:
                        set_active_business_id(allowed[0])
                set_flash(f"User access for '{selected_user['username']}' updated successfully.")
                st.rerun()

        if c2.button("Reset Password",use_container_width=True):
            valid,err=password_is_valid(new_pw)
            if not valid: st.error(err)
            else:
                update_user_password(selected_user["id"],hash_password(new_pw))
                st.success("Password reset successfully.")

        if c3.button("Activate User",use_container_width=True):
            set_user_active(selected_user["id"],True); set_flash("User activated successfully."); st.rerun()

        if c4.button("Deactivate User",use_container_width=True):
            if selected_user["id"]==current_user["id"]:
                st.error("You cannot deactivate the account currently signed in.")
            else:
                set_user_active(selected_user["id"],False); set_flash("User deactivated successfully."); st.rerun()

        st.markdown("#### Permanent User Deletion")
        st.warning("Deletion is permanent. If the user has created a Business, the account must be deactivated instead.")
        if st.button("Delete Selected User",type="secondary",key="delete_selected_user"):
            if selected_user["id"]==current_user["id"]:
                st.error("You cannot delete the account currently signed in.")
            else:
                st.session_state.confirm_delete_user_id=selected_user["id"]
        if st.session_state.get("confirm_delete_user_id")==selected_user["id"]:
            st.warning(f"Permanently delete user '{selected_user['username']}'?")
            y,n=st.columns([1,5])
            if y.button("Yes, Delete User",type="primary"):
                try:
                    delete_user(selected_user["id"])
                    st.session_state.confirm_delete_user_id=None
                    set_flash(f"User '{selected_user['username']}' deleted successfully.")
                    st.rerun()
                except ValueError as e:
                    st.session_state.confirm_delete_user_id=None
                    st.error(str(e))
            if n.button("Cancel",key="cancel_delete_user"):
                st.session_state.confirm_delete_user_id=None; st.rerun()

elif page == "Audit Log":
    st.title("Audit Log")
    if current_user.get("role") != "Admin":
        st.warning("Audit Log is restricted to Administrators.")
        st.stop()
    logs=list_audit_logs(500)
    if not logs:
        st.info("No audit activity has been recorded yet.")
    else:
        df=pd.DataFrame([{
            "Date/Time":x["created_at"],"User":x["username"],"Business":x["business_name"],
            "Action":x["action"],"Entity":x["entity_type"],"Reference":x["reference"],"Details":x["details"]
        } for x in logs])
        st.dataframe(df,use_container_width=True,hide_index=True)

elif page == "About":
    st.title("About GST Billing Utility")
    st.caption(f"{APP_NAME} • Version {APP_VERSION}")

    st.markdown("""
    <div style="
        border:1px solid #e5e7eb;
        border-radius:14px;
        padding:28px;
        background:#ffffff;
        margin-top:10px;
    ">
        <h2 style="margin-top:0;">GST Billing Utility</h2>
        <p style="font-size:16px;">
            Lightweight GST Billing & Reporting Software for local business use.
        </p>

        <hr>

        <h4>Concept, Tax Domain & Product Direction</h4>
        <p>
            <strong>Deepak Patel, Chartered Accountant</strong>
        </p>

        <h4>Software Development Assistance</h4>
        <p>
            Developed with assistance from <strong>OpenAI's ChatGPT</strong>.
        </p>

        <h4>Technology</h4>
        <p>
            Python • Streamlit • SQLite / PostgreSQL • Pandas • ReportLab • OpenPyXL
        </p>

        <h4>Copyright</h4>
        <p>
            © 2026. All rights reserved.
        </p>

        <p style="font-size:12px;color:#666;margin-bottom:0;">
            Third-party components remain subject to their respective licences.
            See <strong>THIRD_PARTY_LICENSES.txt</strong> supplied with the software.
        </p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""### Security

This application is designed for secure local or controlled remote deployment. For remote access, keep the application bound to localhost and place Cloudflare Access and Cloudflare Tunnel in front of it. Never expose Streamlit port 8501 directly to the Internet.""")

    st.markdown("### About the Software")
    st.write(
        "This utility is designed to simplify GST invoice creation, historical invoice "
        "migration, client and item master management, PDF generation and GST-oriented "
        "sales reporting while keeping business data stored locally."
    )

elif page == "Business Setup":
     st.title("Business Setup")
     current_user = st.session_state.authenticated_user
     is_admin = current_user.get("role") == "Admin"
     user_can_create_business = is_admin or allow_user_business_creation()
     is_business_owner = (business.get("created_by_user_id") == current_user.get("id"))
     can_edit_active_business = is_admin or is_business_owner

     if not is_admin and not user_can_create_business and not is_business_owner:
         st.info("Business Setup is restricted to Administrators. Your Administrator has not enabled self-service Business creation for Users.")
         st.stop()

     if not can_edit_active_business:
         st.info("You have access to this Business, but only an Administrator or the Business creator can edit its Business Setup.")
         if user_can_create_business:
             render_create_business_form(current_user, "user_business_form", "Create My Business")
         st.stop()

     if not is_admin:
         st.info("You are editing the Business created by your user account. You may create additional Businesses while the Administrator has enabled self-service Business creation.")

     active_business = business
     st.caption(f'Editing: {active_business.get("business_name","Unnamed Business")}')

     with st.form("business_form"):
         name=st.text_input("Business Name *",active_business.get("business_name",""))
         gstin=gstin_input("GSTIN *",active_business.get("gstin",""))
         address=st.text_area("Address *",active_business.get("address",""))
         state=state_select("Business State *",active_business.get("state"),"business_state")
         state_code=STATE_TO_CODE[state]

         st.markdown("#### Bank Details")
         a,b,c=st.columns(3)
         account_no=a.text_input("Account No.",active_business.get("account_no",""))
         ifsc=b.text_input("IFSC",active_business.get("ifsc","")).upper()
         branch=c.text_input("Branch",active_business.get("branch",""))

         st.markdown("#### Invoice Numbering")
         a,b,c=st.columns(3)
         prefix=a.text_input("Prefix",active_business.get("invoice_prefix","INV"))
         separator=b.text_input("Separator",active_business.get("invoice_separator","/"),max_chars=2)
         digits=c.number_input("Sequence Digits",2,8,int(active_business.get("invoice_digits",3)))
         sequence_start=st.number_input("Invoice Sequence Start / Minimum Next Sequence",min_value=1,value=int(active_business.get("invoice_sequence_start",1) or 1),step=1,help="Example: enter 795 to continue at 795.")

         st.markdown("#### Application Defaults")
         a,b,c=st.columns(3)
         default_state=state_select("Default State",active_business.get("default_state"),"default_state","Maharashtra")
         default_unit=b.selectbox("Default UQC",UQC_OPTIONS,index=UQC_OPTIONS.index(active_business.get("default_unit","NOS")) if active_business.get("default_unit","NOS") in UQC_OPTIONS else 0)
         default_gst=float(active_business.get("default_gst_rate",18))
         default_gst_rate=c.selectbox("Default GST Rate %",GST_RATES,index=GST_RATES.index(int(default_gst)) if int(default_gst) in GST_RATES else 3)
         default_notes=st.text_area("Default Invoice Notes",active_business.get("default_invoice_notes",""))
         default_period=st.selectbox("Default Report Period",REPORT_PERIODS,index=REPORT_PERIODS.index(active_business.get("default_report_period","Current Month")) if active_business.get("default_report_period","Current Month") in REPORT_PERIODS else 0)

         logo=st.file_uploader("Upload Logo",type=["png","jpg","jpeg"],help="Optional. Stored locally for desktop use.")
         logo_url=st.text_input("Public Logo URL",value=(active_business.get("logo_path","") if str(active_business.get("logo_path","")).startswith(("http://","https://")) else ""),help="Optional. Use a public HTTPS image URL, including a Google Drive shared image link.")
         if st.form_submit_button("Save Business Profile",type="primary"):
             valid,err=validate_gstin(gstin)
             if not name.strip() or not address.strip():
                 st.error("Business Name and Address are required.")
             elif not valid:
                 st.error(err)
             else:
                 logo_path=active_business.get("logo_path","")
                 if logo_url.strip():
                     if not is_valid_http_url(logo_url):
                         st.error("Public Logo URL must be a valid http:// or https:// URL.")
                         st.stop()
                     logo_path=logo_url.strip()
                 elif logo:
                     path=UPLOAD_DIR/f"business_logo_{get_active_business_id()}{Path(logo.name).suffix.lower()}"
                     path.write_bytes(logo.getbuffer())
                     logo_path=str(path)
                 save_business({
                     "business_name":name.strip(),"gstin":gstin,"address":address.strip(),"state":state,"state_code":state_code,
                     "account_no":account_no.strip(),"ifsc":ifsc.strip(),"branch":branch.strip(),"logo_path":logo_path,
                     "invoice_prefix":prefix.strip() or "INV","invoice_separator":separator or "/","invoice_digits":int(digits),
                     "default_state":default_state,"default_state_code":STATE_TO_CODE[default_state],"default_unit":default_unit,
                     "default_gst_rate":default_gst_rate,"default_invoice_notes":default_notes,"default_report_period":default_period,
                     "invoice_sequence_start":int(sequence_start)
                 })
                 set_flash(f"Business profile for '{name.strip()}' saved successfully.")
                 st.rerun()

     st.markdown("---")
     with st.expander("➕ Create Another Business",expanded=False):
         render_create_business_form(current_user,"admin_business_form","Create Another Business")

elif page == "Clients":
    st.title("Client Master")
    clients=list_clients()
    client_map={"New Client":None}
    client_map.update({f'{c["name"]} | {c["gstin"] or "Unregistered"}':c["id"] for c in clients})
    selected=st.selectbox("Select Client to Edit",list(client_map.keys()))
    client_id=client_map[selected]
    client=get_client(client_id) if client_id else {}
    default_state=business.get("default_state") or "Maharashtra"

    with st.form("client_form"):
        name=st.text_input("Client Name *",client.get("name",""))
        gstin=gstin_input("GSTIN (blank for unregistered/B2C)",client.get("gstin",""))
        address=st.text_area("Address",client.get("address",""))
        state=state_select("State *",client.get("state"),"client_state",default_state)
        state_code=STATE_TO_CODE[state]
        if st.form_submit_button("Save Client",type="primary"):
            valid,err=validate_gstin(gstin,allow_blank=True)
            if not name.strip(): st.error("Client Name is required.")
            elif not valid: st.error(err)
            elif gstin and gstin[:2]!=state_code: st.error("Client State does not match the State Code embedded in GSTIN.")
            else:
                save_client({"name":name.strip(),"gstin":gstin,"address":address.strip(),
                             "state":state,"state_code":state_code},client_id)
                set_flash("Client saved successfully."); st.rerun()
    if client_id and st.button("Delete Client"):
        try: delete_client(client_id); set_flash("Client deleted successfully."); st.rerun()
        except ValueError as e: st.error(str(e))
    if clients:
        st.dataframe(pd.DataFrame([{"Name":c["name"],"GSTIN":c["gstin"],"State":c["state"],
            "State Code":c["state_code"]} for c in clients]),use_container_width=True,hide_index=True)

elif page == "Items":
    st.title("Item Master")
    st.caption("Items are also created/updated automatically when an invoice is saved.")
    items=list_items()
    item_map={"New Item":None}
    item_map.update({f'{x["description"]} | {x["hsn_sac"]}':x["id"] for x in items})
    selected=st.selectbox("Select Item to Edit",list(item_map.keys()))
    item_id=item_map[selected]
    item=get_item(item_id) if item_id else {}
    with st.form("item_master_form"):
        a0,b0=st.columns([1,3])
        item_code=a0.text_input("Item Code",item.get("item_code", ""),help="Unique within the active Business. If left blank for a new Item, ITM001/ITM002... is generated automatically.")
        description=b0.text_input("Description *",item.get("description",""))
        hsn=st.text_input("HSN / SAC *",item.get("hsn_sac",""))
        a,b,c=st.columns(3)
        unit=a.selectbox("UQC",UQC_OPTIONS,index=UQC_OPTIONS.index(item.get("unit",business.get("default_unit","NOS")))
            if item.get("unit",business.get("default_unit","NOS")) in UQC_OPTIONS else 0)
        rate=b.number_input("Default Rate",min_value=0.0,value=float(item.get("default_rate",0)),step=100.0)
        gst_val=int(float(item.get("gst_rate",business.get("default_gst_rate",18))))
        gst_rate=c.selectbox("GST Rate %",GST_RATES,index=GST_RATES.index(gst_val) if gst_val in GST_RATES else 3)
        active=st.checkbox("Active",value=bool(item.get("active",1)))
        if st.form_submit_button("Save Item",type="primary"):
            if not description.strip() or not hsn.strip(): st.error("Description and HSN/SAC are required.")
            else:
                try:
                    save_item({"item_code":item_code.strip(),"description":description.strip(),"hsn_sac":hsn.strip(),"unit":unit,
                        "default_rate":rate,"gst_rate":gst_rate,"active":active},item_id)
                    set_flash("Item saved successfully."); st.rerun()
                except Exception as e:
                    st.error(f"Could not save item. Item Code or Description may already exist in this Business. {e}")
    if item_id and st.button("Delete Item"):
        delete_item(item_id); set_flash("Item deleted successfully."); st.rerun()
    if items:
        st.dataframe(pd.DataFrame([{"Item Code":x.get("item_code", ""),"Description":x["description"],"HSN/SAC":x["hsn_sac"],
            "UQC":x["unit"],"Default Rate":x["default_rate"],"GST %":x["gst_rate"],
            "Active":"Yes" if x["active"] else "No"} for x in items]),use_container_width=True,hide_index=True)

elif page == "New Invoice":
    editing_id=st.session_state.editing_invoice_id
    existing_inv, existing_items=(get_invoice(editing_id) if editing_id else (None,[]))
    st.title("Edit Invoice" if editing_id else "New Invoice")
    if editing_id:
        st.info(f'Editing {existing_inv["invoice_no"]}. The invoice number will remain unchanged.')
    if show_business_warning():
        if st.button("Open Business Setup"): nav("Business Setup")
        st.stop()

    clients=list_clients()
    if not clients:
        st.warning("Add at least one client first.")
        if st.button("Open Client Master"): nav("Clients")
        st.stop()

    a,b,c=st.columns([1,1,2])
    initial_date=datetime.strptime(existing_inv["invoice_date"],"%Y-%m-%d").date() if existing_inv else date.today()
    inv_date=a.date_input("Invoice Date",value=initial_date,key=f"invoice_date_{editing_id or 'new'}")
    invoice_no=existing_inv["invoice_no"] if existing_inv else next_invoice_number(inv_date,business)
    b.text_input("Invoice No.",invoice_no,disabled=True)

    client_labels={f'{x["name"]} | {x["gstin"] or "Unregistered"}':x for x in clients}
    labels=["— Select Client —"]+list(client_labels.keys())
    default_client_index=0
    duplicate_client_id=st.session_state.get("duplicate_client_id")
    if duplicate_client_id and not existing_inv:
        for i,label in enumerate(labels):
            if i and client_labels[label]["id"]==duplicate_client_id:
                default_client_index=i; break
    if existing_inv:
        for i,label in enumerate(labels):
            if i and client_labels[label]["id"]==existing_inv["client_id"]:
                default_client_index=i; break
    client_label=c.selectbox("Client *",labels,index=default_client_index,key=f"invoice_client_{editing_id or 'new'}")
    client=client_labels.get(client_label)

    if not client:
        st.info("Select a client to continue with Place of Supply and invoice items.")
        st.stop()

    pos_default=existing_inv["place_of_supply_state"] if existing_inv else st.session_state.get("duplicate_pos_state",client["state"])
    a,b=st.columns(2)
    states=list(INDIA_STATES.values())
    pos_state=a.selectbox("Place of Supply *",states,index=states.index(pos_default) if pos_default in states else states.index(business.get("default_state","Maharashtra")),
                          key=f"pos_{editing_id or 'new'}")
    pos_code=STATE_TO_CODE[pos_state]
    tax_type="INTRA" if business["state_code"]==pos_code else "INTER"
    b.info(f"Tax Type: {'CGST + SGST' if tax_type=='INTRA' else 'IGST'}")

    st.markdown("### Add Line Item")
    master_items=list_items(active_only=True)
    master_labels=["— New Item —"]+[x["description"] for x in master_items]
    selected_master=st.selectbox("Choose existing item or create new",master_labels,key=f"master_pick_{editing_id or 'new'}")
    master=next((x for x in master_items if x["description"]==selected_master),None)

    # Selection is intentionally outside the form so choosing a master reruns and pre-fills defaults.
    with st.form(f"item_form_{editing_id or 'new'}",clear_on_submit=True):
        c1,c2=st.columns([3,1])
        description=c1.text_input("Item / Service Description *",value=master["description"] if master else "")
        hsn=c2.text_input("HSN / SAC *",value=master["hsn_sac"] if master else "")
        c1,c2,c3,c4,c5=st.columns(5)
        qty=c1.number_input("Quantity",min_value=0.001,value=1.0,step=1.0)
        default_unit=master["unit"] if master else business.get("default_unit","NOS")
        unit=c2.selectbox("Unit / UQC",UQC_OPTIONS,index=UQC_OPTIONS.index(default_unit) if default_unit in UQC_OPTIONS else 0)
        rate=c3.number_input("Rate",min_value=0.0,value=float(master["default_rate"]) if master else 0.0,step=100.0)
        discount=c4.number_input("Discount %",0.0,100.0,0.0)
        default_gst=int(float(master["gst_rate"])) if master else int(float(business.get("default_gst_rate",18)))
        gst_rate=c5.selectbox("GST Rate %",GST_RATES,index=GST_RATES.index(default_gst) if default_gst in GST_RATES else 3)
        if st.form_submit_button("Add Item",type="primary"):
            if not description.strip() or not hsn.strip(): st.error("Description and HSN/SAC are required.")
            elif rate<=0: st.error("Rate must be greater than zero.")
            else:
                st.session_state.draft_items.append({"description":description.strip(),"hsn_sac":hsn.strip(),
                    "quantity":qty,"unit":unit,"rate":rate,"discount_percent":discount,"gst_rate":gst_rate})
                st.rerun()

    if st.session_state.draft_items:
        preview_invoice,preview_items=build_invoice(inv_date,client["id"],pos_state,pos_code,business,
            st.session_state.draft_items,invoice_no=invoice_no)
        st.dataframe(pd.DataFrame([{"#":i+1,"Description":x["description"],"HSN/SAC":x["hsn_sac"],
            "Qty":x["quantity"],"Unit":x["unit"],"Rate":x["rate"],"Disc %":x["discount_percent"],
            "Taxable":x["taxable_value"],"GST %":x["gst_rate"],"CGST":x["cgst_amount"],
            "SGST":x["sgst_amount"],"IGST":x["igst_amount"],"Total":x["line_total"]}
            for i,x in enumerate(preview_items)]),use_container_width=True,hide_index=True)

        remove_options=["None"]+[f'{i+1}. {x["description"]}' for i,x in enumerate(st.session_state.draft_items)]
        remove_idx=st.selectbox("Remove Item",remove_options)
        if remove_idx!="None" and st.button("Remove Selected Item"):
            st.session_state.draft_items.pop(int(remove_idx.split(".")[0])-1); st.rerun()

        for col,label,key in zip(st.columns(5),["Taxable","CGST","SGST","IGST","Grand Total"],
            ["taxable_total","cgst_total","sgst_total","igst_total","grand_total"]):
            col.metric(label,f'₹ {preview_invoice[key]:,.2f}')

        notes_default=existing_inv["notes"] if existing_inv else business.get("default_invoice_notes","")
        notes=st.text_area("Invoice Notes",value=notes_default,key=f"notes_{editing_id or 'new'}")
        c1,c2,c3=st.columns([1,1,3])
        if c1.button("Update Invoice" if editing_id else "Save Invoice",type="primary",use_container_width=True):
            invoice,calc_items=build_invoice(inv_date,client["id"],pos_state,pos_code,business,
                st.session_state.draft_items,notes,invoice_no=invoice_no)
            if editing_id:
                invoice_id=update_invoice(editing_id,invoice,calc_items)
                message=f'Invoice {invoice_no} updated.'
            else:
                invoice_id=insert_invoice(invoice,calc_items)
                message=f'Invoice {invoice_no} saved.'
            st.session_state.draft_items=[]; st.session_state.editing_invoice_id=None
            st.session_state.edit_loaded_id=None; st.session_state.last_invoice_id=invoice_id
            st.session_state.duplicate_client_id=None; st.session_state.duplicate_pos_state=None
            st.success(message); nav("Invoices")
        if c2.button("Cancel Edit" if editing_id else "Clear Draft"):
            st.session_state.draft_items=[]; st.session_state.editing_invoice_id=None; st.session_state.edit_loaded_id=None
            nav("Invoices" if editing_id else "New Invoice")
    else:
        st.info("Add at least one line item.")

elif page == "Invoices":
    st.title("Invoices")
    clients=list_clients()
    st.markdown("#### Search & Filter")
    a,b,c=st.columns([2,2,2])
    search=a.text_input("Invoice No. / Client / GSTIN")
    client_filter_labels=["All Clients"]+[x["name"] for x in clients]
    selected_client=b.selectbox("Client",client_filter_labels)
    client_id=None if selected_client=="All Clients" else next(x["id"] for x in clients if x["name"]==selected_client)
    use_dates=c.checkbox("Filter by Date")
    start=end=None
    if use_dates:
        d1,d2=st.columns(2)
        start=d1.date_input("From Date",date.today().replace(day=1)).isoformat()
        end=d2.date_input("To Date",date.today()).isoformat()

    invoices=list_invoices(start,end,client_id,search,include_cancelled=True)
    if not invoices:
        st.info("No invoices found for the selected filters."); st.stop()

    st.caption(f"{len(invoices)} invoice(s) found")
    labels={f'{x["invoice_no"]} | {x["invoice_date"]} | {x["client_name"]} | ₹{x["grand_total"]:,.2f} | {x.get("status","ACTIVE")}':x["id"] for x in invoices}
    default_index=0
    if st.session_state.get("last_invoice_id") in list(labels.values()):
        default_index=list(labels.values()).index(st.session_state.last_invoice_id)
    selected=st.selectbox("Select Invoice",list(labels.keys()),index=default_index)
    invoice_id=labels[selected]
    invoice,items=get_invoice(invoice_id)

    action1,action2,action3,action4,action5=st.columns(5)
    if action1.button("✏️ Edit",use_container_width=True,disabled=invoice.get("status")=="CANCELLED"):
        start_edit_invoice(invoice_id)
    if action2.button("📄 Duplicate",use_container_width=True,disabled=invoice.get("status")=="CANCELLED"):
        st.session_state.editing_invoice_id=None; st.session_state.edit_loaded_id=None
        st.session_state.draft_items=[{"description":x["description"],"hsn_sac":x["hsn_sac"],"quantity":x["quantity"],"unit":x["unit"],"rate":x["rate"],"discount_percent":x["discount_percent"],"gst_rate":x["gst_rate"]} for x in items]
        st.session_state.duplicate_client_id=invoice["client_id"]; st.session_state.duplicate_pos_state=invoice["place_of_supply_state"]; st.session_state.page="New Invoice"; st.rerun()
    if action3.button("❌ Cancel Invoice",use_container_width=True,disabled=invoice.get("status")=="CANCELLED"):
        st.session_state.confirm_cancel_invoice=invoice_id
    if action4.button("💰 Payment",use_container_width=True,disabled=invoice.get("status")=="CANCELLED"):
        st.session_state.show_payment_invoice=invoice_id
    if action5.button("🗑️ Delete",use_container_width=True):
        st.session_state.confirm_delete_invoice=invoice_id
    if st.session_state.get("confirm_cancel_invoice")==invoice_id:
        reason=st.text_input("Cancellation Reason *",key=f"cancel_reason_{invoice_id}")
        y,n=st.columns([1,5])
        if y.button("Confirm Cancellation",type="primary"):
            try:
                no=cancel_invoice(invoice_id,reason); st.session_state.confirm_cancel_invoice=None; set_flash(f"Invoice {no} cancelled successfully."); st.rerun()
            except ValueError as e: st.error(str(e))
        if n.button("Cancel",key=f"cancel_cancel_{invoice_id}"): st.session_state.confirm_cancel_invoice=None; st.rerun()
    if st.session_state.get("show_payment_invoice")==invoice_id:
        amount=st.number_input("Amount Received",min_value=0.0,max_value=float(invoice["grand_total"]),value=float(invoice.get("amount_received",0) or 0),step=100.0,key=f"payment_amount_{invoice_id}")
        y,n=st.columns([1,5])
        if y.button("Save Payment",type="primary"):
            status,balance=update_invoice_payment(invoice_id,amount); st.session_state.show_payment_invoice=None; set_flash(f"Payment updated: {status}. Balance ₹{balance:,.2f}."); st.rerun()
        if n.button("Cancel",key=f"cancel_payment_{invoice_id}"): st.session_state.show_payment_invoice=None; st.rerun()
    if st.session_state.get("confirm_delete_invoice")==invoice_id:
        if invoice.get("status")!="CANCELLED": st.warning("Invoice must be cancelled before permanent deletion.")
        else: st.warning(f'Permanently delete cancelled invoice {invoice["invoice_no"]}? This cannot be undone.')
        y,n=st.columns([1,5])
        if y.button("Yes, Delete",type="primary",disabled=invoice.get("status")!="CANCELLED"):
            try:
                deleted_no=delete_invoice(invoice_id); st.session_state.confirm_delete_invoice=None; st.session_state.last_invoice_id=None; set_flash(f"{deleted_no} deleted successfully."); st.rerun()
            except ValueError as e: st.error(str(e))
        if n.button("Cancel",key=f"cancel_delete_{invoice_id}"): st.session_state.confirm_delete_invoice=None; st.rerun()

    status_label=invoice.get("status","ACTIVE")
    if status_label=="CANCELLED": st.error(f"Status: CANCELLED — {invoice.get('cancellation_reason','')}")
    else: st.success(f"Status: {status_label} | Payment: {invoice.get('payment_status','Unpaid')} | Balance: ₹{float(invoice.get('balance_due',invoice['grand_total'])):,.2f}")

    st.subheader(invoice["invoice_no"])
    for col,label,key in zip(st.columns(5),["Invoice Value","Taxable","CGST","SGST","IGST"],
        ["grand_total","taxable_total","cgst_total","sgst_total","igst_total"]):
        col.metric(label,f'₹ {invoice[key]:,.2f}')
    st.dataframe(pd.DataFrame([{"Description":x["description"],"HSN/SAC":x["hsn_sac"],
        "Qty":x["quantity"],"Unit":x["unit"],"Rate":x["rate"],"Taxable":x["taxable_value"],
        "GST %":x["gst_rate"],"CGST":x["cgst_amount"],"SGST":x["sgst_amount"],
        "IGST":x["igst_amount"],"Total":x["line_total"]} for x in items]),
        use_container_width=True,hide_index=True)

    pdf_path=generate_invoice_pdf(invoice,items,business)
    with open(pdf_path,"rb") as f:
        st.download_button("Download PDF Invoice",f.read(),file_name=pdf_path.name,mime="application/pdf")

    rows_html="".join(f"<tr><td>{html.escape(x['description'])}</td><td>{html.escape(x['hsn_sac'])}</td>"
        f"<td>{x['quantity']:.2f}</td><td>{html.escape(x['unit'])}</td><td>{x['rate']:.2f}</td>"
        f"<td>{x['taxable_value']:.2f}</td><td>{x['gst_rate']:.2f}%</td>"
        f"<td>{x['cgst_amount']+x['sgst_amount']+x['igst_amount']:.2f}</td><td>{x['line_total']:.2f}</td></tr>"
        for x in items)
    preview=f"""<div class="invoice-preview"><h2 style="text-align:center">TAX INVOICE</h2>
    <h3>{html.escape(business['business_name'])}</h3><div>{html.escape(business['address'])}<br>
    GSTIN: {html.escape(business['gstin'])}</div><hr><b>Invoice:</b> {html.escape(invoice['invoice_no'])}
    &nbsp; <b>Date:</b> {invoice['invoice_date']}<br><b>Bill To:</b> {html.escape(invoice['client_name'])}
    | GSTIN: {html.escape(invoice['client_gstin'] or 'Unregistered')}<br><b>Place of Supply:</b>
    {html.escape(invoice['place_of_supply_state'])} ({invoice['place_of_supply_code']})
    <table><thead><tr><th>Description</th><th>HSN/SAC</th><th>Qty</th><th>Unit</th><th>Rate</th>
    <th>Taxable</th><th>GST</th><th>Tax</th><th>Total</th></tr></thead><tbody>{rows_html}</tbody></table>
    <p style="text-align:right"><b>Grand Total: ₹ {invoice['grand_total']:,.2f}</b></p>
    <p><b>Amount in Words:</b> {html.escape(invoice['amount_in_words'])}</p></div>"""
    st.markdown("### Browser Print View"); st.markdown(preview,unsafe_allow_html=True)

elif page == "Import Invoices":
    st.title("Import Historical Invoices")
    st.caption("Imports legacy Excel invoices, creates missing clients/items, validates totals and skips duplicates.")

    uploaded = st.file_uploader("Select Excel file", type=["xlsx", "xls"], key="historical_invoice_upload")
    if not uploaded:
        st.info("Upload the historical invoice Excel file.")
        st.stop()

    try:
        legacy = pd.read_excel(uploaded)
    except Exception as e:
        st.error(f"Could not read Excel file: {e}")
        st.stop()

    legacy.columns = [str(c).strip() for c in legacy.columns]
    required = ["Date","Invoice No","Name","GSTIN","Taxable Value","Tax Rate",
                "IGST","CGST","SGST","Total","HSN Code","Quantity","Unit of Measurement"]
    missing = [c for c in required if c not in legacy.columns]
    if missing:
        st.error("Missing required column(s): " + ", ".join(missing))
        st.stop()

    legacy = legacy.dropna(how="all").copy()
    legacy["Date"] = pd.to_datetime(legacy["Date"], errors="coerce")
    legacy = legacy[legacy["Date"].notna() & legacy["Invoice No"].notna()].copy()
    if legacy.empty:
        st.error("No valid invoice rows were found.")
        st.stop()

    st.success(f'Found {legacy["Invoice No"].nunique()} invoice(s) and {len(legacy)} line row(s).')

    hsns = sorted({str(x).strip().replace(".0","") for x in legacy["HSN Code"].dropna() if str(x).strip()})
    st.markdown("#### HSN / Item Description Mapping")
    st.caption("Your source file has HSN codes but no item descriptions. Replace the suggested descriptions below if desired.")
    mapping_df = pd.DataFrame({"HSN Code":hsns, "Item Description":[f"HSN {h}" for h in hsns]})
    mapping_df = st.data_editor(mapping_df, hide_index=True, use_container_width=True,
                                disabled=["HSN Code"], key="hsn_mapping_editor")
    hsn_map = {str(r["HSN Code"]).strip():str(r["Item Description"]).strip()
               for _,r in mapping_df.iterrows()}

    c1,c2 = st.columns(2)
    formatted = c1.checkbox("Use configured invoice format", value=True,
        help="Example: numeric 746 becomes INV/2026-27/746.")
    states = list(INDIA_STATES.values())
    fallback_state = c2.selectbox("State for unregistered clients", states,
        index=states.index(business.get("default_state","Maharashtra")))

    st.dataframe(legacy[required].head(100), use_container_width=True, hide_index=True)

    if st.button("Import Historical Invoices", type="primary"):
        code_to_state = {v:k for k,v in STATE_TO_CODE.items()}
        imported, skipped, failed = [], [], []
        created_clients = 0

        for raw_no, grp in legacy.groupby("Invoice No", sort=False):
            try:
                inv_date = grp.iloc[0]["Date"].date()
                invoice_no = format_import_invoice_number(raw_no, inv_date, business) if formatted \
                    else str(raw_no).strip().replace(".0","")

                if invoice_number_exists(invoice_no):
                    skipped.append(f"{invoice_no} - already exists")
                    continue

                first = grp.iloc[0]
                client_name = "" if pd.isna(first["Name"]) else str(first["Name"]).strip()
                gstin = "" if pd.isna(first["GSTIN"]) else str(first["GSTIN"]).strip().upper()
                if gstin.endswith(".0"): gstin = gstin[:-2]

                client = find_client_for_import(client_name, gstin)
                if not client:
                    client_state = code_to_state.get(gstin[:2], fallback_state) if gstin else fallback_state
                    client_id = save_client({
                        "name": client_name or f"Legacy Client {invoice_no}",
                        "gstin": gstin, "address": "", "state": client_state,
                        "state_code": STATE_TO_CODE[client_state]
                    })
                    client = get_client(client_id)
                    created_clients += 1

                raw_items = []
                for _, row in grp.iterrows():
                    hsn = "" if pd.isna(row["HSN Code"]) else str(row["HSN Code"]).strip().replace(".0","")
                    qty = float(row["Quantity"] or 0)
                    taxable = float(row["Taxable Value"] or 0)
                    if qty <= 0: raise ValueError("Quantity must be greater than zero.")
                    unit = str(row["Unit of Measurement"] or business.get("default_unit","NOS")).strip().upper()
                    raw_items.append({
                        "description": hsn_map.get(hsn) or f"HSN {hsn}",
                        "hsn_sac": hsn, "quantity": qty, "unit": unit,
                        "rate": taxable / qty, "discount_percent": 0.0,
                        "gst_rate": float(row["Tax Rate"] or 0)
                    })

                invoice, calc_items = build_invoice(
                    inv_date, client["id"], client["state"], client["state_code"],
                    business, raw_items, "Imported historical invoice", invoice_no=invoice_no
                )

                # -----------------------------------------------------------------
                # Historical migration validation
                # -----------------------------------------------------------------
                # The legacy file contains already-issued invoice values. Rate is
                # reconstructed as Taxable Value / Quantity only because the source
                # does not contain the original unit rate. Small reconstruction and
                # rounding differences are therefore permitted.
                source_taxable = round(float(grp["Taxable Value"].fillna(0).sum()), 2)
                source_cgst = round(float(grp["CGST"].fillna(0).sum()), 2)
                source_sgst = round(float(grp["SGST"].fillna(0).sum()), 2)
                source_igst = round(float(grp["IGST"].fillna(0).sum()), 2)
                source_total = round(float(grp["Total"].fillna(0).max()), 2)

                tolerances = {
                    "Taxable": 10.00,
                    "CGST": 1.00,
                    "SGST": 1.00,
                    "IGST": 1.00,
                    "Total": 10.00,
                }
                checks = [
                    ("Taxable", invoice["taxable_total"], source_taxable),
                    ("CGST", invoice["cgst_total"], source_cgst),
                    ("SGST", invoice["sgst_total"], source_sgst),
                    ("IGST", invoice["igst_total"], source_igst),
                    ("Total", invoice["grand_total"], source_total),
                ]
                mismatches = [
                    f"{name}: calculated {calc:.2f}, source {src:.2f}, "
                    f"difference {abs(round(calc,2)-src):.2f} exceeds tolerance {tolerances[name]:.2f}"
                    for name, calc, src in checks
                    if abs(round(calc,2)-src) > tolerances[name]
                ]
                if mismatches:
                    raise ValueError(" | ".join(mismatches))

                # -----------------------------------------------------------------
                # Preserve source statutory figures
                # -----------------------------------------------------------------
                # These are historical invoices already issued. Once the reconstructed
                # calculation is within tolerance, the Excel values become authoritative
                # for reporting and invoice history.
                invoice["taxable_total"] = source_taxable
                invoice["cgst_total"] = source_cgst
                invoice["sgst_total"] = source_sgst
                invoice["igst_total"] = source_igst
                invoice["grand_total"] = source_total

                # Preserve source values at line-item level as well. This file currently
                # has one row per invoice, but this also works if future legacy files
                # contain multiple rows for an invoice.
                for calc_item, (_, source_row) in zip(calc_items, grp.iterrows()):
                    src_taxable = round(float(source_row["Taxable Value"] or 0), 2)
                    src_cgst = round(float(source_row["CGST"] or 0), 2)
                    src_sgst = round(float(source_row["SGST"] or 0), 2)
                    src_igst = round(float(source_row["IGST"] or 0), 2)

                    calc_item["taxable_value"] = src_taxable
                    calc_item["cgst_amount"] = src_cgst
                    calc_item["sgst_amount"] = src_sgst
                    calc_item["igst_amount"] = src_igst
                    calc_item["line_total"] = round(
                        src_taxable + src_cgst + src_sgst + src_igst, 2
                    )

                    # Keep gross/discount internally consistent for the imported
                    # historical row. Source file has no separate discount amount.
                    calc_item["gross_value"] = src_taxable
                    calc_item["discount_amount"] = 0.0
                    calc_item["discount_percent"] = 0.0

                invoice["subtotal"] = source_taxable
                invoice["discount_total"] = 0.0

                # Rebuild amount-in-words from the authoritative historical total.
                from gst_utils import number_to_words_indian
                invoice["amount_in_words"] = number_to_words_indian(source_total)

                insert_invoice(invoice, calc_items)
                imported.append(invoice_no)
            except Exception as e:
                failed.append(f"{raw_no}: {e}")

        if imported:
            st.success(f"Imported {len(imported)} invoice(s); created {created_clients} new client(s).")
            st.info("Item Master was created/updated automatically. The next invoice will continue from the highest imported sequence.")
        if skipped:
            st.warning(f"Skipped {len(skipped)} duplicate invoice(s).")
            with st.expander("Skipped invoices"): st.write("\n".join(skipped))
        if failed:
            st.error(f"{len(failed)} invoice(s) failed validation and were not imported.")
            with st.expander("Import errors"): st.write("\n".join(failed))

elif page == "Reports":
    st.title("GST Reports")
    today=date.today()
    default_period=business.get("default_report_period","Current Month")
    mode=st.selectbox("Period",REPORT_PERIODS,index=REPORT_PERIODS.index(default_period) if default_period in REPORT_PERIODS else 0)
    if mode=="Current Month":
        start=today.replace(day=1); end=today
    elif mode=="Current Quarter":
        q=((today.month-1)//3)*3+1; start=date(today.year,q,1); end=today
    elif mode=="Current Financial Year":
        start=date(today.year if today.month>=4 else today.year-1,4,1); end=today
    else:
        c1,c2=st.columns(2); start=c1.date_input("From Date",today.replace(day=1)); end=c2.date_input("To Date",today)
    if start>end: st.error("From Date cannot be after To Date."); st.stop()
    raw,b2b,b2c,hsn=build_reports(start.isoformat(),end.isoformat())
    if raw.empty: st.info("No transactions found for the selected period."); st.stop()
    inv_summary=raw.groupby("invoice_id",as_index=False).agg(invoice_value=("invoice_value","first"))
    values=[inv_summary["invoice_value"].sum(),raw["taxable_value"].sum(),raw["cgst_amount"].sum(),
            raw["sgst_amount"].sum(),raw["igst_amount"].sum()]
    for col,label,val in zip(st.columns(5),["Total Sales Value","Taxable Amount","CGST","SGST","IGST"],values):
        col.metric(label,f"₹ {val:,.2f}")
    tabs=st.tabs(["B2B Sales","B2C Summary","HSN/SAC Summary"])
    with tabs[0]:
        st.dataframe(b2b,use_container_width=True,hide_index=True)
        st.download_button("Download B2B CSV",b2b.to_csv(index=False).encode("utf-8-sig"),"B2B_Sales.csv","text/csv")
    with tabs[1]:
        st.dataframe(b2c,use_container_width=True,hide_index=True)
        st.download_button("Download B2C CSV",b2c.to_csv(index=False).encode("utf-8-sig"),"B2C_Summary.csv","text/csv")
    with tabs[2]:
        st.dataframe(hsn,use_container_width=True,hide_index=True)
        st.download_button("Download HSN CSV",hsn.to_csv(index=False).encode("utf-8-sig"),"HSN_Summary.csv","text/csv")
    st.download_button("Download Complete GST Report (Excel)",excel_bytes(b2b,b2c,hsn),
        f"GST_Report_{start}_{end}.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
