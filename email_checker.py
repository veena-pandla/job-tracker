"""
Gmail inbox checker — scans for job application responses and auto-updates the database.

Setup (one-time):
  1. Go to myaccount.google.com → Security → 2-Step Verification → App passwords
  2. Generate an App Password for "Mail"
  3. Add to .env:
       GMAIL_EMAIL=you@gmail.com
       GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx   (16-char code from Google)

Run standalone:  python email_checker.py
Or via dashboard: sidebar button "Check Gmail Inbox"
"""
import imaplib
import email
import os
import re
from datetime import datetime, timezone, timedelta
from email.header import decode_header
from dotenv import load_dotenv

from database import get_jobs, update_status, get_conn

load_dotenv()

GMAIL_EMAIL    = os.getenv("GMAIL_EMAIL", "")
GMAIL_APP_PASS = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")

# Keywords that indicate a job-related email
JOB_KEYWORDS = [
    "application", "applied", "position", "role", "opportunity",
    "interview", "offer", "unfortunately", "regret", "not moving forward",
    "thank you for your interest", "next steps", "hiring", "recruiter",
    "job", "career", "employment",
]

# Classification patterns (fast, no AI needed for clear signals)
REJECT_PHRASES = [
    # Direct soft rejections
    "unfortunately", "regret to inform", "not selected", "not a fit",
    "not be moving forward", "not moving forward", "will not be moving",
    "unable to offer", "not successful", "did not select", "not proceed",
    "cannot offer", "we won't be",

    # "Decided to go with others" variations
    "decided to move forward with other", "decided to pursue other",
    "move forward with another", "pursuing other candidates",
    "pursuing candidates whose", "decided to go with",
    "other candidates more closely", "better suited candidates",
    "stronger match", "more closely aligns",

    # "Keep on file" = always a rejection
    "keep your resume on file", "keep your application on file",
    "keep you in mind for future", "consider you for future opportunities",
    "encourage you to apply for future", "other opportunities at",

    # "Position filled / no longer available"
    "position has been filled", "role has been filled",
    "position is no longer", "no longer accepting",

    # Polite closings that signal rejection
    "best of luck in your search", "best wishes in your job search",
    "best wishes in your search", "wish you the best in your",
    "success in your job search", "future endeavors",

    # "After careful consideration" openers
    "after careful consideration", "after thorough consideration",
    "after reviewing your", "having reviewed your application",
    "after much consideration",

    # "We had many applicants"
    "highly competitive", "strong pool of candidates",
    "overwhelming number of applicants", "many qualified applicants",
    "volume of applications",
]
# Interview = only when there is an actual calendar/meeting invite (not just the word "interview")
CALENDAR_SIGNALS = [
    "zoom.us/j/", "zoom.us/meeting", "meet.google.com/",
    "teams.microsoft.com/", "webex.com/", "gotomeeting.com/",
    "calendar invitation", "calendar invite", "you have been invited",
    "you're invited", "accepted this invitation", "add to calendar",
    ".ics", "ical", "vcalendar",
    "scheduled for", "your interview is", "interview is scheduled",
    "confirmed for", "book a time", "pick a time", "choose a time",
    "calendly.com/",
]
OFFER_PHRASES = [
    "offer letter", "job offer", "pleased to offer", "we would like to offer",
    "compensation package", "start date", "salary offer", "formal offer",
]


def _decode_str(s) -> str:
    """Decode email header string."""
    if not s:
        return ""
    parts = decode_header(s)
    decoded = []
    for part, enc in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return " ".join(decoded)


