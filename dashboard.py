"""
Streamlit dashboard — view and manage all job applications.

Run with: streamlit run dashboard.py
  OR:     python main.py --dashboard
"""
import streamlit as st
import pandas as pd
import io
import threading
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from database import get_jobs, get_stats, update_status, mark_applied, get_job_by_id
import requests

EASTERN = ZoneInfo("America/New_York")

# Cache Easy Apply checks so we only fetch each job URL once per session
_EASY_APPLY_CACHE: dict[str, bool] = {}

def check_linkedin_easy_apply(url: str) -> bool:
    """
    Use LinkedIn's jobs-guest API to detect Easy Apply.
    Signal: 'apply-link-offsite' in response = External Site; absent = Easy Apply.
    """
    if url in _EASY_APPLY_CACHE:
        return _EASY_APPLY_CACHE[url]
    try:
        import re
        job_id_match = re.search(r"/view/(\d+)", url)
        if not job_id_match:
            return False
        job_id = job_id_match.group(1)
        api_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
        r = requests.get(api_url, headers=headers, timeout=8)
        is_easy = "apply-link-offsite" not in r.text.lower()
        _EASY_APPLY_CACHE[url] = is_easy
        return is_easy
    except Exception:
        return False

st.set_page_config(
    page_title="Job Tracker — Veena",
    page_icon="💼",
    layout="wide"
)

# ── Auto-scrape on open (max once every 2 hours) ─────────────────────────────
_STAMP_FILE    = Path(__file__).parent / ".last_scraped"
_PROGRESS_FILE = Path(__file__).parent / ".scrape_in_progress"

def _should_scrape() -> bool:
    if _PROGRESS_FILE.exists():
        return False  # already running
    if not _STAMP_FILE.exists():
        return True
    try:
        last = datetime.fromisoformat(_STAMP_FILE.read_text().strip())
        return (datetime.now() - last).total_seconds() > 30 * 60
    except Exception:
        return True

def _run_scraper_bg():
    try:
        _PROGRESS_FILE.write_text("running")
        subprocess.run(
            [sys.executable, "main.py", "--scrape-only"],
            cwd=str(Path(__file__).parent),
            capture_output=True
        )
        _STAMP_FILE.write_text(datetime.now(timezone.utc).isoformat())
    except Exception:
        pass
    finally:
        try:
            _PROGRESS_FILE.unlink()
        except Exception:
            pass

if _should_scrape():
    t = threading.Thread(target=_run_scraper_bg, daemon=True)
    t.start()

# ── Auto-check Gmail (max once every 1 hour) ──────────────────────────────────
_GMAIL_STAMP_FILE = Path(__file__).parent / ".last_gmail_checked"

def _should_check_gmail() -> bool:
    if not _GMAIL_STAMP_FILE.exists():
        return True
    try:
        last = datetime.fromisoformat(_GMAIL_STAMP_FILE.read_text().strip())
        return (datetime.now() - last).total_seconds() > 3600
    except Exception:
        return True

def _run_gmail_bg():
    try:
        from email_checker import check_gmail
        check_gmail(days_back=7)
        _GMAIL_STAMP_FILE.write_text(datetime.now().isoformat())
    except Exception:
        pass

if _should_check_gmail():
    tg = threading.Thread(target=_run_gmail_bg, daemon=True)
    tg.start()

st.title("💼 Job Application Tracker")

if _PROGRESS_FILE.exists():
    st.info("🔄 Fetching fresh jobs in the background — click **🔄 Refresh Jobs Now** when done to see new results.", icon="🔄")
elif _STAMP_FILE.exists():
    try:
        last_dt = datetime.fromisoformat(_STAMP_FILE.read_text().strip())
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        last_dt_et = last_dt.astimezone(EASTERN)
        st.success(f"✅ Jobs last updated at {last_dt_et.strftime('%I:%M %p ET')} — next refresh in 30 min.", icon="✅")
    except Exception:
        pass

# ── Helper functions ────────────────────────────────────────────────────────────
def detect_job_type(job: dict) -> str:
    desc = (job.get("description", "") or "").lower()
    title = (job.get("title", "") or "").lower()
    text = desc + " " + title
    if any(w in text for w in ["contract", "c2c", "w2", "1099", "freelance", "contractor"]):
        return "Contract"
    if any(w in text for w in ["full-time", "full time", "permanent", "salaried"]):
        return "Full Time"
    return "Unknown"


def detect_h1b(job: dict) -> str:
    desc = (job.get("description", "") or "").lower()
    no_sponsor = any(p in desc for p in [
        "unable to sponsor", "not sponsor", "no sponsor", "cannot sponsor",
        "without sponsorship", "no visa", "us citizen", "green card only",
        "authorized to work"
    ])
    yes_sponsor = any(p in desc for p in ["h1b", "h-1b", "will sponsor", "sponsorship available", "visa sponsorship"])
    if no_sponsor:
        return "No"
    if yes_sponsor:
        return "Yes"
    return "Unknown"


