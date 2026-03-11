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
    "ElevenLabs":        "elevenlabs",
    "Character AI":      "characterai",
    "Harvey":            "harveyai",
    "Glean":             "glean",
    "Adept AI":          "adeptai",
    "Inflection AI":     "inflectionai",
    "Imbue":             "imbue",
    "Mosaic ML":         "mosaicml",

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
    "Prefect":           "prefect",
    "Hex":               "hex",
    "Dagster":           "dagster",
    "dbt Labs":          "dbtlabs",
    "Fivetran":          "fivetran",
    "Airbyte":           "airbyte",

    # FinTech / YC FinTech
    "Stripe":            "stripe",
    "Coinbase":          "coinbase",
    "Robinhood":         "robinhood",
    "Brex":              "brex",
    "Plaid":             "plaid",
    "Chime":             "chime",
    "Carta":             "carta",
    "Ramp":              "ramp",
    "Deel":              "deel",
    "Mercury":           "mercury",
    "Rho":               "rho",
    "Finix":             "finix",
    "Slope":             "slope",
    "Stytch":            "stytch",

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
    "Grammarly":         "grammarly",
    "Canva":             "canva",
    "Pendo":             "pendo",
    "Highspot":          "highspot",
    "Gong":              "gong",

    # YC-backed Startups (high intern acceptance rate)
    "Replit":            "replit",
    "Vanta":             "vanta",
    "Gem":               "gem",
    "Ironclad":          "ironclad",
    "Pilot":             "pilot",
    "Descript":          "descript",
    "Watershed":         "watershed",
    "Ashby":             "ashby",
    "Persona":           "personaidentitycorp",
    "Sourcegraph":       "sourcegraph",
    "Coda":              "coda",
    "Neon":              "neon",
    "Browserbase":       "browserbase",
    "Supabase":          "supabase",
    "Temporal":          "temporal",

    # BioTech / HealthTech
    "Recursion":         "recursionpharma",
    "Ginkgo Bioworks":   "ginkgobioworks",
    "Benchling (GH)":    "benchling",
    "Freenome":          "freenome",
    "Tempus":            "tempus",
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

    # More startups using Lever
    "Attentive":         "attentive",
    "Navan":             "navan",
    "Samsara":           "samsara",
    "Drift":             "drift",
    "Clay":              "clay",
    "Luma AI":           "lumalabs",
    "Coda (Lever)":      "coda",
    "Highspot (Lever)":  "highspot",
    "Capsule":           "capsule",
    "Arc":               "arc",
    "Gem (Lever)":       "gem",
    "Rewind AI":         "rewindai",
    "Mem":               "mem",
    "Phenom":            "phenom",
    "Sendbird":          "sendbird",
    "Aptos":             "aptoslabs",
    "Mysten Labs":       "mystenlabs",
    "Dfinity":           "dfinity",
    "Alchemy":           "alchemyplatform",
    "Phantom":           "phantom",
    "Magic Eden":        "magiceden",
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

def _parse_yc_jobs(raw_jobs: list, source_tag: str) -> list[dict]:
    """Helper: convert raw YC job dicts into standard job dicts."""
    out = []
    for item in raw_jobs:
        if not isinstance(item, dict):
            continue
        title = item.get("title", "") or item.get("job_title", "") or ""
        if not _is_intern_title(title):
            continue

        company_data = item.get("company", item.get("startup", {})) or {}
        company = company_data.get("name", "") if isinstance(company_data, dict) else str(company_data)

        job_id = item.get("id", "") or item.get("slug", "")
        job_url = item.get("url", "") or item.get("job_url", "") or ""
        if not job_url and job_id:
            job_url = f"https://www.workatastartup.com/jobs/{job_id}"
        if not job_url or not job_url.startswith("http"):
            continue

        remote = item.get("remote", False)
        loc_list = item.get("locationNames", []) or item.get("locations", [])
        location = loc_list[0] if loc_list else ("Remote" if remote else "USA")

        description = re.sub(r"<[^>]+>", " ", item.get("description", "") or "").strip()[:3000]

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

        out.append({
            "title":          title,
            "company":        company or "YC Startup",
            "url":            job_url,
            "location":       location,
            "salary":         "",
            "description":    description,
            "tags":           ["internship", "yc", source_tag],
            "source":         "yc",
            "date_posted":    date_posted,
            "num_applicants": "",
        })
    return out


