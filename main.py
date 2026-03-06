"""
Main orchestrator — runs the full pipeline:
  1. Scrape jobs from all sources
  2. Score each job with AI
  3. Generate cover letters for high-scoring jobs
  4. Auto-apply (if enabled)
  5. Log results

Usage:
  python main.py                  # Full run (dry_run=True — won't actually submit)
  python main.py --apply          # Full run AND actually submit applications
  python main.py --scrape-only    # Only scrape and score, no applying
  python main.py --dashboard      # Open the tracker dashboard
"""
import os
import sys
import argparse
from dotenv import load_dotenv

load_dotenv()

from config import PROFILE
from database import insert_job, update_score, update_cover_letter, mark_applied, log_run, get_jobs, get_stats, delete_old_jobs
from scraper import scrape_all_jobs
from ai_engine import score_job, generate_cover_letter
from auto_apply import apply_to_jobs_batch

# ── Settings ──────────────────────────────────────────────────────────────────
KEYWORDS = [k.strip() for k in os.getenv("JOB_KEYWORDS", "machine learning engineer,AI engineer").split(",")]
MIN_SCORE = float(os.getenv("MIN_SCORE_TO_APPLY", "7"))
MAX_APPLICATIONS = int(os.getenv("MAX_APPLICATIONS_PER_RUN", "10"))


def run_pipeline(dry_run: bool = True, scrape_only: bool = False):
    print("=" * 60)
    print("  Job Application System — Starting")
    print(f"  Keywords: {KEYWORDS}")
    print(f"  Min score to apply: {MIN_SCORE}")
    print(f"  Dry run: {dry_run}")
    print("=" * 60)

    # Auto-clean stale jobs (older than 8 hours) — positions already filled
    delete_old_jobs(hours=8)

    jobs_found = 0
    jobs_scored = 0
    jobs_applied = 0
    errors = []

    # ── Step 1: Scrape ────────────────────────────────────────────────────────
    print("\n[1/4] Scraping job boards...")
    raw_jobs = scrape_all_jobs(KEYWORDS)

    new_jobs = []
    for job in raw_jobs:
        job_id = insert_job(job)
        if job_id is not None:
            job["id"] = job_id
            new_jobs.append(job)

    jobs_found = len(new_jobs)
    print(f"  {jobs_found} new jobs added to database ({len(raw_jobs) - jobs_found} duplicates skipped)")

    if scrape_only:
        log_run(jobs_found, 0, 0)
        print("\nDone (scrape only).")
        return

    # Include previously scraped but unscored jobs
    unscored = get_jobs(status="new", min_score=0)
    unscored = [j for j in unscored if not j.get("score")]
    jobs_to_score = unscored[:20]  # Max 20 per run to stay within free API limits
    if not jobs_to_score:
        print("  No jobs to score.")
        log_run(jobs_found, 0, 0)
        return

    # ── Step 2: Score with AI ─────────────────────────────────────────────────
    print(f"\n[2/4] Scoring {len(jobs_to_score)} jobs with AI...")
    for i, job in enumerate(jobs_to_score):
        print(f"  [{i+1}/{len(jobs_to_score)}] Scoring: {job['title']} @ {job['company']}... ", end="")
        try:
            score, reason = score_job(job)
            update_score(job["id"], score, reason)
            job["score"] = score
            print(f"score={score:.1f}")
            jobs_scored += 1
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append(str(e))

    # ── Step 3: Generate cover letters for top jobs ───────────────────────────
    top_jobs = [j for j in jobs_to_score if j.get("score", 0) >= MIN_SCORE]
    print(f"\n[3/4] Generating cover letters for {len(top_jobs)} top-scored jobs...")

    for i, job in enumerate(top_jobs):
        print(f"  [{i+1}/{len(top_jobs)}] Cover letter for: {job['title']} @ {job['company']}...")
        try:
            letter = generate_cover_letter(job)
            update_cover_letter(job["id"], letter)
            job["cover_letter"] = letter
        except Exception as e:
            print(f"  ERROR: {e}")
            errors.append(str(e))

    if scrape_only:
        log_run(jobs_found, jobs_scored, 0, "\n".join(errors))
        return

    # ── Step 4: Auto-apply ────────────────────────────────────────────────────
    # Include previously reviewed jobs with cover letters that haven't been applied to
    existing_top = get_jobs(status="reviewed", min_score=MIN_SCORE)
    existing_top = [j for j in existing_top if j.get("cover_letter")]
    all_apply = {j["id"]: j for j in top_jobs + existing_top}  # deduplicate by id
    apply_candidates = list(all_apply.values())[:MAX_APPLICATIONS]
    print(f"\n[4/4] Auto-applying to {len(apply_candidates)} jobs (dry_run={dry_run})...")
    try:
        batch_results = apply_to_jobs_batch(apply_candidates, dry_run=dry_run)
        for res in batch_results:
            job = res.get("job", {})
            if res["success"]:
                mark_applied(job["id"], notes=res["notes"])
                jobs_applied += 1
                print(f"  ✓ {job.get('title')} @ {job.get('company')}: {res['notes']}")
            else:
                print(f"  ✗ {job.get('title')} @ {job.get('company')}: {res['notes']}")
    except Exception as e:
        print(f"  ERROR in batch apply: {e}")
        errors.append(str(e))

    # ── Summary ───────────────────────────────────────────────────────────────
    log_run(jobs_found, jobs_scored, jobs_applied, "\n".join(errors))

    stats = get_stats()
    print("\n" + "=" * 60)
    print("  RUN COMPLETE")
    print(f"  Jobs found this run : {jobs_found}")
    print(f"  Jobs scored         : {jobs_scored}")
    print(f"  Applications sent   : {jobs_applied}")
    print(f"  Total in database   : {stats['total']}")
    print(f"  By status           : {stats['by_status']}")
    if errors:
        print(f"  Errors ({len(errors)})         : see log")
    print("=" * 60)
    print("\nRun 'python main.py --dashboard' to view your tracker.")


def open_dashboard():
    import subprocess
    subprocess.run([sys.executable, "-m", "streamlit", "run", "dashboard.py"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Application Automation System")
    parser.add_argument("--apply", action="store_true", help="Actually submit applications (default: dry run)")
    parser.add_argument("--scrape-only", action="store_true", help="Only scrape and score, don't apply")
    parser.add_argument("--dashboard", action="store_true", help="Open the Streamlit dashboard")
    args = parser.parse_args()

    if args.dashboard:
        open_dashboard()
    else:
        run_pipeline(
            dry_run=not args.apply,
            scrape_only=args.scrape_only,
        )