def posted_age(job: dict) -> str:
    """
    Show precise time using date_found (exact scrape timestamp) for minutes/hours.
    Fall back to date_posted (date-only from jobspy) for day-level display.
    """
    now_utc = datetime.now(timezone.utc)

    # Step 1: try date_posted — if it has a real time component (not midnight), use it
    date_str = job.get("date_posted", "")
    if date_str and str(date_str).lower() not in ("nat", "none", "nan"):
        try:
            dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt.hour != 0 or dt.minute != 0:  # has real time info
                diff = now_utc - dt
                mins = int(diff.total_seconds() / 60)
                if mins < 60:
                    return f"{mins}m ago"
                hrs = int(diff.total_seconds() / 3600)
                if hrs < 24:
                    return f"{hrs}h ago"
        except Exception:
            pass

    # Step 2: use date_found (exact moment we scraped it) for hour/minute precision
    found_str = job.get("date_found", "")
    if found_str and str(found_str).lower() not in ("nat", "none", "nan"):
        try:
            dt = datetime.fromisoformat(str(found_str).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            diff = now_utc - dt
            mins = int(diff.total_seconds() / 60)
            if mins < 60:
                return f"{mins}m ago"
            hrs = int(diff.total_seconds() / 3600)
            if hrs < 48:
                return f"{hrs}h ago"
        except Exception:
            pass

    # Step 3: fall back to date_posted day-level (Today / Yesterday / Xd ago)
    if date_str and str(date_str).lower() not in ("nat", "none", "nan"):
        try:
            dt = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            now_et = datetime.now(EASTERN)
            dt_date = dt.astimezone(EASTERN).date()
            diff_days = (now_et.date() - dt_date).days
            if diff_days == 0:
                return "Today"
            if diff_days == 1:
                return "Yesterday"
            if diff_days < 7:
                return f"{diff_days}d ago"
            return f"{diff_days // 7}w ago"
        except Exception:
            pass

    return "Unknown"


def color_posted_age(val: str) -> str:
    if "m ago" in val:  # minutes ago — very fresh
        return "color: #15803d; font-weight: bold"
    if "h ago" in val:
        hrs = int(val.replace("h ago", "").strip() or 99)
        if hrs <= 6:
            return "color: #15803d; font-weight: bold"
        return "color: #1d4ed8"
    if val in ("Today", "Yesterday"):
        return "color: #1d4ed8"
    if "d ago" in val:
        days = int(val.replace("d ago", "").strip() or 99)
        if days <= 3:
            return "color: #b45309"
        return "color: #dc2626"
    return ""


def detect_apply_type(job: dict, live_check: bool = False) -> str:
    source = (job.get("source", "") or "").lower()
    tags = job.get("tags") or []
    if isinstance(tags, str):
        import json
        try:
            tags = json.loads(tags)
        except Exception:
            tags = [t.strip() for t in tags.split(",")]
    if source == "linkedin":
        # If already tagged from scraper, trust it
        if "easy_apply" in tags:
            return "Easy Apply"
        # For job detail view, do a live page check for accuracy
        if live_check and job.get("url"):
            return "Easy Apply" if check_linkedin_easy_apply(job["url"]) else "External Site"
        return "External Site"
    if source == "indeed":
        return "Quick Apply"
    return "External Site"


def _date_posted_dt(j):
    date_str = j.get("date_posted") or ""
    if not date_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _date_found_dt(j):
    date_str = j.get("date_found") or ""
    if not date_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


# ── Sidebar ─────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("**Jobs**")
    if st.button("🔄 Refresh Jobs Now", width="stretch", type="primary"):
        if not _PROGRESS_FILE.exists():
            t = threading.Thread(target=_run_scraper_bg, daemon=True)
            t.start()
            st.success("Fetching fresh jobs... check back in ~30 seconds.")
        else:
            st.info("Already refreshing — please wait.")
    st.divider()
    st.header("Filters")
    status_filter = st.selectbox(
        "Status",
        ["All", "new", "reviewed", "applied", "interviewing", "offer", "rejected", "closed"]
    )
    source_filter = st.multiselect(
        "Source",
        ["linkedin", "indeed", "remoteok", "weworkremotely", "google"],
        default=[]
    )
    job_type_filter = st.multiselect(
        "Job Type",
        ["Full Time", "Contract", "Unknown"],
        default=[]
    )
    freshness_filter = st.selectbox(
        "Posted Within",
        ["All time", "10 minutes", "30 minutes", "1 hour", "3 hours", "5 hours",
         "Today", "2 days", "This week"],
        index=0
    )
    location_filter = st.text_input("Location (e.g. USA, Remote, New York)", value="")

    st.divider()

    # Export
    st.markdown("**Export**")
    all_jobs_export = get_jobs(status=None, min_score=0)
    if all_jobs_export:
        export_df = pd.DataFrame(all_jobs_export)
        export_df["applied"] = export_df["status"].apply(lambda x: "Yes" if x == "applied" else "No")
        export_df["response"] = export_df["notes"].apply(
            lambda x: "Yes" if x and any(w in str(x).lower() for w in ["interview", "response", "reply", "callback", "offer"]) else "No"
        )
        export_df["job_type"] = export_df.apply(detect_job_type, axis=1)
        export_df["h1b"] = export_df.apply(detect_h1b, axis=1)
        export_df["apply_type"] = export_df.apply(detect_apply_type, axis=1)

        export_cols = {
            "company": "Company", "title": "Job Title", "score": "AI Score",
            "status": "Status", "applied": "Applied?", "response": "Response?",
            "job_type": "Job Type", "h1b": "H-1B Sponsor?", "apply_type": "Apply Type",
            "source": "Source", "location": "Location", "salary": "Salary",
            "url": "Job Link", "date_found": "Date Found",
            "applied_date": "Date Applied", "notes": "Notes",
        }
        cols_available = [c for c in export_cols if c in export_df.columns]
        export_out = export_df[cols_available].rename(columns=export_cols)

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            export_out.to_excel(writer, index=False, sheet_name="Job Applications")
        st.download_button(label="⬇ Download Excel", data=buffer.getvalue(),
                           file_name="job_applications.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           width="stretch")
        st.download_button(label="⬇ Download CSV", data=export_out.to_csv(index=False),
                           file_name="job_applications.csv", mime="text/csv", width="stretch")

    st.divider()
    st.markdown("**Quick Actions**")
    if st.button("Run Scraper (dry run)", width="stretch"):
        import subprocess, sys
        with st.spinner("Running scraper..."):
            result = subprocess.run(
                [sys.executable, "main.py", "--scrape-only"],
                capture_output=True, text=True, cwd="."
            )
        st.success("Done!")
        st.code(result.stdout[-2000:] if result.stdout else result.stderr[-1000:])

    if st.button("🎓 Scrape Internships Now", width="stretch"):
        with st.spinner("Scraping from LinkedIn, Indeed, Glassdoor, RemoteOK, RSS feeds..."):
            try:
                from scrape_internships import scrape_all_intern_jobs
                from database import insert_job
                intern_raw = scrape_all_intern_jobs()
                added = 0
                for job in intern_raw:
                    job_id = insert_job(job)
                    if job_id is not None:
                        added += 1
                st.success(f"✅ Found {len(intern_raw)} internships, {added} new added. Check the 🎓 Internships tab!")
            except Exception as e:
                st.error(f"Scraper error: {e}")

    if st.button("Check Gmail Inbox", width="stretch"):
        from email_checker import check_gmail
        with st.spinner("Scanning Gmail for job responses..."):
            results = check_gmail(days_back=14)
        found  = [r for r in results if "company" in r]
        errors = [r for r in results if "error" in r]
        infos  = [r for r in results if "info" in r]
        if errors:
            st.error(errors[0]["error"])
        elif infos:
            st.info(infos[0]["info"])
        else:
            st.success(f"Found {len(found)} job-related email(s)!")
            for r in found:
                icon = {"offer": "🎉", "interview": "📅", "rejected": "❌", "follow_up": "📧", "applied_confirmation": "✅"}.get(r["classification"], "📧")
                st.write(f"{icon} **{r['company']}** — {r['classification'].upper()} | {r['subject'][:60]}")
            # Toast popup only for positive responses
            positives = [r for r in found if r["classification"] in ("interview", "offer")]
            for r in positives:
                icon = "🎉" if r["classification"] == "offer" else "📅"
                sender = r.get("sender_name", r.get("sender", ""))[:30]
                st.toast(f"{icon} {r['classification'].upper()} from {r['company']}! ({sender})", icon=icon)
        st.rerun()

    st.divider()
    st.markdown("**Auto Apply**")
    dry_run_toggle = st.checkbox("Dry Run (test only — won't actually submit)", value=True)
    if st.button("🚀 Auto Apply — 5 LinkedIn Easy Apply", width="stretch"):
        from database import get_jobs, update_status
        from auto_apply import apply_to_jobs_batch

        # Pick top 5 LinkedIn jobs not yet applied, sorted by score
        candidate_jobs = get_jobs(status="new", min_score=0)
        candidate_jobs += get_jobs(status="reviewed", min_score=0)
        linkedin_candidates = [
            j for j in candidate_jobs
            if j.get("source") == "linkedin"
            and j.get("url")
            and j.get("status") not in ("applied", "interviewing", "offer", "rejected", "closed")
        ]
        # Sort by score descending, take top 5
        linkedin_candidates.sort(key=lambda j: float(j.get("score") or 0), reverse=True)
        to_apply = linkedin_candidates[:5]

        if not to_apply:
            st.warning("No LinkedIn jobs available to apply to. Run the scraper first.")
        else:
            label = "DRY RUN" if dry_run_toggle else "LIVE"
            st.info(f"[{label}] Applying to {len(to_apply)} LinkedIn Easy Apply jobs...")
            with st.spinner(f"Opening browser and applying... ({label})"):
                results = apply_to_jobs_batch(to_apply, dry_run=dry_run_toggle)

            success_count = sum(1 for r in results if r.get("success"))
            fail_count    = len(results) - success_count

            if not dry_run_toggle:
                for r in results:
                    if r.get("success"):
                        job_id = r["job"].get("id")
                        if job_id:
                            update_status(job_id, "applied", "Applied via Auto Apply (Easy Apply)")

            st.success(f"Done! {success_count} applied, {fail_count} skipped.")
            for r in results:
                j    = r["job"]
                icon = "✅" if r.get("success") else "⚠️"
                st.write(f"{icon} **{j.get('company')}** — {j.get('title')} | {r.get('notes', '')}")
            st.rerun()

    st.divider()
    with st.expander("📋 Changelog", expanded=False):
        st.markdown("""
**v1.9** — Mar 2026
- 🌐 More internship sources: RemoteOK API + Indeed RSS feeds (not just LinkedIn)
- 📄 Internship resume upload + AI generator (no work experience — education/skills/projects only)
- 🔍 Internship tab filters: source, status, search, freshness

**v1.8** — Mar 2026
- 🎓 New Internships tab — scrapes and shows intern-specific jobs from all boards
- 🎓 "Scrape Internships Now" button in sidebar

**v1.7** — Mar 2026
- 🔧 Fixed false-positive interview detections from emails
- 🎨 Color legend added above job board table

**v1.6** — Mar 2026
- 🔄 "Refresh Jobs Now" button in sidebar
- ⏱ Auto-scrape reduced to every 30 min

**v1.5** — Mar 2026
- 📧 Auto Gmail check every hour in background
- 🔗 LinkedIn application confirmation emails auto-mark as Applied
- 🚫 Improved rejection email detection (indirect language)

**v1.4** — Mar 2026
- 🎨 Row color highlighting by status in job board
- ✅ "Mark as Applied" now sets applied date correctly
- 👁 Jobs auto-marked as Reviewed when opened

**v1.3** — Mar 2026
- 🤖 Auto Apply button for LinkedIn Easy Apply jobs
- 🏷 Accurate Easy Apply vs External Site detection

**v1.2** — Mar 2026
- 📬 Gmail inbox scanner for job responses
- 🕐 Jobs stay visible after 8 hours if reviewed/applied

**v1.1** — Mar 2026
- 📊 AI scoring with Groq
- 🗄 Supabase cloud database

**v1.0** — Mar 2026
- 🚀 Initial launch — job scraper + dashboard
        """)


# ── Tabs ─────────────────────────────────────────────────────────────────────────
main_tab, tracker_tab, intern_tab = st.tabs(["🔍 Job Board", "📊 My Applications", "🎓 Internships"])


# ══════════════════════════════════════════════════════════════════════════════════
# TAB 1: JOB BOARD
# ══════════════════════════════════════════════════════════════════════════════════
with main_tab:
    stats = get_stats()
    by_status = stats.get("by_status", {})

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("Total Jobs", stats["total"])
    col2.metric("New", by_status.get("new", 0))
    col3.metric("Reviewed", by_status.get("reviewed", 0))
    col4.metric("Applied", by_status.get("applied", 0))
    col5.metric("Interviewing", by_status.get("interviewing", 0))
    col6.metric("Avg AI Score", stats["avg_score"])

    st.divider()

    # Load and filter jobs
    status_param = None if status_filter == "All" else status_filter
    jobs = get_jobs(status=status_param, min_score=0)

    if source_filter:
        jobs = [j for j in jobs if j.get("source") in source_filter]

    for j in jobs:
        j["job_type"]   = detect_job_type(j)
        j["apply_type"] = detect_apply_type(j)
        j["posted"]     = posted_age(j)

    if job_type_filter:
        jobs = [j for j in jobs if j["job_type"] in job_type_filter]

    # Location filter — text search against job location field
    if location_filter.strip():
        loc_q = location_filter.strip().lower()
        jobs = [j for j in jobs if loc_q in (j.get("location") or "").lower()]

    # Auto-remove NEW jobs posted more than 8 hours ago (keep reviewed/applied always)
    now_utc = datetime.now(timezone.utc)
    jobs = [
        j for j in jobs
        if j.get("status") not in ("new",)
        or _date_posted_dt(j) == datetime.min.replace(tzinfo=timezone.utc)
        or (now_utc - _date_posted_dt(j)).total_seconds() <= 8 * 3600
    ]

    # Sort by date_posted newest first
    jobs.sort(key=lambda j: (_date_posted_dt(j), _date_found_dt(j)), reverse=True)

    # Freshness filter — based on date_found (when we scraped it)
    if freshness_filter != "All time":
        minutes_map = {
            "10 minutes": 10,
            "30 minutes": 30,
            "1 hour":     60,
            "3 hours":    180,
            "5 hours":    300,
            "Today":      1440,
            "2 days":     2880,
            "This week":  10080,
        }
        max_minutes = minutes_map.get(freshness_filter, 99999)
        jobs = [
            j for j in jobs
            if (now_utc - _date_found_dt(j)).total_seconds() / 60 <= max_minutes
        ]

    if not jobs:
        st.info("No jobs found matching filters.")
        st.stop()

    # Add Applied? and Response? columns
    for j in jobs:
        j["applied?"] = "Yes" if j.get("status") in ("applied", "interviewing", "offer") else "No"
        notes_text = (j.get("notes") or "").lower()
        if j.get("status") == "offer":
            j["response?"] = "Offer"
        elif j.get("status") == "interviewing" or "interview" in notes_text:
            j["response?"] = "Interview"
        elif j.get("status") == "rejected" or any(w in notes_text for w in ["reject", "not moving", "unfortunately"]):
            j["response?"] = "Rejected"
        elif any(w in notes_text for w in ["response", "reply", "callback", "follow", "[auto]"]):
            j["response?"] = "Reply"
        else:
            j["response?"] = "—"

    df = pd.DataFrame(jobs)
    display_cols = ["id", "title", "company", "posted", "applied?", "response?",
                    "job_type", "apply_type", "source", "location", "salary", "status"]
    display_cols = [c for c in display_cols if c in df.columns]
    df_display = df[display_cols].copy()

    def color_score(val):
        if not val:
            return ""
        if val >= 8:
            return "background-color: #bbf7d0; color: #14532d; font-weight: bold"
        elif val >= 6:
            return "background-color: #bfdbfe; color: #1e3a8a"
        return "background-color: #fee2e2; color: #7f1d1d"

    def color_h1b(val):
        if val == "Yes": return "color: #15803d; font-weight: bold"
        if val == "No":  return "color: #dc2626"
        return ""

    def color_apply_type(val):
        if val == "Easy Apply":  return "color: #15803d; font-weight: bold"
        if val == "Quick Apply": return "color: #1d4ed8; font-weight: bold"
        return "color: #6b7280"

    def color_applied(val):
        if val == "Yes": return "color: #15803d; font-weight: bold"
        return "color: #9ca3af"

    def color_response(val):
        if val == "Offer":     return "background-color: #bbf7d0; color: #14532d; font-weight: bold"
        if val == "Interview": return "background-color: #bfdbfe; color: #1e3a8a; font-weight: bold"
        if val == "Rejected":  return "background-color: #fee2e2; color: #7f1d1d"
        if val == "Reply":     return "color: #92400e; font-weight: bold"
        return "color: #9ca3af"

    def highlight_row(row):
        """Color entire row based on job status so it's instantly visible."""
        status = row.get("status", "") if hasattr(row, "get") else ""
        row_len = len(row)
        if status == "offer":        return ["background-color: #bbf7d0"] * row_len  # green
        if status == "interviewing": return ["background-color: #bfdbfe"] * row_len  # blue
        if status == "applied":      return ["background-color: #fef9c3"] * row_len  # yellow
        if status == "reviewed":     return ["background-color: #f3e8ff"] * row_len  # lavender
        if status == "rejected":     return ["background-color: #ffe4e6"] * row_len  # pink/red
        return [""] * row_len

    styled = df_display.style\
        .apply(highlight_row, axis=1)\
        .map(color_apply_type, subset=["apply_type"])\
        .map(color_posted_age, subset=["posted"])\
        .map(color_applied,    subset=["applied?"])\
        .map(color_response,   subset=["response?"])

    st.markdown(
        "<small>"
        "<span style='background:#fef9c3;padding:2px 7px;border-radius:3px;margin-right:6px'>🟡 Applied</span>"
        "<span style='background:#bfdbfe;padding:2px 7px;border-radius:3px;margin-right:6px'>🔵 Interviewing</span>"
        "<span style='background:#bbf7d0;padding:2px 7px;border-radius:3px;margin-right:6px'>🟢 Offer</span>"
        "<span style='background:#f3e8ff;padding:2px 7px;border-radius:3px;margin-right:6px'>🟣 Reviewed</span>"
        "<span style='background:#ffe4e6;padding:2px 7px;border-radius:3px'>🔴 Rejected</span>"
        "</small>",
        unsafe_allow_html=True
    )
    st.dataframe(styled, width="stretch", height=400)
    st.caption(f"Showing {len(jobs)} jobs")

    st.divider()

    # ── Job Detail ──────────────────────────────────────────────────────────────
    st.subheader("Job Detail")

    job_keys = [f"#{j['id']} — {j['title']} @ {j['company']}" for j in jobs]
    job_ids  = [j['id'] for j in jobs]

    if job_keys:
        if "job_index" not in st.session_state:
            st.session_state.job_index = 0
        st.session_state.job_index = min(st.session_state.job_index, len(job_keys) - 1)

        def _on_select():
            st.session_state.job_index = job_keys.index(st.session_state.job_select)

        nav_col, drop_col = st.columns([1, 6])
        with nav_col:
            btn_prev, btn_next = st.columns(2)
            if btn_prev.button("◀", help="Previous job"):
                st.session_state.job_index = max(0, st.session_state.job_index - 1)
                st.session_state.job_select = job_keys[st.session_state.job_index]
            if btn_next.button("▶", help="Next job"):
                st.session_state.job_index = min(len(job_keys) - 1, st.session_state.job_index + 1)
                st.session_state.job_select = job_keys[st.session_state.job_index]
        with drop_col:
            st.selectbox("Select a job to view details:", job_keys,
                         index=st.session_state.job_index, key="job_select",
                         on_change=_on_select)

        selected_id = job_ids[st.session_state.job_index]
    else:
        selected_id = None

    job = get_job_by_id(int(selected_id)) if selected_id else None

    if job:
        job["job_type"]   = detect_job_type(job)
        job["apply_type"] = detect_apply_type(job, live_check=True)
        job["posted"]     = posted_age(job)

        # Auto-mark as "reviewed" the first time a new job is viewed
        if job.get("status") == "new":
            _last_reviewed = st.session_state.get("_last_reviewed_id")
            if _last_reviewed != job["id"]:
                update_status(job["id"], "reviewed", job.get("notes", "") or "")
                st.session_state["_last_reviewed_id"] = job["id"]
                job["status"] = "reviewed"  # update local copy so UI reflects it

        col_a, col_b = st.columns([2, 1])
        with col_a:
            st.markdown(f"### {job['title']}")
            st.markdown(f"**{job['company']}** · {job['location']} · {job['source']}")

            bc1, bc2, bc3, bc4, bc5 = st.columns(5)
            bc1.info(f"**Posted:** {job['posted']}")
            bc2.info(f"**Type:** {job['job_type']}")
            bc3.info(f"**Apply:** {job['apply_type']}")
            if job.get("salary"):  bc4.info(f"**Salary:** {job['salary']}")
            applicants = job.get("num_applicants", "")
            if applicants:         bc5.info(f"**Applicants:** {applicants}")

            st.markdown("---")
            current_status = job.get("status", "new")
            apply_label = "Apply via Easy Apply (LinkedIn)" if job["apply_type"] == "Easy Apply" else \
                          "Apply via Quick Apply (Indeed)"  if job["apply_type"] == "Quick Apply"  else \
                          "Go to Job Page & Apply"

            if current_status not in ("applied", "interviewing", "offer"):
                # Single button: marks as applied AND shows the link to click
                if st.button(f"🚀 {apply_label} — Mark as Applied", width="stretch", type="primary"):
                    mark_applied(job["id"], "Applied via dashboard")
                    st.session_state["_open_url"] = job["url"]
                    st.rerun()
                st.caption("Click above to mark as applied, then open the job link that appears.")
            else:
                st.success(f"✅ Status: {current_status.upper()}")
                st.link_button("🔗 View Job Page", job["url"])

            # Show job URL link after marking applied (persists until next job selected)
            if st.session_state.get("_open_url") == job["url"]:
                st.info("✅ Marked as Applied! Now open the job page:")
                st.link_button("→ Open Job Page Now", job["url"], width="stretch")
                if st.button("Done, close link", key="close_link"):
                    st.session_state.pop("_open_url", None)
                    st.rerun()

        with col_b:
            st.markdown("**Update Status**")
            statuses = ["new", "reviewed", "applied", "interviewing", "offer", "rejected", "closed"]
            cur_idx = statuses.index(job.get("status", "new")) if job.get("status") in statuses else 0
            new_status = st.selectbox("New status", statuses,
                                      index=cur_idx,
                                      key=f"status_select_{job['id']}")
            notes = st.text_input("Notes", value=job.get("notes", "") or "")
            if st.button("Save Status"):
                update_status(job["id"], new_status, notes)
                st.success("Updated!")
                st.rerun()

        tabs = st.tabs(["Description", "Cover Letter", "Resume"])
        with tabs[0]:
            desc = job.get("description") or ""
            st.text(desc if desc and desc.lower() != "nan" else "No description available")
        with tabs[1]:
            cover = job.get("cover_letter", "")
            if cover:
                st.text_area("Cover Letter", value=cover, height=300, key="cl_view")
                if st.button("Copy to clipboard"):
                    st.code(cover)
            else:
                st.info("No cover letter generated yet.")
        with tabs[2]:
            from ai_engine import generate_tailored_resume
            from resume_builder import build_resume_docx
            st.markdown("Generate a tailored ATS-optimized resume for this specific job.")
            if st.button("Generate Tailored Resume", width="stretch"):
                with st.spinner("AI is tailoring your resume..."):
                    tailored     = generate_tailored_resume(job)
                    resume_bytes = build_resume_docx(job, tailored)
                st.success("Resume ready!")
                safe_co    = "".join(c for c in job.get("company", "company") if c.isalnum() or c in "-_")
                safe_title = "".join(c for c in job.get("title", "role")    if c.isalnum() or c in "-_")
                st.download_button(label="⬇ Download Resume (.docx)",
                                   data=resume_bytes,
                                   file_name=f"Resume_{safe_co}_{safe_title}.docx",
                                   mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                   width="stretch")
                if tailored.get("extra_bullets"):
                    with st.expander("Preview: New ATS Bullets"):
                        for b in tailored["extra_bullets"]:
                            st.markdown(f"• {b}")
                if tailored.get("priority_skills"):
                    with st.expander("Preview: Skills Reordered"):
                        st.write("  •  ".join(tailored["priority_skills"]) + "  (+ all your other skills)")
    else:
        st.warning("Job not found.")


# ══════════════════════════════════════════════════════════════════════════════════
# TAB 2: MY APPLICATIONS
# ══════════════════════════════════════════════════════════════════════════════════
with tracker_tab:
    all_jobs = get_jobs(status=None, min_score=0)

    applied     = [j for j in all_jobs if j.get("status") in ("applied", "interviewing", "offer", "rejected")]
    interviews  = [j for j in all_jobs if j.get("status") == "interviewing"]
    offers      = [j for j in all_jobs if j.get("status") == "offer"]
    rejected    = [j for j in all_jobs if j.get("status") == "rejected"]
    no_response = [j for j in all_jobs if j.get("status") == "applied"]

    # Summary metrics
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Total Applied", len(applied))
    m2.metric("Responses", len(interviews) + len(offers) + len(rejected))
    m3.metric("Interviews", len(interviews))
    m4.metric("Offers", len(offers))
    m5.metric("Rejected", len(rejected))

    st.divider()

    # ── Positive responses (lilac/purple) ────────────────────────────────────
    positive = offers + interviews
    st.markdown(
        f"""<div style='background:#ede9fe; border-left:5px solid #7c3aed;
        padding:14px 20px; border-radius:8px; margin-bottom:12px;'>
        <b style='color:#4c1d95; font-size:16px'>
        Positive Responses &nbsp;✨&nbsp; {len(positive)} job(s)</b></div>""",
        unsafe_allow_html=True
    )
    if positive:
        for j in positive:
            tag          = "🎉 OFFER" if j.get("status") == "offer" else "📅 INTERVIEW"
            notes_raw    = (j.get("notes") or "")
            applied_date = (j.get("applied_date") or "")[:10]
            # Extract sender name from auto-note if present
            sender_name  = ""
            for line in notes_raw.splitlines():
                if "From:" in line:
                    sender_name = line.split("From:")[-1].split("|")[0].strip()
                    break
            notes_display = notes_raw.replace("\n", " ")[:120]
            meta = " &nbsp;|&nbsp; ".join(filter(None, [
                f"Applied: {applied_date}" if applied_date else "",
                f"From: <b>{sender_name}</b>" if sender_name else "",
            ]))
            st.markdown(
                f"""<div style='background:#f5f3ff; border:1px solid #c4b5fd;
                padding:10px 16px; border-radius:6px; margin-bottom:6px;'>
                <b style='color:#6d28d9'>{tag}</b> &nbsp;
                <b>{j['company']}</b> — {j['title']}<br>
                <small style='color:#7c3aed'>{meta}</small><br>
                <small style='color:#9ca3af'>{notes_display}</small></div>""",
                unsafe_allow_html=True
            )
    else:
        st.markdown("<p style='color:#7c3aed; font-style:italic'>No positive responses yet — keep going!</p>",
                    unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Rejections (pink/red) ─────────────────────────────────────────────────
    st.markdown(
        f"""<div style='background:#ffe4e6; border-left:5px solid #e11d48;
        padding:14px 20px; border-radius:8px; margin-bottom:12px;'>
        <b style='color:#9f1239; font-size:16px'>
        Rejections &nbsp;❌&nbsp; {len(rejected)} job(s)</b></div>""",
        unsafe_allow_html=True
    )
    if rejected:
        for j in rejected:
            notes_raw    = (j.get("notes") or "")
            applied_date = (j.get("applied_date") or "")[:10]
            sender_name  = ""
            for line in notes_raw.splitlines():
                if "From:" in line:
                    sender_name = line.split("From:")[-1].split("|")[0].strip()
                    break
            meta = " &nbsp;|&nbsp; ".join(filter(None, [
                f"Applied: {applied_date}" if applied_date else "",
                f"From: <b>{sender_name}</b>" if sender_name else "",
            ]))
            st.markdown(
                f"""<div style='background:#fff1f2; border:1px solid #fda4af;
                padding:10px 16px; border-radius:6px; margin-bottom:6px;'>
                <b style='color:#be123c'>❌ REJECTED</b> &nbsp;
                <b>{j['company']}</b> — {j['title']}<br>
                <small style='color:#e11d48'>{meta}</small></div>""",
                unsafe_allow_html=True
            )
    else:
        st.markdown("<p style='color:#e11d48; font-style:italic'>No rejections recorded yet.</p>",
                    unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Awaiting response (gray) ──────────────────────────────────────────────
    st.markdown(
        f"""<div style='background:#f1f5f9; border-left:5px solid #94a3b8;
        padding:14px 20px; border-radius:8px; margin-bottom:12px;'>
        <b style='color:#475569; font-size:16px'>
        Awaiting Response &nbsp;⏳&nbsp; {len(no_response)} job(s)</b></div>""",
        unsafe_allow_html=True
    )
    if no_response:
        for j in no_response:
            applied_date = (j.get("applied_date") or "")[:10]
            notes_raw    = (j.get("notes") or "")
            sender_name  = ""
            for line in notes_raw.splitlines():
                if "From:" in line:
                    sender_name = line.split("From:")[-1].split("|")[0].strip()
                    break
            meta = " &nbsp;|&nbsp; ".join(filter(None, [
                f"Applied: <b>{applied_date}</b>" if applied_date else "Applied: unknown",
                f"Contact: {sender_name}" if sender_name else "",
            ]))
            st.markdown(
                f"""<div style='background:#f8fafc; border:1px solid #cbd5e1;
                padding:10px 16px; border-radius:6px; margin-bottom:6px;'>
                <b style='color:#64748b'>⏳ WAITING</b> &nbsp;
                <b>{j['company']}</b> — {j['title']}<br>
                <small style='color:#94a3b8'>{meta}</small>
                </div>""",
                unsafe_allow_html=True
            )
    else:
        st.markdown("<p style='color:#64748b; font-style:italic'>No pending applications.</p>",
                    unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════════
# TAB 3: INTERNSHIPS
# ══════════════════════════════════════════════════════════════════════════════════
with intern_tab:
    st.markdown(
        "<div style='background:#f0fdf4; border-left:5px solid #16a34a; "
        "padding:14px 20px; border-radius:8px; margin-bottom:16px;'>"
        "<b style='color:#14532d; font-size:16px'>🎓 Internship Jobs</b><br>"
        "<small style='color:#166534'>Scraped from LinkedIn, Indeed, Glassdoor, ZipRecruiter, "
        "<b>RemoteOK</b>, and <b>Indeed RSS feeds</b>. "
        "Click <b>🎓 Scrape Internships Now</b> in the sidebar to fetch fresh listings.</small></div>",
        unsafe_allow_html=True
    )

    # ── Internship Resume Section ────────────────────────────────────────────────
    _INTERN_RESUME_PATH = Path(__file__).parent / "intern_resume.pdf"
    _INTERN_RESUME_DOCX_PATH = Path(__file__).parent / "intern_resume.docx"

    with st.expander("📄 My Internship Resume", expanded=False):
        st.markdown(
            "Upload a resume **without work experience** — tailored for internship applications "
            "(education, skills, projects only). This will be used when generating tailored internship resumes."
        )
        uploaded_resume = st.file_uploader(
            "Upload your internship resume (PDF or DOCX)",
            type=["pdf", "docx"],
            key="intern_resume_upload"
        )
        if uploaded_resume:
            save_path = _INTERN_RESUME_PATH if uploaded_resume.name.endswith(".pdf") else _INTERN_RESUME_DOCX_PATH
            save_path.write_bytes(uploaded_resume.read())
            st.success(f"✅ Saved as `{save_path.name}` — will be used for internship applications.")

        # Show download button if a resume is already saved
        if _INTERN_RESUME_PATH.exists():
            st.download_button(
                label="⬇ Download saved internship resume (PDF)",
                data=_INTERN_RESUME_PATH.read_bytes(),
                file_name="intern_resume.pdf",
                mime="application/pdf",
                key="dl_intern_pdf"
            )
        if _INTERN_RESUME_DOCX_PATH.exists():
            st.download_button(
                label="⬇ Download saved internship resume (DOCX)",
                data=_INTERN_RESUME_DOCX_PATH.read_bytes(),
                file_name="intern_resume.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key="dl_intern_docx"
            )
        if not _INTERN_RESUME_PATH.exists() and not _INTERN_RESUME_DOCX_PATH.exists():
            st.info("No internship resume uploaded yet. Upload one above, or use 'Generate AI Resume' in the job detail below.")

    st.divider()

    # Load and filter
    all_jobs_intern = get_jobs(status=None, min_score=0)
    _INTERN_WORDS = ("intern", "internship", "trainee", "co-op", "coop")
    intern_jobs = [
        j for j in all_jobs_intern
        if any(w in (j.get("title", "") or "").lower() for w in _INTERN_WORDS)
    ]

    for j in intern_jobs:
        j["job_type"]   = detect_job_type(j)
        j["apply_type"] = detect_apply_type(j)
        j["posted"]     = posted_age(j)
        j["applied?"]   = "Yes" if j.get("status") in ("applied", "interviewing", "offer") else "No"

    # Filters row
    icol1, icol2, icol3, icol4 = st.columns(4)
    with icol1:
        intern_source = st.multiselect(
            "Source",
            ["linkedin", "indeed", "glassdoor", "zip_recruiter", "remoteok"],
            default=[], key="intern_source"
        )
    with icol2:
        intern_status = st.selectbox(
            "Status", ["All", "new", "reviewed", "applied", "rejected"], key="intern_status"
        )
    with icol3:
        intern_search = st.text_input("Search title / company", value="", key="intern_search")
    with icol4:
        intern_fresh = st.selectbox(
            "Posted Within",
            ["All time", "1 day", "3 days", "This week"],
            key="intern_fresh"
        )

    if intern_source:
        intern_jobs = [j for j in intern_jobs if j.get("source") in intern_source]
    if intern_status != "All":
        intern_jobs = [j for j in intern_jobs if j.get("status") == intern_status]
    if intern_search.strip():
        q = intern_search.strip().lower()
        intern_jobs = [
            j for j in intern_jobs
            if q in (j.get("title", "") or "").lower()
            or q in (j.get("company", "") or "").lower()
        ]
    if intern_fresh != "All time":
        _fresh_map = {"1 day": 1440, "3 days": 4320, "This week": 10080}
        _fresh_min = _fresh_map[intern_fresh]
        _now_utc   = datetime.now(timezone.utc)
        intern_jobs = [
            j for j in intern_jobs
            if (_now_utc - _date_found_dt(j)).total_seconds() / 60 <= _fresh_min
        ]

    intern_jobs.sort(key=lambda j: (_date_posted_dt(j), _date_found_dt(j)), reverse=True)

    # Metrics
    im1, im2, im3, im4, im5 = st.columns(5)
    im1.metric("Total", len(intern_jobs))
    im2.metric("LinkedIn", sum(1 for j in intern_jobs if j.get("source") == "linkedin"))
    im3.metric("Indeed", sum(1 for j in intern_jobs if j.get("source") == "indeed"))
    im4.metric("RemoteOK", sum(1 for j in intern_jobs if j.get("source") == "remoteok"))
    im5.metric("Applied", sum(1 for j in intern_jobs if j.get("status") in ("applied", "interviewing", "offer")))

    if not intern_jobs:
        st.info(
            "No internship jobs found yet. Click **🎓 Scrape Internships Now** in the sidebar to fetch listings.",
            icon="🎓"
        )
    else:
        idf = pd.DataFrame(intern_jobs)
        intern_display_cols = ["id", "title", "company", "posted", "applied?",
                               "apply_type", "source", "location", "salary", "status"]
        intern_display_cols = [c for c in intern_display_cols if c in idf.columns]
        idf_display = idf[intern_display_cols].copy()

        styled_intern = idf_display.style\
            .apply(highlight_row, axis=1)\
            .map(color_apply_type, subset=["apply_type"] if "apply_type" in idf_display.columns else [])\
            .map(color_posted_age, subset=["posted"] if "posted" in idf_display.columns else [])\
            .map(color_applied,    subset=["applied?"] if "applied?" in idf_display.columns else [])

        st.dataframe(styled_intern, width="stretch", height=380)
        st.caption(f"Showing {len(intern_jobs)} internship jobs")

        st.divider()

        # ── Internship Job Detail ────────────────────────────────────────────────
        st.subheader("Internship Detail")

        ikeys = [f"#{j['id']} — {j['title']} @ {j['company']}" for j in intern_jobs]
        iids  = [j["id"] for j in intern_jobs]

        if "intern_job_index" not in st.session_state:
            st.session_state.intern_job_index = 0
        st.session_state.intern_job_index = min(st.session_state.intern_job_index, len(ikeys) - 1)

        def _on_intern_select():
            st.session_state.intern_job_index = ikeys.index(st.session_state.intern_job_select)

        inav_col, idrop_col = st.columns([1, 6])
        with inav_col:
            ibtn_prev, ibtn_next = st.columns(2)
            if ibtn_prev.button("◀", key="intern_prev", help="Previous internship"):
                st.session_state.intern_job_index = max(0, st.session_state.intern_job_index - 1)
                st.session_state.intern_job_select = ikeys[st.session_state.intern_job_index]
            if ibtn_next.button("▶", key="intern_next", help="Next internship"):
                st.session_state.intern_job_index = min(len(ikeys) - 1, st.session_state.intern_job_index + 1)
                st.session_state.intern_job_select = ikeys[st.session_state.intern_job_index]
        with idrop_col:
            st.selectbox("Select an internship to view details:", ikeys,
                         index=st.session_state.intern_job_index, key="intern_job_select",
                         on_change=_on_intern_select)

        selected_intern_id = iids[st.session_state.intern_job_index]
        ijob = get_job_by_id(int(selected_intern_id))

        if ijob:
            ijob["job_type"]   = detect_job_type(ijob)
            ijob["apply_type"] = detect_apply_type(ijob, live_check=True)
            ijob["posted"]     = posted_age(ijob)

            icola, icolb = st.columns([2, 1])
            with icola:
                st.markdown(f"### {ijob['title']}")
                st.markdown(f"**{ijob['company']}** · {ijob['location']} · {ijob['source']}")

                ibc1, ibc2, ibc3, ibc4 = st.columns(4)
                ibc1.info(f"**Posted:** {ijob['posted']}")
                ibc2.info(f"**Type:** {ijob['job_type']}")
                ibc3.info(f"**Apply:** {ijob['apply_type']}")
                if ijob.get("salary"): ibc4.info(f"**Salary:** {ijob['salary']}")

                st.markdown("---")
                if ijob.get("status") not in ("applied", "interviewing", "offer"):
                    if st.button("✅ I Applied — Mark as Applied", key="intern_mark_applied",
                                 width="stretch", type="primary"):
                        mark_applied(ijob["id"], "Manually applied via Internships tab")
                        st.session_state["_intern_open_url"] = ijob["url"]
                        st.rerun()

                    if st.session_state.get("_intern_open_url") == ijob["url"]:
                        st.info("✅ Marked as Applied! Open the job page:")
                        st.link_button("→ Open Job Page Now", ijob["url"], width="stretch")
                        if st.button("Done, close link", key="intern_close_link"):
                            st.session_state.pop("_intern_open_url", None)
                            st.rerun()
                    else:
                        st.link_button("🚀 Go to Job Page", ijob["url"])
                else:
                    st.success(f"✅ Status: {ijob['status'].upper()}")
                    st.link_button("🔗 View Job Page", ijob["url"])

            with icolb:
                st.markdown("**Update Status**")
                istatuses = ["new", "reviewed", "applied", "interviewing", "offer", "rejected", "closed"]
                icur_idx = istatuses.index(ijob.get("status", "new")) if ijob.get("status") in istatuses else 0
                inew_status = st.selectbox("New status", istatuses, index=icur_idx,
                                           key=f"intern_status_select_{ijob['id']}")
                inotes = st.text_input("Notes", value=ijob.get("notes", "") or "", key="intern_notes")
                if st.button("Save Status", key="intern_save_status"):
                    update_status(ijob["id"], inew_status, inotes)
                    st.success("Updated!")
                    st.rerun()

            # ── Tabs: Description / Internship Resume ──────────────────────────
            itabs = st.tabs(["📄 Description", "📝 Internship Resume"])

            with itabs[0]:
                desc = ijob.get("description") or ""
                st.text(desc if desc and desc.lower() != "nan" else "No description available")

            with itabs[1]:
                st.markdown(
                    "Generate an internship-friendly resume for this job — **no work experience**, "
                    "just education, skills, and projects tailored to this role. "
                    "Perfect for companies that won't consider candidates with full-time experience."
                )
                # If user already uploaded an internship resume, offer that first
                if _INTERN_RESUME_PATH.exists():
                    st.download_button(
                        label="⬇ Download My Uploaded Internship Resume (PDF)",
                        data=_INTERN_RESUME_PATH.read_bytes(),
                        file_name="intern_resume.pdf",
                        mime="application/pdf",
                        key=f"dl_up_pdf_{ijob['id']}"
                    )
                if _INTERN_RESUME_DOCX_PATH.exists():
                    st.download_button(
                        label="⬇ Download My Uploaded Internship Resume (DOCX)",
                        data=_INTERN_RESUME_DOCX_PATH.read_bytes(),
                        file_name="intern_resume.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"dl_up_docx_{ijob['id']}"
                    )

                st.markdown("---")
                st.markdown("**Or generate an AI-tailored version for this specific job:**")
                if st.button("🤖 Generate AI Internship Resume", key=f"gen_intern_res_{ijob['id']}",
                             width="stretch"):
                    with st.spinner("AI is tailoring your internship resume..."):
                        from ai_engine import generate_tailored_resume
                        from resume_builder import build_intern_resume_docx
                        tailored = generate_tailored_resume(ijob)
                        resume_bytes = build_intern_resume_docx(ijob, tailored)
                    st.success("Internship resume ready! (No work experience — education, skills & projects only)")
                    safe_co    = "".join(c for c in (ijob.get("company", "company") or "") if c.isalnum() or c in "-_")
                    safe_title = "".join(c for c in (ijob.get("title", "intern") or "")  if c.isalnum() or c in "-_")
                    st.download_button(
                        label="⬇ Download Internship Resume (.docx)",
                        data=resume_bytes,
                        file_name=f"InternResume_{safe_co}_{safe_title}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"dl_gen_intern_{ijob['id']}",
                        width="stretch"
                    )
                    if tailored.get("extra_bullets"):
                        with st.expander("Preview: New ATS Bullets (added to Projects)"):
                            for b in tailored["extra_bullets"]:
                                st.markdown(f"• {b}")
                    if tailored.get("priority_skills"):
                        with st.expander("Preview: Skills Reordered"):
                            st.write("  •  ".join(tailored["priority_skills"]) + "  (+ all your other skills)")