def scrape_yc_intern() -> list[dict]:
    """
    Y Combinator's Work at a Startup job board.
    workatastartup.com is a Rails app — tries JSON API endpoints directly.
    The page HTML uses client-side rendering so __NEXT_DATA__ won't have jobs.
    """
    jobs = []

    # Approach 1: Rails JSON API (append .json or use Accept header)
    api_attempts = [
        "https://www.workatastartup.com/startup_jobs.json?q=intern&type=intern",
        "https://www.workatastartup.com/startup_jobs.json?query=intern",
        "https://www.workatastartup.com/jobs.json?q=intern&type=intern",
    ]
    json_headers = {**HEADERS, "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}

    for api_url in api_attempts:
        try:
            r = requests.get(api_url, headers=json_headers, timeout=15)
            if r.status_code == 200 and r.text.strip()[:1] in ("[", "{"):
                data = r.json()
                raw = data if isinstance(data, list) else (
                    data.get("startup_jobs") or data.get("jobs") or []
                )
                if raw:
                    parsed = _parse_yc_jobs(raw, "workatastartup")
                    jobs.extend(parsed)
                    print(f"[YC/WorkAtAStartup] {len(parsed)} intern postings via JSON API")
                    return jobs
        except Exception:
            continue

    # Approach 2: Companies page filtered by intern jobs, JSON response
    try:
        co_url = "https://www.workatastartup.com/companies.json?jobType=intern"
        r = requests.get(co_url, headers=json_headers, timeout=15)
        if r.status_code == 200 and r.text.strip()[:1] in ("[", "{"):
            data = r.json()
            companies = data if isinstance(data, list) else data.get("startups", []) or []
            raw = []
            for co in companies:
                for job in (co.get("jobs") or []):
                    job.setdefault("company", {"name": co.get("name", "")})
                    raw.append(job)
            if raw:
                parsed = _parse_yc_jobs(raw, "workatastartup")
                jobs.extend(parsed)
                print(f"[YC/WorkAtAStartup] {len(parsed)} intern postings via companies JSON")
                return jobs
    except Exception:
        pass

    print("[YC/WorkAtAStartup] No intern postings found — site may require login or API changed")
    return jobs


# ── Wellfound (AngelList) ──────────────────────────────────────────────────────

def scrape_wellfound_intern() -> list[dict]:
    """
    Wellfound (formerly AngelList) startup internships.
    Wellfound uses client-side React — tries their internal search API.
    Falls back gracefully if blocked or structure changes.
    """
    jobs = []

    # Approach 1: Wellfound internal search API (reverse-engineered from network tab)
    try:
        api_url = "https://wellfound.com/role/l/intern"
        api_headers = {
            **HEADERS,
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
        }
        r = requests.get(api_url, headers=api_headers, timeout=15)
        if r.status_code == 200 and r.text.strip()[:1] in ("[", "{"):
            data = r.json()
            raw = (data.get("roleListings") or data.get("listings") or
                   data.get("roles") or data.get("jobs") or
                   (data if isinstance(data, list) else []))
            for item in raw:
                if not isinstance(item, dict):
                    continue
                role = item.get("role", item)
                title = role.get("title", "") or item.get("title", "") or ""
                if not _is_intern_title(title):
                    continue
                company_data = item.get("company", role.get("startup", {})) or {}
                company = company_data.get("name", "") if isinstance(company_data, dict) else str(company_data)
                slug = role.get("slug", "") or item.get("slug", "") or str(role.get("id", ""))
                job_url = role.get("url", "") or item.get("url", "")
                if not job_url and slug:
                    job_url = f"https://wellfound.com/jobs/{slug}"
                if not job_url or not job_url.startswith("http"):
                    continue
                loc_list = role.get("locationNames", []) or item.get("locationNames", [])
                jobs.append({
                    "title":          title or "Intern",
                    "company":        company or "Wellfound Startup",
                    "url":            job_url,
                    "location":       loc_list[0] if loc_list else "USA",
                    "salary":         "",
                    "description":    "",
                    "tags":           ["internship", "wellfound", "startup"],
                    "source":         "wellfound",
                    "date_posted":    "",
                    "num_applicants": "",
                })
            if jobs:
                print(f"[Wellfound] {len(jobs)} intern postings")
                return jobs
    except Exception:
        pass

    # Approach 2: Parse embedded JSON blobs from HTML (some pages embed window.__data)
    try:
        r = requests.get("https://wellfound.com/role/l/intern", headers=HEADERS, timeout=15)
        if r.status_code == 200:
            for pattern in [
                r'"roleListings"\s*:\s*(\[.+?\])',
                r'"listings"\s*:\s*(\[.+?\])',
                r'"roles"\s*:\s*(\[.+?\])',
            ]:
                m = re.search(pattern, r.text, re.DOTALL)
                if m:
                    try:
                        raw = json.loads(m.group(1))
                        for item in raw:
                            if not isinstance(item, dict):
                                continue
                            title = item.get("title", "") or ""
                            if not _is_intern_title(title):
                                continue
                            company_data = item.get("startup", item.get("company", {})) or {}
                            company = company_data.get("name", "") if isinstance(company_data, dict) else ""
                            slug = str(item.get("slug", "") or item.get("id", ""))
                            job_url = item.get("url", "") or (f"https://wellfound.com/jobs/{slug}" if slug else "")
                            if not job_url:
                                continue
                            jobs.append({
                                "title":          title,
                                "company":        company or "Wellfound Startup",
                                "url":            job_url,
                                "location":       "USA",
                                "salary":         "",
                                "description":    "",
                                "tags":           ["internship", "wellfound", "startup"],
                                "source":         "wellfound",
                                "date_posted":    "",
                                "num_applicants": "",
                            })
                        if jobs:
                            print(f"[Wellfound] {len(jobs)} intern postings (HTML parse)")
                            return jobs
                    except Exception:
                        continue
    except Exception:
        pass

    print("[Wellfound] No listings found — site uses client-side rendering, login may be required")
    return jobs


# ── WayUp ─────────────────────────────────────────────────────────────────────

def scrape_wayup_intern() -> list[dict]:
    """
    WayUp — platform focused exclusively on student internships and entry-level jobs.
    Tries JSON API and embedded state; fails gracefully if login is required.
    """
    jobs = []

    api_attempts = [
        "https://www.wayup.com/api/listing/search/?q=internship&type=internship&page_size=50",
        "https://www.wayup.com/api/v1/listings/?q=intern&listing_type=internship",
        "https://www.wayup.com/listing/?q=internship&type=internship",
        "https://www.wayup.com/s/internship-jobs/",
    ]

    for url in api_attempts:
        try:
            r = requests.get(url, headers={**HEADERS, "Accept": "application/json"}, timeout=15)
            if r.status_code != 200:
                continue

            raw = []
            # Try JSON parse first
            if r.text.strip()[:1] in ("[", "{"):
                data = r.json()
                raw = (data if isinstance(data, list) else
                       data.get("jobs", []) or data.get("listings", []) or
                       data.get("results", []) or data.get("data", []))
            else:
                # Try embedded state patterns in HTML
                for pat in [
                    r'window\.__INITIAL_STATE__\s*=\s*({.+?});\s*</script>',
                    r'window\.__PRELOADED_STATE__\s*=\s*({.+?});\s*</script>',
                    r'"listings"\s*:\s*(\[.+?\])',
                    r'"results"\s*:\s*(\[.+?\])',
                ]:
                    m = re.search(pat, r.text, re.DOTALL)
                    if m:
                        try:
                            d = json.loads(m.group(1))
                            raw = d if isinstance(d, list) else (
                                d.get("jobs", []) or d.get("listings", []) or d.get("results", [])
                            )
                            if raw:
                                break
                        except Exception:
                            continue

            if not raw:
                continue

            for item in raw:
                if not isinstance(item, dict):
                    continue
                title = item.get("title", "") or item.get("position", "") or ""
                if not _is_intern_title(title):
                    continue

                company = (item.get("company_name", "") or item.get("company", "") or "")
                if isinstance(company, dict):
                    company = company.get("name", "")

                job_url = item.get("url", "") or item.get("apply_url", "") or ""
                if not job_url:
                    job_id = item.get("id", "")
                    if job_id:
                        job_url = f"https://www.wayup.com/listing/{job_id}/"
                if not job_url:
                    continue
                if not job_url.startswith("http"):
                    job_url = "https://www.wayup.com" + job_url

                description = re.sub(r"<[^>]+>", " ", item.get("description", "") or "").strip()[:3000]

                jobs.append({
                    "title":          title,
                    "company":        company or "Unknown",
                    "url":            job_url,
                    "location":       item.get("location", "") or "USA",
                    "salary":         "",
                    "description":    description,
                    "tags":           ["internship", "wayup", "student"],
                    "source":         "wayup",
                    "date_posted":    item.get("created_at", "") or item.get("posted_at", ""),
                    "num_applicants": "",
                })

            if jobs:
                print(f"[WayUp] {len(jobs)} intern postings")
                return jobs
        except Exception:
            continue

    print("[WayUp] No listings found — site may require student login")
    return jobs


# ── Main entry point ──────────────────────────────────────────────────────────

def scrape_all_company_internships() -> list[dict]:
    """
    Scrape internships from:
      • Greenhouse (100+ companies)
      • Lever (40+ companies)
      • Y Combinator / Work at a Startup
      • Wellfound (AngelList)
      • WayUp (student internship platform)
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

    print("\n── WayUp (student internships) ───────────────")
    all_jobs.extend(scrape_wayup_intern())

    # Deduplicate by URL
    seen: set[str] = set()
    unique: list[dict] = []
    for job in all_jobs:
        if job["url"] not in seen:
            seen.add(job["url"])
            unique.append(job)

    print(f"\n[Company Career Pages] Total unique intern jobs: {len(unique)}")
    return unique
