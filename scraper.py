"""
Job scraper using JobSpy — scrapes LinkedIn, Indeed, Glassdoor, ZipRecruiter.
Gets jobs posted in the last 24 hours with proper date_posted for every job.
"""
import time
import re
import requests
from datetime import datetime, timezone

try:
    from jobspy import scrape_jobs
except ImportError:
    raise ImportError("Run: pip install python-jobspy")


def _is_linkedin_easy_apply(job_url: str) -> bool:
    """
    Check LinkedIn's jobs-guest API to detect Easy Apply.
    'apply-link-offsite' in response = External Site; absent = Easy Apply.
    Runs locally during scraping so Streamlit Cloud doesn't need to call LinkedIn.
    """
    try:
        m = re.search(r"/view/(\d+)", job_url)
        if not m:
            return False
        job_id = m.group(1)
        api_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
        r = requests.get(api_url, headers=headers, timeout=6)
        return "apply-link-offsite" not in r.text.lower()
    except Exception:
        return False


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

                # Capture Easy Apply flag from jobspy when available (LinkedIn only)
                # jobspy returns True/None — store as tag so dashboard skips live check
                if str(row.get("site", "")) == "linkedin":
                    ea = row.get("is_easy_apply")
                    if ea is True:
                        tags.append("easy_apply")

                # Applicant count — jobspy may return this for some sources
                num_applicants = ""
                for field in ["num_applicants", "applicants", "num_urgent_words"]:
                    val = row.get(field)
                    if val is not None:
                        try:
                            import pandas as pd
                            if not pd.isna(val):
                                num_applicants = str(int(float(val)))
                                break
                        except Exception:
                            pass

                all_jobs.append({
                    "title":          str(row.get("title", "") or ""),
                    "company":        str(row.get("company", "") or ""),
                    "url":            url,
                    "location":       str(row.get("location", "Remote") or "Remote"),
                    "salary":         salary,
                    "description":    str(row.get("description", "") or "")[:3000],
                    "tags":           tags,
                    "source":         str(row.get("site", "") or ""),
                    "date_posted":    date_posted,
                    "num_applicants": num_applicants,
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
