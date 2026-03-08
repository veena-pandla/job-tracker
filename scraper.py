"""
Job scraper using JobSpy — scrapes LinkedIn, Indeed, Glassdoor, ZipRecruiter.
Gets jobs posted in the last 24 hours with proper date_posted for every job.
"""
import time
from datetime import datetime, timezone

try:
    from jobspy import scrape_jobs
except ImportError:
    raise ImportError("Run: pip install python-jobspy")


def scrape_all_jobs(keywords: list[str]) -> list[dict]:
    """Scrape jobs from LinkedIn, Indeed, Glassdoor, ZipRecruiter using JobSpy."""
    all_jobs = []
    seen_urls = set()

    for keyword in keywords:
        print(f"[JobSpy] Searching: '{keyword}'...")
        try:
            df = scrape_jobs(
                site_name=["linkedin", "indeed", "glassdoor", "zip_recruiter"],
                search_term=keyword,
                location="Remote",
                results_wanted=25,
                hours_old=24,        # Only jobs posted in the last 24 hours
                country_indeed="USA",
                verbose=0,
            )

            if df is None or df.empty:
                print(f"[JobSpy] No results for '{keyword}'")
                continue

            for _, row in df.iterrows():
                url = str(row.get("job_url", "") or "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)

                # Parse date_posted
                date_posted = ""
                dp = row.get("date_posted")
                if dp is not None:
                    try:
                        import pandas as pd
                        if pd.isna(dp):
                            date_posted = ""
                        elif hasattr(dp, "isoformat"):
                            date_posted = dp.isoformat()
                        else:
                            s = str(dp)
                            if s.lower() not in ("nat", "none", "nan", ""):
                                date_posted = s
                    except Exception:
                        date_posted = ""

                # Build salary string (guard against NaN floats from pandas)
                salary = ""
                min_amt = row.get("min_amount")
                max_amt = row.get("max_amount")
                interval = str(row.get("salary_source") or row.get("interval") or "").strip()
                try:
                    min_amt = float(min_amt) if min_amt is not None else None
                    max_amt = float(max_amt) if max_amt is not None else None
                    import math
                    if min_amt and not math.isnan(min_amt) and max_amt and not math.isnan(max_amt):
                        salary = f"${int(min_amt):,} - ${int(max_amt):,} {interval}".strip()
                    elif min_amt and not math.isnan(min_amt):
                        salary = f"${int(min_amt):,}+ {interval}".strip()
                except Exception:
                    salary = ""

                # Job type tag
                job_type_raw = str(row.get("job_type") or "").lower()
                tags = [keyword]
                if job_type_raw:
                    tags.append(job_type_raw)
                # Capture LinkedIn Easy Apply flag from jobspy
                if row.get("is_easy_apply") is True:
                    tags.append("easy_apply")

                all_jobs.append({
                    "title":       str(row.get("title", "") or ""),
                    "company":     str(row.get("company", "") or ""),
                    "url":         url,
                    "location":    str(row.get("location", "Remote") or "Remote"),
                    "salary":      salary,
                    "description": str(row.get("description", "") or "")[:3000],
                    "tags":        tags,
                    "source":      str(row.get("site", "") or ""),
                    "date_posted": date_posted,
                })

            print(f"[JobSpy] '{keyword}' -> {len(df)} jobs found")
            time.sleep(2)  # polite delay between keyword searches

        except Exception as e:
            print(f"[JobSpy] Error for '{keyword}': {e}")

    # Deduplicate by URL
    seen = set()
    unique = []
    for job in all_jobs:
        if job["url"] not in seen:
            seen.add(job["url"])
            unique.append(job)

    print(f"\n[JobSpy] Total unique jobs: {len(unique)}")
    return unique
