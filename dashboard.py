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
from database import get_jobs, get_stats, update_status, mark_applied, get_job_by_id

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
        return (datetime.now() - last).total_seconds() > 2 * 3600
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
        _STAMP_FILE.write_text(datetime.now().isoformat())
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

st.title("💼 Job Application Tracker")

if _PROGRESS_FILE.exists():
    st.info("🔄 Fetching fresh jobs... page will auto-refresh shortly.", icon="🔄")
    st.markdown('<meta http-equiv="refresh" content="20">', unsafe_allow_html=True)
elif _STAMP_FILE.exists():
    try:
        last_dt = datetime.fromisoformat(_STAMP_FILE.read_text().strip())
        st.success(f"✅ Jobs last updated at {last_dt.strftime('%I:%M %p')} — next refresh in 2 hours.", icon="✅")
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
    date_str = job.get("date_posted", "") or job.get("date_found", "")
    if not date_str:
        return "Unknown"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = now - dt
        hours = int(diff.total_seconds() / 3600)
        if hours < 1:
            return "Just posted"
        if hours < 24:
            return f"{hours}h ago"
        days = diff.days
        if days < 7:
            return f"{days}d ago"
        return f"{days // 7}w ago"
    except Exception:
        return "Unknown"


def color_posted_age(val: str) -> str:
    if "Just posted" in val or ("h ago" in val and int(val.replace("h ago", "").strip() or 99) <= 6):
        return "color: #15803d; font-weight: bold"
    if "h ago" in val:
        return "color: #1d4ed8"
    if "d ago" in val:
        days = int(val.replace("d ago", "").strip() or 99)
        if days <= 3:
            return "color: #b45309"
        return "color: #dc2626"
    return ""


def detect_apply_type(job: dict) -> str:
    url = (job.get("url", "") or "").lower()
    source = (job.get("source", "") or "").lower()
    if source == "linkedin" and "linkedin.com/jobs" in url:
        return "Easy Apply"
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
    st.header("Filters")
    status_filter = st.selectbox(
        "Status",
        ["All", "new", "reviewed", "applied", "interviewing", "offer", "rejected", "closed"]
    )
    min_score = st.slider("Min AI Score", 0.0, 10.0, 0.0, 0.5)
    source_filter = st.multiselect(
        "Source",
        ["linkedin", "indeed", "remoteok", "weworkremotely"],
        default=[]
    )
    job_type_filter = st.multiselect(
        "Job Type",
        ["Full Time", "Contract", "Unknown"],
        default=[]
    )
    h1b_filter = st.selectbox("H-1B Sponsorship", ["All", "Yes", "No", "Unknown"])
    freshness_filter = st.selectbox(
        "Scraped",
        ["All time", "Today", "Last 2 days", "Last 7 days"],
        index=0
    )

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
                icon = {"offer": "🎉", "interview": "📅", "rejected": "❌", "follow_up": "📧"}.get(r["classification"], "📧")
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


# ── Tabs ─────────────────────────────────────────────────────────────────────────
main_tab, tracker_tab = st.tabs(["🔍 Job Board", "📊 My Applications"])


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
    jobs = get_jobs(status=status_param, min_score=min_score)

    if source_filter:
        jobs = [j for j in jobs if j.get("source") in source_filter]

    for j in jobs:
        j["job_type"]  = detect_job_type(j)
        j["h1b"]       = detect_h1b(j)
        j["apply_type"] = detect_apply_type(j)
        j["posted"]    = posted_age(j)

    if job_type_filter:
        jobs = [j for j in jobs if j["job_type"] in job_type_filter]
    if h1b_filter != "All":
        jobs = [j for j in jobs if j["h1b"] == h1b_filter]

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

    if freshness_filter != "All time":
        days_map = {"Today": 0, "Last 2 days": 1, "Last 7 days": 6}
        max_days = days_map[freshness_filter]
        today = datetime.now(timezone.utc).date()
        jobs = [j for j in jobs if (today - _date_found_dt(j).date()).days <= max_days]

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
                    "job_type", "h1b", "apply_type", "source", "salary", "score", "status"]
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

    styled = df_display.style\
        .map(color_score,      subset=["score"])\
        .map(color_h1b,        subset=["h1b"])\
        .map(color_apply_type, subset=["apply_type"])\
        .map(color_posted_age, subset=["posted"])\
        .map(color_applied,    subset=["applied?"])\
        .map(color_response,   subset=["response?"])

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
        job["job_type"]  = detect_job_type(job)
        job["h1b"]       = detect_h1b(job)
        job["apply_type"] = detect_apply_type(job)
        job["posted"]    = posted_age(job)

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
            if job["h1b"] == "Yes":   bc4.success("H-1B: Sponsors")
            elif job["h1b"] == "No":  bc4.error("H-1B: No Sponsor")
            else:                     bc4.warning("H-1B: Unknown")
            if job.get("salary"):     bc5.info(f"**Salary:** {job['salary']}")

            if job.get("score"):       st.markdown(f"**AI Score:** {job['score']}/10")
            if job.get("score_reason"): st.info(f"AI reasoning: {job['score_reason']}")

            st.markdown("---")
            apply_label = "Apply via Easy Apply (LinkedIn)" if job["apply_type"] == "Easy Apply" else \
                          "Apply via Quick Apply (Indeed)"  if job["apply_type"] == "Quick Apply"  else \
                          "Go to Job Page & Apply"
            link_col, mark_col = st.columns([3, 2])
            with link_col:
                st.link_button(f"🚀 {apply_label}", job["url"], width="stretch")
            with mark_col:
                current_status = job.get("status", "new")
                if current_status not in ("applied", "interviewing", "offer"):
                    if st.button("✅ I Applied — Mark as Applied", width="stretch"):
                        mark_applied(job["id"], "Manually applied")
                        st.success("Marked as applied!")
                        st.rerun()
                else:
                    st.success(f"Status: {current_status.upper()}")

        with col_b:
            st.markdown("**Update Status**")
            statuses = ["new", "reviewed", "applied", "interviewing", "offer", "rejected", "closed"]
            cur_idx = statuses.index(job.get("status", "new")) if job.get("status") in statuses else 0
            new_status = st.selectbox("New status", statuses,
                                      index=cur_idx,
                                      key="status_select")
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
