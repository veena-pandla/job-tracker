"""
Internship-specific scraper.
Sources:
  1. RemoteOK  — free JSON API (remoteok.com/api?tag=intern)
  2. Indeed RSS — feedparser, last 7 days, Remote + USA
  3. JobSpy    — LinkedIn, Indeed, Glassdoor, ZipRecruiter (last 7 days)
     * Searches both "Remote" and "United States" for broader coverage
     * results_wanted=50 per keyword

Only jobs with "intern", "internship", "trainee", or "co-op" in the title
are kept — so generic keyword hits are filtered out automatically.
"""
import time
import re
import requests
import feedparser
import email.utils
from datetime import datetime, timezone

try:
    from jobspy import scrape_jobs
except ImportError:
    scrape_jobs = None

# Broader keyword list — mix of specific and general so we don't miss anything
INTERN_KEYWORDS = [
    # General (catches the most)
    "intern",
    "internship remote",
    "summer intern 2025",
    # Domain-specific
    "machine learning intern",
    "AI intern",
    "data science intern",
    "software engineer intern",
    "python intern",
    "data engineer intern",
    "ML research intern",
    "backend intern",
    "full stack intern",
    "AI research intern",
    "deep learning intern",
    "computer vision intern",
    "NLP intern",
]

_INTERN_TITLE_WORDS = ("intern", "internship", "trainee", "co-op", "coop")


def _clean_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "").strip()


def _is_intern_title(title: str) -> bool:
    return any(w in title.lower() for w in _INTERN_TITLE_WORDS)


# ── Source 1: RemoteOK ────────────────────────────────────────────────────────

def scrape_remoteok_intern() -> list[dict]:
    """
    RemoteOK free JSON API.  Returns every job tagged 'intern'.
    https://remoteok.com/api?tag=intern
    """
    jobs = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; InternScraper/1.0)"}
        r = requests.get("https://remoteok.com/api?tag=intern", headers=headers, timeout=15)
        data = r.json()
        for item in data[1:]:       # item[0] is a legal notice dict — skip it
            if not isinstance(item, dict):
                continue
            title = item.get("position", "") or ""
            # Don't filter by title here — RemoteOK already tagged these as intern
            company = item.get("company", "") or "Unknown"
            slug = item.get("slug", "")
            url = item.get("url", "") or (f"https://remoteok.com/remote-jobs/{slug}" if slug else "")
            if not url:
                continue
            if not url.startswith("http"):
                url = "https://remoteok.com" + url

            tags_raw = list(item.get("tags", []) or [])
            date_str = item.get("date", "")

            jobs.append({
                "title":         title,
                "company":       company,
                "url":           url,
                "location":      "Remote",
                "salary":        "",
                "description":   _clean_html(item.get("description", ""))[:3000],
                "tags":          tags_raw + ["internship", "remoteok"],
                "source":        "remoteok",
                "date_posted":   date_str,
                "num_applicants": "",
            })
        print(f"[RemoteOK] Found {len(jobs)} intern jobs")
    except Exception as e:
        print(f"[RemoteOK] Error: {e}")
    return jobs


# ── Source 2: Indeed RSS ──────────────────────────────────────────────────────

