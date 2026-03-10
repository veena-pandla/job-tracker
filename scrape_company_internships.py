"""
Scrape internships directly from company career pages.

Most real internships (Google, Meta, Anthropic, Databricks, OpenAI, etc.) are posted
ONLY on the company's own site — not on LinkedIn or Indeed.

This scraper uses two public, free APIs that 90% of tech companies use as their ATS:
  • Greenhouse  → https://boards-api.greenhouse.io/v1/boards/{slug}/jobs
  • Lever       → https://api.lever.co/v0/postings/{slug}?mode=json

No API key required. Returns JSON. Very reliable.

Add/remove companies by editing GREENHOUSE_COMPANIES or LEVER_COMPANIES below.
"""
import requests
import time
from datetime import datetime, timezone

_INTERN_WORDS = ("intern", "internship", "trainee", "co-op", "coop", "co op")

def _is_intern_title(title: str) -> bool:
    t = title.lower()
    return any(w in t for w in _INTERN_WORDS)


# ── Company lists ─────────────────────────────────────────────────────────────
# Format: "Display Name": "ats-slug"
# To find a company's slug: go to their jobs page and look at the URL, e.g.
#   https://boards.greenhouse.io/anthropic  →  slug is "anthropic"
#   https://jobs.lever.co/netflix           →  slug is "netflix"

GREENHOUSE_COMPANIES = {
    # AI / ML focused
    "Anthropic":         "anthropic",
    "Scale AI":          "scaleai",
    "Cohere":            "cohere",
    "Weights & Biases":  "wandb",
    "Hugging Face":      "huggingface",
    "Mistral AI":        "mistral",
    "Perplexity AI":     "perplexityai",
    "Together AI":       "togetherai",
    "Runway":            "runwayml",
    "Stability AI":      "stabilityai",

    # Data / Cloud
    "Databricks":        "databricks",
    "Snowflake":         "snowflake",
    "MongoDB":           "mongodb",
    "Elastic":           "elastic",
    "HashiCorp":         "hashicorp",
    "Datadog":           "datadog",
    "New Relic":         "newrelic",
    "PagerDuty":         "pagerduty",
    "Cloudflare":        "cloudflare",

    # FinTech
    "Stripe":            "stripe",
    "Coinbase":          "coinbase",
    "Robinhood":         "robinhood",
    "Brex":              "brex",
    "Plaid":             "plaid",
    "Chime":             "chime",
    "Carta":             "carta",

    # Big Tech / SaaS
    "Airbnb":            "airbnb",
    "Lyft":              "lyft",
    "Pinterest":         "pinterest",
    "Dropbox":           "dropbox",
    "GitHub":            "github",
    "Notion":            "notion",
    "Figma":             "figma",
    "Airtable":          "airtable",
    "Rippling":          "rippling",
    "Twilio":            "twilio",
    "Zendesk":           "zendesk",
    "Okta":              "okta",
    "HubSpot":           "hubspot",
    "Amplitude":         "amplitude",
    "Mixpanel":          "mixpanel",
    "Intercom":          "intercom",
    "Segment":           "segment",
    "Retool":            "retool",
    "Loom":              "loom",
    "Miro":              "miro",
    "Linear":            "linear",
    "Vercel":            "vercel",
    "LaunchDarkly":      "launchdarkly",
    "Checkr":            "checkr",
    "Gusto":             "gusto",
    "Lattice":           "lattice",
    "Duolingo":          "duolingo",
}

LEVER_COMPANIES = {
    # Big names that use Lever
    "Netflix":           "netflix",
    "Coursera":          "coursera",
    "Faire":             "faire",
    "Whatnot":           "whatnot",
    "Flexport":          "flexport",
    "Benchling":         "benchling",
    "Anduril":           "anduril",
    "Palantir":          "palantir",
    "Verkada":           "verkada",
    "Ripple":            "ripple",
    "Figma (Lever)":     "figma",
    "Discord":           "discord",
    "Twitch":            "twitch",
    "Cruise":            "getcruise",
    "Nuro":              "nuro",
    "Aurora":            "auroradriver",
    "Argo AI":           "argoai",
    "Waymo":             "waymo",
    "Zoox":              "zoox",
    "Rivian":            "rivian",
    "Lucid Motors":      "lucidmotors",
}


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    )
}


# ── Greenhouse ────────────────────────────────────────────────────────────────

