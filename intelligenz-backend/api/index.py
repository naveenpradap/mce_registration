import os
import re
import csv
import io
import random
import string
import smtplib
import psycopg2
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, send_file, Response, flash
)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv isn't needed in production (Vercel injects env vars directly)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "..", "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "..", "static"),
)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # 4 MB upload cap

DATABASE_URL = os.environ.get("DATABASE_URL")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_EMAIL = os.environ.get("SMTP_EMAIL")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")

EVENT_NAME = os.environ.get("EVENT_NAME", "INTELLIGENZ 2K26")
OTP_VALID_MINUTES = 10

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Add a Postgres connection string "
            "(e.g. from Neon or Vercel Postgres) as an environment variable."
        )
    conn = psycopg2.connect(DATABASE_URL, sslmode="require")
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS registrations (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            reg_no TEXT NOT NULL,
            college TEXT NOT NULL,
            email TEXT NOT NULL,
            transaction_id TEXT NOT NULL,
            screenshot BYTEA NOT NULL,
            screenshot_mimetype TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            submitted_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        """
    )
    conn.commit()
    cur.close()
    conn.close()


_db_ready = False


def ensure_db():
    global _db_ready
    if not _db_ready:
        init_db()
        _db_ready = True


# ---------------------------------------------------------------------------
# Email helper
# ---------------------------------------------------------------------------
def send_otp_email(to_email, name, otp):
    if not SMTP_EMAIL or not SMTP_PASSWORD:
        raise RuntimeError(
            "SMTP_EMAIL / SMTP_PASSWORD are not set. Add a Gmail address and "
            "an App Password as environment variables to send OTP emails."
        )
    subject = f"{EVENT_NAME} - Your Verification Code"
    body = (
        f"Hi {name},\n\n"
        f"Your verification code for {EVENT_NAME} registration is: {otp}\n\n"
        f"This code is valid for {OTP_VALID_MINUTES} minutes.\n"
        f"If you did not request this, you can ignore this email.\n\n"
        f"- {EVENT_NAME} Team"
    )
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_EMAIL
    msg["To"] = to_email

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.sendmail(SMTP_EMAIL, [to_email], msg.as_string())


def generate_otp():
    return "".join(random.choices(string.digits, k=6))


# ---------------------------------------------------------------------------
# Auth decorator for admin routes
# ---------------------------------------------------------------------------
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Public site
# ---------------------------------------------------------------------------
@app.route("/")
def home():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Step 1: Registration details
# ---------------------------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html", event_name=EVENT_NAME)

    name = request.form.get("name", "").strip()
    reg_no = request.form.get("reg_no", "").strip()
    college = request.form.get("college", "").strip()
    email = request.form.get("email", "").strip().lower()

    if not all([name, reg_no, college, email]):
        return render_template(
            "register.html", event_name=EVENT_NAME,
            error="Please fill in all fields.",
            values=request.form,
        )
    if not EMAIL_RE.match(email):
        return render_template(
            "register.html", event_name=EVENT_NAME,
            error="Please enter a valid email address.",
            values=request.form,
        )

    otp = generate_otp()
    session["reg_data"] = {
        "name": name, "reg_no": reg_no, "college": college, "email": email,
    }
    session["otp"] = otp
    session["otp_expires"] = (
        datetime.utcnow() + timedelta(minutes=OTP_VALID_MINUTES)
    ).isoformat()
    session["email_verified"] = False

    try:
        send_otp_email(email, name, otp)
    except Exception as e:
        return render_template(
            "register.html", event_name=EVENT_NAME,
            error=f"Could not send verification email: {e}",
            values=request.form,
        )

    return redirect(url_for("verify_otp"))


# ---------------------------------------------------------------------------
# Step 2: Email OTP verification
# ---------------------------------------------------------------------------
@app.route("/verify-otp", methods=["GET", "POST"])
def verify_otp():
    reg_data = session.get("reg_data")
    if not reg_data:
        return redirect(url_for("register"))

    if request.method == "GET":
        return render_template(
            "verify_otp.html", event_name=EVENT_NAME, email=reg_data["email"]
        )

    submitted = request.form.get("otp", "").strip()
    expires_raw = session.get("otp_expires")
    expired = (
        not expires_raw or datetime.utcnow() > datetime.fromisoformat(expires_raw)
    )

    if expired:
        return render_template(
            "verify_otp.html", event_name=EVENT_NAME, email=reg_data["email"],
            error="Code expired. Please request a new one.",
        )

    if submitted != session.get("otp"):
        return render_template(
            "verify_otp.html", event_name=EVENT_NAME, email=reg_data["email"],
            error="Incorrect code. Please try again.",
        )

    session["email_verified"] = True
    return redirect(url_for("payment"))


@app.route("/resend-otp", methods=["POST"])
def resend_otp():
    reg_data = session.get("reg_data")
    if not reg_data:
        return redirect(url_for("register"))

    otp = generate_otp()
    session["otp"] = otp
    session["otp_expires"] = (
        datetime.utcnow() + timedelta(minutes=OTP_VALID_MINUTES)
    ).isoformat()

    try:
        send_otp_email(reg_data["email"], reg_data["name"], otp)
        return render_template(
            "verify_otp.html", event_name=EVENT_NAME, email=reg_data["email"],
            info="A new code has been sent.",
        )
    except Exception as e:
        return render_template(
            "verify_otp.html", event_name=EVENT_NAME, email=reg_data["email"],
            error=f"Could not resend email: {e}",
        )


# ---------------------------------------------------------------------------
# Step 3: Payment - GPay QR, transaction ID, screenshot upload
# ---------------------------------------------------------------------------
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


@app.route("/payment", methods=["GET", "POST"])
def payment():
    reg_data = session.get("reg_data")
    if not reg_data or not session.get("email_verified"):
        return redirect(url_for("register"))

    if request.method == "GET":
        return render_template(
            "payment.html", event_name=EVENT_NAME, reg_data=reg_data
        )

    transaction_id = request.form.get("transaction_id", "").strip()
    screenshot = request.files.get("screenshot")

    if not transaction_id:
        return render_template(
            "payment.html", event_name=EVENT_NAME, reg_data=reg_data,
            error="Please enter the transaction ID.",
        )
    if not screenshot or screenshot.filename == "":
        return render_template(
            "payment.html", event_name=EVENT_NAME, reg_data=reg_data,
            error="Please upload your payment screenshot.",
        )
    if screenshot.mimetype not in ALLOWED_IMAGE_TYPES:
        return render_template(
            "payment.html", event_name=EVENT_NAME, reg_data=reg_data,
            error="Screenshot must be a JPEG, PNG, or WEBP image.",
        )

    image_bytes = screenshot.read()

    try:
        ensure_db()
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO registrations
                (name, reg_no, college, email, transaction_id,
                 screenshot, screenshot_mimetype)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (
                reg_data["name"], reg_data["reg_no"], reg_data["college"],
                reg_data["email"], transaction_id,
                psycopg2.Binary(image_bytes), screenshot.mimetype,
            ),
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        return render_template(
            "payment.html", event_name=EVENT_NAME, reg_data=reg_data,
            error=f"Could not save your registration: {e}",
        )

    session.clear()
    return render_template(
        "success.html", event_name=EVENT_NAME, reg_id=new_id,
        name=reg_data["name"],
    )


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "GET":
        return render_template("admin_login.html", event_name=EVENT_NAME)

    username = request.form.get("username", "")
    password = request.form.get("password", "")
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session["is_admin"] = True
        return redirect(url_for("admin_dashboard"))
    return render_template(
        "admin_login.html", event_name=EVENT_NAME,
        error="Invalid username or password.",
    )


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    return render_template("admin_dashboard.html", event_name=EVENT_NAME)


@app.route("/admin/api/registrations")
@admin_required
def admin_api_registrations():
    ensure_db()
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, reg_no, college, email, transaction_id, status,
               submitted_at
        FROM registrations
        ORDER BY submitted_at DESC;
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    data = [
        {
            "id": r[0], "name": r[1], "reg_no": r[2], "college": r[3],
            "email": r[4], "transaction_id": r[5], "status": r[6],
            "submitted_at": r[7].isoformat(),
        }
        for r in rows
    ]
    return jsonify(data)


@app.route("/admin/screenshot/<int:reg_id>")
@admin_required
def admin_screenshot(reg_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT screenshot, screenshot_mimetype FROM registrations WHERE id = %s;",
        (reg_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return "Not found", 404
    return send_file(
        io.BytesIO(row[0]), mimetype=row[1], download_name=f"screenshot_{reg_id}"
    )


@app.route("/admin/update-status/<int:reg_id>", methods=["POST"])
@admin_required
def admin_update_status(reg_id):
    new_status = request.json.get("status") if request.is_json else None
    if new_status not in ("pending", "approved", "rejected"):
        return jsonify({"error": "invalid status"}), 400

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE registrations SET status = %s WHERE id = %s;",
        (new_status, reg_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True})


@app.route("/admin/export.csv")
@admin_required
def admin_export_csv():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, reg_no, college, email, transaction_id, status,
               submitted_at
        FROM registrations
        ORDER BY submitted_at DESC;
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["ID", "Name", "Reg No", "College", "Email", "Transaction ID",
         "Status", "Submitted At"]
    )
    for r in rows:
        writer.writerow(r)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=registrations.csv"},
    )


# Local dev entrypoint
if __name__ == "__main__":
    app.run(debug=True, port=5000)