def scrape_indeed_rss_intern(keywords: list[str]) -> list[dict]:
    """
    Indeed RSS feeds — no API key needed, very fresh (sort=date).
    Searches both Remote and no-location (USA-wide) to maximise results.
    fromage=7 = last 7 days.
    """
    jobs = []
    seen_urls: set[str] = set()

    # Search both Remote and nationwide
    location_variants = ["Remote", ""]

    for keyword in keywords:
        for location in location_variants:
            try:
                encoded_q = keyword.replace(" ", "+")
                loc_param = f"&l={location.replace(' ', '+')}" if location else ""
                feed_url = (
                    f"https://rss.indeed.com/rss?q={encoded_q}"
                    f"{loc_param}&sort=date&fromage=7&limit=25"
                )
                feed = feedparser.parse(feed_url)
                count = 0
                for entry in feed.entries:
                    url = entry.get("link", "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)

                    # Indeed RSS title format: "Job Title - Company Name"
                    raw_title = entry.get("title", "")
                    company = ""
                    if " - " in raw_title:
                        parts = raw_title.rsplit(" - ", 1)
                        title = parts[0].strip()
                        company = parts[1].strip()
                    else:
                        title = raw_title

                    if not _is_intern_title(title):
                        continue

                    # Parse RFC-2822 published date
                    date_posted = ""
                    pub = getattr(entry, "published", None)
                    if pub:
                        try:
                            dt = email.utils.parsedate_to_datetime(pub)
                            date_posted = dt.isoformat()
                        except Exception:
                            date_posted = pub

                    summary = _clean_html(entry.get("summary", ""))
                    jobs.append({
                        "title":         title,
                        "company":       company or "Unknown",
                        "url":           url,
                        "location":      location or "USA",
                        "salary":        "",
                        "description":   summary[:3000],
                        "tags":          [keyword, "internship", "indeed_rss"],
                        "source":        "indeed",
                        "date_posted":   date_posted,
                        "num_applicants": "",
                    })
                    count += 1

                if count:
                    print(f"[IndeedRSS] '{keyword}' ({location or 'USA'}) -> {count} intern jobs")
                time.sleep(0.5)
            except Exception as e:
                print(f"[IndeedRSS] Error for '{keyword}': {e}")

    return jobs


# ── Source 3: JobSpy (LinkedIn / Indeed / Glassdoor / ZipRecruiter) ──────────

def scrape_jobspy_intern(keywords: list[str]) -> list[dict]:
    """
    Use JobSpy to hit LinkedIn, Indeed, Glassdoor, ZipRecruiter.
    - hours_old=168 (7 days) — intern postings are sparse
    - results_wanted=50 per keyword
    - searches both Remote and United States for wider coverage
    - keeps ALL intern-titled rows regardless of seniority
    """
    if scrape_jobs is None:
        print("[JobSpy] python-jobspy not installed — skipping.")
        return []

    all_jobs: list[dict] = []
    seen_urls: set[str] = set()

    # Search two locations for more coverage
    locations = ["Remote", "United States"]

    for location in locations:
        for keyword in keywords:
            print(f"[JobSpy] '{keyword}' @ {location}...")
            try:
                df = scrape_jobs(
                    site_name=["linkedin", "indeed", "glassdoor", "zip_recruiter"],
                    search_term=keyword,
                    location=location,
                    results_wanted=50,
                    hours_old=168,          # 7 days
                    country_indeed="USA",
                    verbose=0,
                )
                if df is None or df.empty:
                    continue

                kept = 0
                for _, row in df.iterrows():
                    url = str(row.get("job_url", "") or "")
                    if not url or url in seen_urls:
                        continue

                    title = str(row.get("title", "") or "")
                    if not _is_intern_title(title):
                        continue

                    seen_urls.add(url)

                    # date_posted
                    date_posted = ""
                    dp = row.get("date_posted")
                    if dp is not None:
                        try:
                            import pandas as pd
                            if not pd.isna(dp):
                                date_posted = dp.isoformat() if hasattr(dp, "isoformat") else str(dp)
                        except Exception:
                            pass

                    # salary
                    salary = ""
                    try:
                        import math
                        min_amt = row.get("min_amount")
                        max_amt = row.get("max_amount")
                        interval = str(row.get("interval") or "").strip()
                        min_amt = float(min_amt) if min_amt is not None else None
                        max_amt = float(max_amt) if max_amt is not None else None
                        if min_amt and not math.isnan(min_amt) and max_amt and not math.isnan(max_amt):
                            salary = f"${int(min_amt):,} - ${int(max_amt):,} {interval}".strip()
                        elif min_amt and not math.isnan(min_amt):
                            salary = f"${int(min_amt):,}+ {interval}".strip()
                    except Exception:
                        pass

                    all_jobs.append({
                        "title":         title,
                        "company":       str(row.get("company", "") or ""),
                        "url":           url,
                        "location":      str(row.get("location", location) or location),
                        "salary":        salary,
                        "description":   str(row.get("description", "") or "")[:3000],
                        "tags":          [keyword, "internship"],
                        "source":        str(row.get("site", "") or ""),
                        "date_posted":   date_posted,
                        "num_applicants": "",
                    })
                    kept += 1

                print(f"[JobSpy] '{keyword}' @ {location} -> {kept} intern jobs kept")
                time.sleep(2)
            except Exception as e:
                print(f"[JobSpy] Error for '{keyword}' @ {location}: {e}")

    return all_jobs


# ── Main entry point ──────────────────────────────────────────────────────────

def scrape_all_intern_jobs(keywords: list[str] | None = None) -> list[dict]:
    """
    Run all three scrapers and return a deduplicated list of internship jobs.
    Call from dashboard sidebar button or CLI.
    """
    if keywords is None:
        keywords = INTERN_KEYWORDS

    all_jobs: list[dict] = []

    print("\n── RemoteOK ──────────────────────────────")
    all_jobs.extend(scrape_remoteok_intern())

    print("\n── Indeed RSS ────────────────────────────")
    # Broader RSS keywords (simpler = more results)
    rss_keywords = [
        "intern",
        "machine learning intern",
        "AI intern",
        "data science intern",
        "software intern",
        "python intern",
    ]
    all_jobs.extend(scrape_indeed_rss_intern(rss_keywords))

    print("\n── JobSpy (LinkedIn/Indeed/Glassdoor/Zip) ─")
    all_jobs.extend(scrape_jobspy_intern(keywords))

    # Deduplicate by URL
    seen: set[str] = set()
    unique: list[dict] = []
    for job in all_jobs:
        if job["url"] not in seen:
            seen.add(job["url"])
            unique.append(job)

    print(f"\n[Internships] Total unique jobs: {len(unique)}")
    return unique
