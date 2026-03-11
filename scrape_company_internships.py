"""
Scrape internships directly from company career pages.

Most real internships (Google, Meta, Anthropic, Databricks, OpenAI, etc.) are posted
ONLY on the company's own site — not on LinkedIn or Indeed.

Sources:
  • Greenhouse  → https://boards-api.greenhouse.io/v1/boards/{slug}/jobs
  • Lever       → https://api.lever.co/v0/postings/{slug}?mode=json
  • Y Combinator / Work at a Startup → https://www.workatastartup.com/jobs
  • Wellfound (AngelList) → __NEXT_DATA__ SSR scrape

No API key required. Returns JSON. Very reliable.

Add/remove companies by editing GREENHOUSE_COMPANIES or LEVER_COMPANIES below.
"""
import re
import json
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


# ── Y Combinator / Work at a Startup ──────────────────────────────────────────

def scrape_yc_intern() -> list[dict]:
    """
    Y Combinator's Work at a Startup job board.
    Fetches the internship-filtered page and parses __NEXT_DATA__ (Next.js SSR).
    """
    jobs = []
    try:
        url = "https://www.workatastartup.com/jobs?query=intern&type=intern"
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"[YC/WorkAtAStartup] HTTP {r.status_code}")
            return []

        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
            r.text, re.DOTALL
        )
        if not match:
            print("[YC/WorkAtAStartup] Could not find __NEXT_DATA__ in page")
            return []

        page_data = json.loads(match.group(1))
        props = page_data.get("props", {}).get("pageProps", {})
        raw_jobs = (
            props.get("jobs") or
            props.get("listings") or
            props.get("roles") or
            []
        )

        count = 0
        for item in raw_jobs:
            if not isinstance(item, dict):
                continue
            title = item.get("title", "") or item.get("job_title", "") or ""
            if not _is_intern_title(title):
                continue

            company_data = item.get("company", {}) or {}
            company = company_data.get("name", "") if isinstance(company_data, dict) else str(company_data)

            job_id = item.get("id", "") or item.get("slug", "")
            job_url = item.get("url", "") or item.get("job_url", "") or ""
            if not job_url and job_id:
                job_url = f"https://www.workatastartup.com/jobs/{job_id}"
            if not job_url or not job_url.startswith("http"):
                continue

            loc_list = item.get("locationNames", []) or item.get("locations", [])
            location = loc_list[0] if loc_list else (item.get("remote") and "Remote" or "USA")

            description = item.get("description", "") or ""
            description = re.sub(r"<[^>]+>", " ", description).strip()[:3000]

            date_posted = ""
            created = item.get("created_at", "") or item.get("posted_at", "")
            if created:
                try:
                    if isinstance(created, (int, float)):
                        ts = int(created)
                        dt = datetime.fromtimestamp(ts / 1000 if ts > 1e10 else ts, tz=timezone.utc)
                    else:
                        dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                    date_posted = dt.isoformat()
                except Exception:
                    date_posted = str(created)

            jobs.append({
                "title":          title,
                "company":        company or "YC Startup",
                "url":            job_url,
                "location":       location,
                "salary":         "",
                "description":    description,
                "tags":           ["internship", "yc", "workatastartup"],
                "source":         "yc",
                "date_posted":    date_posted,
                "num_applicants": "",
            })
            count += 1

        if count:
            print(f"[YC/WorkAtAStartup] {count} intern postings")
        else:
            print("[YC/WorkAtAStartup] No intern postings found (API/page structure may have changed)")
    except Exception as e:
        print(f"[YC/WorkAtAStartup] Error: {e}")
    return jobs


# ── Wellfound (AngelList) ──────────────────────────────────────────────────────

def scrape_wellfound_intern() -> list[dict]:
    """
    Wellfound (formerly AngelList) startup internships.
    Parses __NEXT_DATA__ JSON embedded in the Next.js SSR page.
    Falls back gracefully if the page structure changes.
    """
    jobs = []
    try:
        url = "https://wellfound.com/role/l/intern"
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"[Wellfound] HTTP {r.status_code}")
            return []

        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>',
            r.text, re.DOTALL
        )
        if not match:
            print("[Wellfound] Could not find __NEXT_DATA__ in page")
            return []

        page_data = json.loads(match.group(1))
        props = page_data.get("props", {}).get("pageProps", {})
        raw_jobs = (
            props.get("roleListings") or
            props.get("listings") or
            props.get("roles") or
            props.get("jobs") or
            []
        )

        count = 0
        for item in raw_jobs:
            if not isinstance(item, dict):
                continue

            # Wellfound nests role info sometimes
            role = item.get("role", item)
            title = role.get("title", "") or item.get("title", "") or ""
            if not _is_intern_title(title):
                continue

            company_data = item.get("company", role.get("startup", {})) or {}
            company = company_data.get("name", "") if isinstance(company_data, dict) else str(company_data)

            slug = role.get("slug", "") or item.get("slug", "") or role.get("id", "")
            job_url = role.get("url", "") or item.get("url", "")
            if not job_url and slug:
                job_url = f"https://wellfound.com/jobs/{slug}"
            if not job_url or not job_url.startswith("http"):
                continue

            loc_list = role.get("locationNames", []) or item.get("locationNames", [])
            location = loc_list[0] if loc_list else "USA"

            jobs.append({
                "title":          title or "Intern",
                "company":        company or "Wellfound Startup",
                "url":            job_url,
                "location":       location,
                "salary":         "",
                "description":    "",
                "tags":           ["internship", "wellfound", "startup"],
                "source":         "wellfound",
                "date_posted":    "",
                "num_applicants": "",
            })
            count += 1

        if count:
            print(f"[Wellfound] {count} intern postings")
        else:
            print("[Wellfound] No listings found (page may be JS-only or structure changed)")
    except Exception as e:
        print(f"[Wellfound] Error: {e}")
    return jobs


# ── Main entry point ──────────────────────────────────────────────────────────

def scrape_all_company_internships() -> list[dict]:
    """
    Scrape internships from company career pages via Greenhouse + Lever APIs,
    plus Y Combinator (Work at a Startup) and Wellfound (AngelList).
    Returns a deduplicated list of job dicts compatible with insert_job().
    """
    all_jobs: list[dict] = []

    print("\n── Greenhouse (company career pages) ────────")
    all_jobs.extend(scrape_greenhouse(GREENHOUSE_COMPANIES))

    print("\n── Lever (company career pages) ─────────────")
    all_jobs.extend(scrape_lever(LEVER_COMPANIES))

    print("\n── Y Combinator / Work at a Startup ─────────")
    all_jobs.extend(scrape_yc_intern())

    print("\n── Wellfound (AngelList) ─────────────────────")
    all_jobs.extend(scrape_wellfound_intern())

    # Deduplicate by URL
    seen: set[str] = set()
    unique: list[dict] = []
    for job in all_jobs:
        if job["url"] not in seen:
            seen.add(job["url"])
            unique.append(job)

    print(f"\n[Company Career Pages] Total unique intern jobs: {len(unique)}")
    return unique