def scrape_greenhouse(companies: dict[str, str]) -> list[dict]:
    """
    Greenhouse public API — no auth needed.
    GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs
    """
    jobs = []
    for company_name, slug in companies.items():
        try:
            url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            raw_jobs = data.get("jobs", [])

            count = 0
            for item in raw_jobs:
                title = item.get("title", "") or ""
                if not _is_intern_title(title):
                    continue

                job_url = item.get("absolute_url", "") or ""
                if not job_url:
                    job_url = f"https://boards.greenhouse.io/{slug}"

                # Location
                loc_list = item.get("location", {})
                location = ""
                if isinstance(loc_list, dict):
                    location = loc_list.get("name", "") or ""
                elif isinstance(loc_list, list) and loc_list:
                    location = loc_list[0].get("name", "") if isinstance(loc_list[0], dict) else str(loc_list[0])

                # Date
                date_posted = ""
                updated = item.get("updated_at", "") or item.get("created_at", "")
                if updated:
                    try:
                        dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                        date_posted = dt.isoformat()
                    except Exception:
                        date_posted = updated

                jobs.append({
                    "title":         title,
                    "company":       company_name,
                    "url":           job_url,
                    "location":      location or "USA",
                    "salary":        "",
                    "description":   "",          # Greenhouse needs a second call for description
                    "tags":          ["internship", "greenhouse", slug],
                    "source":        "greenhouse",
                    "date_posted":   date_posted,
                    "num_applicants": "",
                })
                count += 1

            if count:
                print(f"[Greenhouse] {company_name}: {count} intern postings")
            time.sleep(0.3)
        except Exception as e:
            print(f"[Greenhouse] {company_name}: {e}")

    return jobs


# ── Lever ─────────────────────────────────────────────────────────────────────

def scrape_lever(companies: dict[str, str]) -> list[dict]:
    """
    Lever public API — no auth needed.
    GET https://api.lever.co/v0/postings/{slug}?mode=json
    """
    jobs = []
    for company_name, slug in companies.items():
        try:
            url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            raw_jobs = r.json()
            if not isinstance(raw_jobs, list):
                continue

            count = 0
            for item in raw_jobs:
                title = item.get("text", "") or ""
                if not _is_intern_title(title):
                    continue

                job_url = item.get("hostedUrl", "") or item.get("applyUrl", "") or ""
                if not job_url:
                    job_url = f"https://jobs.lever.co/{slug}"

                # Location
                categories = item.get("categories", {}) or {}
                location = categories.get("location", "") or categories.get("commitment", "") or "USA"

                # Date (Lever gives Unix ms timestamp)
                date_posted = ""
                created_at = item.get("createdAt")
                if created_at:
                    try:
                        dt = datetime.fromtimestamp(int(created_at) / 1000, tz=timezone.utc)
                        date_posted = dt.isoformat()
                    except Exception:
                        pass

                # Description (Lever includes it inline)
                desc_text = ""
                lists = item.get("lists", []) or []
                for lst in lists:
                    desc_text += (lst.get("text", "") or "") + "\n"
                    for content in (lst.get("content", "") or "").split("<li>"):
                        if content.strip():
                            import re
                            desc_text += "• " + re.sub(r"<[^>]+>", "", content).strip() + "\n"

                desc_text = (desc_text or item.get("description", "") or "")[:3000]

                jobs.append({
                    "title":         title,
                    "company":       company_name,
                    "url":           job_url,
                    "location":      location,
                    "salary":        "",
                    "description":   desc_text,
                    "tags":          ["internship", "lever", slug],
                    "source":        "lever",
                    "date_posted":   date_posted,
                    "num_applicants": "",
                })
                count += 1

            if count:
                print(f"[Lever] {company_name}: {count} intern postings")
            time.sleep(0.3)
        except Exception as e:
            print(f"[Lever] {company_name}: {e}")

    return jobs


# ── Main entry point ──────────────────────────────────────────────────────────

def scrape_all_company_internships() -> list[dict]:
    """
    Scrape internships from company career pages via Greenhouse + Lever APIs.
    Returns a deduplicated list of job dicts compatible with insert_job().
    """
    all_jobs: list[dict] = []

    print("\n── Greenhouse (company career pages) ────────")
    all_jobs.extend(scrape_greenhouse(GREENHOUSE_COMPANIES))

    print("\n── Lever (company career pages) ─────────────")
    all_jobs.extend(scrape_lever(LEVER_COMPANIES))

    # Deduplicate by URL
    seen: set[str] = set()
    unique: list[dict] = []
    for job in all_jobs:
        if job["url"] not in seen:
            seen.add(job["url"])
            unique.append(job)

    print(f"\n[Company Career Pages] Total unique intern jobs: {len(unique)}")
    return unique
