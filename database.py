"""
PostgreSQL database layer (Supabase) — stores all jobs and application history.
"""
import psycopg2
import psycopg2.extras
import json
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")


def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def init_db():
    """Create tables if they don't exist."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id                   SERIAL PRIMARY KEY,
                    title                TEXT NOT NULL,
                    company              TEXT NOT NULL,
                    url                  TEXT UNIQUE NOT NULL,
                    source               TEXT,
                    location             TEXT,
                    salary               TEXT,
                    description          TEXT,
                    tags                 TEXT,
                    date_found           TEXT,
                    date_posted          TEXT,
                    score                REAL DEFAULT 0,
                    score_reason         TEXT,
                    status               TEXT DEFAULT 'new',
                    cover_letter         TEXT,
                    applied_date         TEXT,
                    notes                TEXT,
                    tailored_resume_json TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS run_log (
                    id           SERIAL PRIMARY KEY,
                    run_date     TEXT,
                    jobs_found   INTEGER DEFAULT 0,
                    jobs_scored  INTEGER DEFAULT 0,
                    jobs_applied INTEGER DEFAULT 0,
                    errors       TEXT
                )
            """)
        conn.commit()


def insert_job(job: dict) -> int | None:
    """Insert a new job. Returns the new row id, or None if duplicate."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                tags = json.dumps(job.get("tags", []))
                cur.execute("""
                    INSERT INTO jobs (title, company, url, source, location, salary,
                                      description, tags, date_found, date_posted)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("url", ""),
                    job.get("source", ""),
                    job.get("location", ""),
                    job.get("salary", ""),
                    job.get("description", ""),
                    tags,
                    datetime.now().isoformat(),
                    job.get("date_posted", ""),
                ))
                row = cur.fetchone()
            conn.commit()
            return row[0] if row else None
    except psycopg2.errors.UniqueViolation:
        return None  # duplicate URL


def update_score(job_id: int, score: float, reason: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET score=%s, score_reason=%s, status='reviewed' WHERE id=%s",
                (score, reason, job_id)
            )
        conn.commit()


def update_cover_letter(job_id: int, cover_letter: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET cover_letter=%s WHERE id=%s",
                (cover_letter, job_id)
            )
        conn.commit()


def mark_applied(job_id: int, notes: str = ""):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status='applied', applied_date=%s, notes=%s WHERE id=%s",
                (datetime.now().isoformat(), notes, job_id)
            )
        conn.commit()


def update_status(job_id: int, status: str, notes: str = ""):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE jobs SET status=%s, notes=%s WHERE id=%s",
                (status, notes, job_id)
            )
        conn.commit()


def get_jobs(status: str | None = None, min_score: float = 0) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if status:
                cur.execute(
                    "SELECT * FROM jobs WHERE status=%s AND (score>=%s OR score IS NULL) ORDER BY score DESC, date_found DESC",
                    (status, min_score)
                )
            else:
                cur.execute(
                    "SELECT * FROM jobs WHERE score>=%s ORDER BY score DESC, date_found DESC",
                    (min_score,)
                )
            return [dict(r) for r in cur.fetchall()]


def get_job_by_id(job_id: int) -> dict | None:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
            row = cur.fetchone()
            return dict(row) if row else None


def log_run(jobs_found: int, jobs_scored: int, jobs_applied: int, errors: str = ""):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO run_log (run_date, jobs_found, jobs_scored, jobs_applied, errors) VALUES (%s,%s,%s,%s,%s)",
                (datetime.now().isoformat(), jobs_found, jobs_scored, jobs_applied, errors)
            )
        conn.commit()


def get_stats() -> dict:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM jobs")
            total = cur.fetchone()[0]
            cur.execute("SELECT status, COUNT(*) as cnt FROM jobs GROUP BY status")
            by_status = {row[0]: row[1] for row in cur.fetchall()}
            cur.execute("SELECT AVG(score) FROM jobs WHERE score > 0")
            avg_score = cur.fetchone()[0]
    return {
        "total": total,
        "by_status": by_status,
        "avg_score": round(avg_score or 0, 2),
    }


def delete_old_jobs(hours: int = 8) -> int:
    """Delete jobs older than `hours` hours, keeping applied/interviewing/offer."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM jobs
                WHERE status NOT IN ('applied', 'interviewing', 'offer')
                AND (
                    date_found < %s
                    OR (date_posted != '' AND date_posted IS NOT NULL AND date_posted < %s)
                )
            """, (cutoff, cutoff))
            deleted = cur.rowcount
        conn.commit()
    if deleted:
        print(f"[DB] Auto-cleaned {deleted} job(s) older than {hours}h from database.")
    return deleted


# Initialize on import
init_db()