def _get_body(msg) -> str:
    """Extract plain text body from email message."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                payload = part.get_payload(decode=True)
                if payload:
                    body += payload.decode(errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            body = payload.decode(errors="replace")
    return body[:4000]


def _has_calendar_invite(msg) -> bool:
    """Check if the email contains an actual calendar invite (.ics attachment or text/calendar part)."""
    for part in msg.walk():
        ct = part.get_content_type()
        fname = str(part.get_filename() or "").lower()
        if ct == "text/calendar" or fname.endswith(".ics"):
            return True
    return False


def _classify_email(subject: str, body: str, msg=None) -> str:
    """
    Classify email as: offer / interview / rejected / follow_up / not_related
    Interview requires an actual calendar/meeting invite — not just the word 'interview'.
    """
    text = (subject + " " + body).lower()

    # Check if job-related at all
    if not any(kw in text for kw in JOB_KEYWORDS):
        return "not_related"

    if any(p in text for p in OFFER_PHRASES):
        return "offer"

    # Interview: only if there's a real meeting link or calendar attachment
    has_cal = _has_calendar_invite(msg) if msg else False
    has_meeting_link = any(p in text for p in CALENDAR_SIGNALS)
    if has_cal or has_meeting_link:
        return "interview"

    if any(p in text for p in REJECT_PHRASES):
        return "rejected"

    return "follow_up"


def _match_company(sender_domain: str, subject: str, body: str, companies: list[str]) -> str | None:
    """Find which company in our DB this email is from."""
    sender_domain = sender_domain.lower()
    text_lower = (subject + " " + body).lower()

    for company in companies:
        co_clean = company.lower().strip()
        # Match against sender domain
        co_domain = re.sub(r"[^a-z0-9]", "", co_clean)
        if co_domain and co_domain in sender_domain.replace(".", "").replace("-", ""):
            return company
        # Match company name in subject/body
        if len(co_clean) > 3 and co_clean in text_lower:
            return company
    return None


def check_gmail(days_back: int = 14) -> list[dict]:
    """
    Connect to Gmail, scan recent emails, classify job responses,
    auto-update database statuses. Returns list of result dicts.
    """
    if not GMAIL_EMAIL or not GMAIL_APP_PASS:
        return [{"error": "GMAIL_EMAIL or GMAIL_APP_PASSWORD not set in .env"}]

    results = []

    # Load all companies from DB
    all_jobs = get_jobs(status=None, min_score=0)
    companies = list({j["company"] for j in all_jobs if j.get("company")})
    # Build company -> job_id map (prefer applied > reviewed > new)
    status_rank = {"applied": 3, "interviewing": 2, "offer": 4, "reviewed": 1, "new": 0}
    company_job = {}
    for j in sorted(all_jobs, key=lambda x: status_rank.get(x.get("status", "new"), 0)):
        company_job[j["company"]] = j

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(GMAIL_EMAIL, GMAIL_APP_PASS)
        mail.select("INBOX")

        # Search emails from last N days
        since_date = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
        _, msg_ids = mail.search(None, f'(SINCE "{since_date}")')

        if not msg_ids or not msg_ids[0]:
            mail.logout()
            return [{"info": f"No emails found in last {days_back} days."}]

        ids = msg_ids[0].split()
        print(f"[Gmail] Scanning {len(ids)} emails from last {days_back} days...")

        processed = 0
        for msg_id in reversed(ids[-200:]):  # Check latest 200 emails
            try:
                _, data = mail.fetch(msg_id, "(RFC822)")
                raw = data[0][1]
                msg = email.message_from_bytes(raw)

                subject = _decode_str(msg.get("Subject", ""))
                sender  = _decode_str(msg.get("From", ""))
                body    = _get_body(msg)

                # Extract sender domain
                domain_match = re.search(r"@([\w.-]+)", sender)
                sender_domain = domain_match.group(1).lower() if domain_match else ""

                # ── LinkedIn application confirmation emails ──────────────────
                # LinkedIn sends "Your application was sent to [Company]" emails.
                # Detect these separately before the skip_domains check.
                is_linkedin = "linkedin.com" in sender_domain
                if is_linkedin:
                    subject_lower = subject.lower()
                    body_lower    = body.lower()
                    linkedin_confirm_phrases = [
                        "your application was sent",
                        "application was submitted",
                        "you applied to",
                        "application submitted to",
                        "successfully applied",
                    ]
                    is_confirmation = any(p in subject_lower or p in body_lower
                                         for p in linkedin_confirm_phrases)
                    if is_confirmation:
                        # Try to extract company from subject e.g. "Your application was sent to Acme Corp"
                        company_from_subject = None
                        for phrase in ["was sent to ", "applied to ", "submitted to "]:
                            idx = subject_lower.find(phrase)
                            if idx != -1:
                                company_from_subject = subject[idx + len(phrase):].strip()
                                break
                        # Match against DB companies
                        matched = _match_company("", subject, body, companies) or \
                                  (company_from_subject and _match_company("", company_from_subject, "", companies))
                        if matched:
                            job = company_job.get(matched)
                            if job and job.get("status") not in ("applied", "interviewing", "offer"):
                                from database import mark_applied
                                mark_applied(job["id"], f"[Auto] Applied — confirmed by LinkedIn email | {subject[:80]}")
                                print(f"  [APPLIED] {matched} -> marked applied via LinkedIn confirmation email")
                                results.append({
                                    "company":        matched,
                                    "subject":        subject,
                                    "sender":         sender,
                                    "sender_name":    "LinkedIn",
                                    "classification": "applied_confirmation",
                                    "job_id":         job["id"],
                                    "new_status":     "applied",
                                })
                                processed += 1
                    continue  # skip all other LinkedIn emails (job alerts, etc.)

                # Skip other job board marketing emails (not company responses)
                skip_domains = ["indeed.com", "glassdoor.com", "ziprecruiter.com",
                                "greenhouse.io", "lever.co", "workday.com", "icims.com"]
                if any(sd in sender_domain for sd in skip_domains):
                    continue

                classification = _classify_email(subject, body, msg)
                if classification == "not_related":
                    continue

                matched_company = _match_company(sender_domain, subject, body, companies)
                if not matched_company:
                    continue

                job = company_job.get(matched_company)
                if not job:
                    continue

                # Extract sender display name (e.g. "John Smith <john@company.com>" -> "John Smith")
                sender_name = re.sub(r"<.*?>", "", sender).strip().strip('"').strip("'") or sender_domain

                # Map classification to status
                status_map = {
                    "offer":      "offer",
                    "interview":  "interviewing",
                    "rejected":   "rejected",
                    "follow_up":  None,
                }
                new_status = status_map.get(classification)

                note = f"[Auto] {classification.upper()} | From: {sender_name} | {subject[:80]}"

                if new_status and job.get("status") not in ("offer", "interviewing", "rejected"):
                    update_status(job["id"], new_status, note)
                    print(f"  [{classification.upper()}] {matched_company} -> status set to '{new_status}'")
                else:
                    existing_notes = job.get("notes", "") or ""
                    if note not in existing_notes:
                        update_status(job["id"], job.get("status", "new"), existing_notes + "\n" + note)

                results.append({
                    "company":        matched_company,
                    "subject":        subject,
                    "sender":         sender,
                    "sender_name":    sender_name,
                    "classification": classification,
                    "job_id":         job["id"],
                    "new_status": new_status,
                })
                processed += 1

            except Exception as e:
                print(f"[Gmail] Error processing email {msg_id}: {e}")

        mail.logout()
        print(f"[Gmail] Done. {processed} job-related emails found and processed.")

    except imaplib.IMAP4.error as e:
        return [{"error": f"Gmail login failed: {e}\n\nMake sure you're using an App Password, not your regular password.\nGet one at: myaccount.google.com -> Security -> App passwords"}]
    except Exception as e:
        return [{"error": str(e)}]

    return results if results else [{"info": "No job-related emails matched companies in your database."}]


if __name__ == "__main__":
    results = check_gmail(days_back=14)
    for r in results:
        if "error" in r:
            print(f"ERROR: {r['error']}")
        elif "info" in r:
            print(r["info"])
        else:
            print(f"  {r['classification'].upper():12} | {r['company']:30} | {r['subject'][:50]}")
