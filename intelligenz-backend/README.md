# INTELLIGENZ 2K26 — Registration Backend

Live registration system: landing page → student fills details → email OTP
verification → GPay payment (transaction ID + screenshot) → saved to a
database that you monitor from a private admin dashboard.

## What's inside

```
api/index.py          Flask app (all routes, DB, email, admin)
templates/             Landing page + registration flow + admin pages
static/                Put your GPay QR image here as gpay-qr.png
vercel.json            Tells Vercel how to run the Flask app
requirements.txt       Python dependencies
.env.example           All environment variables you need to set
```

## 1. Add your GPay QR code

Save your GPay QR code image as:
```
static/gpay-qr.png
```
Until you add it, the payment page shows a placeholder box so nothing breaks.

## 2. Set up a database (Postgres)

Vercel's servers don't keep files between requests, so registrations —
including the screenshot images — are stored in Postgres instead of on disk.

Easiest path: in your Vercel project dashboard → **Storage** tab → **Create
Database** → **Postgres** (this is Neon under the hood, free tier is plenty
for a college event). It gives you a `DATABASE_URL` automatically — copy it
into your environment variables (see step 4). No manual table setup needed;
the app creates the table itself on first run.

## 3. Set up Gmail for OTP emails

1. Turn on 2-Step Verification on the Gmail account you want to send from:
   https://myaccount.google.com/security
2. Create an App Password: https://myaccount.google.com/apppasswords
   (choose "Mail" as the app) — you'll get a 16-character code.
3. Use that Gmail address as `SMTP_EMAIL` and the 16-character code as
   `SMTP_PASSWORD` (not your normal Gmail password).

## 4. Environment variables

Copy `.env.example` as a guide. In Vercel: **Project → Settings →
Environment Variables**, add each one:

| Variable | What it is |
|---|---|
| `DATABASE_URL` | Postgres connection string from step 2 |
| `SECRET_KEY` | Any long random string (protects login sessions) |
| `ADMIN_USERNAME` | Your admin login username |
| `ADMIN_PASSWORD` | Your admin login password |
| `SMTP_SERVER` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_EMAIL` | Gmail address sending OTPs |
| `SMTP_PASSWORD` | Gmail App Password from step 3 |
| `EVENT_NAME` | `INTELLIGENZ 2K26` (or whatever you want shown) |

## 5. Deploy to Vercel

Vercel deploys from a Git repo (GitHub/GitLab/Bitbucket), or via their CLI.

**Via GitHub (easiest):**
1. Push this folder to a new GitHub repo.
2. Go to https://vercel.com/new, import that repo.
3. Add the environment variables from step 4 during import (or after, in
   Settings → Environment Variables).
4. Deploy. Vercel gives you a live URL like `your-project.vercel.app`.

**Via CLI:**
```bash
npm i -g vercel
cd intelligenz-backend
vercel
# follow prompts, then add env vars:
vercel env add DATABASE_URL
vercel env add SECRET_KEY
vercel env add ADMIN_USERNAME
vercel env add ADMIN_PASSWORD
vercel env add SMTP_SERVER
vercel env add SMTP_PORT
vercel env add SMTP_EMAIL
vercel env add SMTP_PASSWORD
vercel env add EVENT_NAME
vercel --prod
```

## 6. Test locally first (recommended)

```bash
pip install -r requirements.txt
export DATABASE_URL="postgresql://..."   # from step 2
export SECRET_KEY="dev-secret"
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="admin123"
export SMTP_EMAIL="youraccount@gmail.com"
export SMTP_PASSWORD="your-app-password"
python api/index.py
```
Visit http://localhost:5000

## How it works

- **`/`** — your landing page. "Register" buttons now go to `/register`
  instead of a Google Form.
- **`/register`** — name, registration number, college, email → sends a
  6-digit OTP to that email.
- **`/verify-otp`** — student enters the code (valid 10 minutes, can resend).
- **`/payment`** — shows your GPay QR, student enters the UPI transaction ID
  and uploads a screenshot.
- On submit, the full record (including the screenshot as binary data) is
  saved to Postgres with status `pending`.
- **`/admin/login`** — your private login (username + password from env vars).
- **`/admin/dashboard`** — live table of every registration, auto-refreshing
  every 8 seconds, with search, a link to view each screenshot, a status
  dropdown (pending/approved/rejected) per student, and a CSV export button.

## Notes

- Upload size is capped at 4 MB per screenshot — tell students to keep
  screenshots reasonably compressed.
- Registration details are held in a signed cookie between the 3 steps and
  only written to the database once the full flow (including payment) is
  complete — so half-finished attempts don't clutter your admin list.
- Change `ADMIN_PASSWORD` to something real before going live — the default
  in `.env.example` is just a placeholder.
