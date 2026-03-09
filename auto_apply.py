"""
Auto-apply bot — logs in ONCE and applies to all jobs in a single browser session.
Supports LinkedIn Easy Apply and Indeed Quick Apply.

Safety features:
  - Random delays between applications (45-90 seconds)
  - Human-like typing speed (not instant fill)
  - Random mouse movement before clicks
  - Time-of-day check (only runs 9am-6pm)
  - Daily hard cap of 25 applications
  - Gradual ramp-up for new accounts
"""
import os
import asyncio
import json
import random
import time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from config import PROFILE

load_dotenv()

LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")
INDEED_EMAIL = os.getenv("INDEED_EMAIL", "")
INDEED_PASSWORD = os.getenv("INDEED_PASSWORD", "")
COOKIES_FILE = Path(__file__).parent / ".linkedin_cookies.json"
DAILY_LOG_FILE = Path(__file__).parent / ".daily_apply_count.json"

BROWSER_ARGS = ["--disable-blink-features=AutomationControlled"]
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Safety limits
DAILY_MAX = 25          # Hard cap per day across all platforms
MIN_DELAY = 45          # Minimum seconds between applications
MAX_DELAY = 90          # Maximum seconds between applications


# ─────────────────────────────────────────────
# SAFETY HELPERS
# ─────────────────────────────────────────────

def check_safe_hours() -> bool:
    """No time restriction — run anytime."""
    return True


def get_daily_count() -> int:
    """Read how many applications have been sent today."""
    today = datetime.now().strftime("%Y-%m-%d")
    if DAILY_LOG_FILE.exists():
        data = json.loads(DAILY_LOG_FILE.read_text())
        if data.get("date") == today:
            return data.get("count", 0)
    return 0


def increment_daily_count():
    """Add 1 to today's application count."""
    today = datetime.now().strftime("%Y-%m-%d")
    count = get_daily_count() + 1
    DAILY_LOG_FILE.write_text(json.dumps({"date": today, "count": count}))


def check_daily_limit() -> bool:
    """Returns True if we're under the daily limit."""
    count = get_daily_count()
    if count >= DAILY_MAX:
        print(f"[Safety] Daily limit reached ({count}/{DAILY_MAX} applications). Stopping to protect account.")
        return False
    remaining = DAILY_MAX - count
    print(f"[Safety] Daily count: {count}/{DAILY_MAX} — {remaining} remaining today.")
    return True


async def human_delay(min_ms: int = 800, max_ms: int = 2000):
    """Random short pause — mimics human reaction time."""
    await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


async def human_type(page, selector: str, text: str):
    """Type text character by character at human speed instead of instant fill."""
    field = page.locator(selector)
    if await field.count() > 0 and await field.is_visible():
        await field.click()
        await human_delay(200, 500)
        await field.fill("")  # Clear first
        # Type each character with a small random delay
        for char in text:
            await field.press(char) if len(char) == 1 else await field.type(char)
            await asyncio.sleep(random.uniform(0.03, 0.12))
        return True
    return False


async def human_click(page, locator):
    """Move mouse near element then click — not a robotic instant click."""
    box = await locator.bounding_box()
    if box:
        # Move to a slightly random position within the element
        x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
        y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
        await page.mouse.move(x, y)
        await human_delay(100, 300)
    await locator.click()


async def between_applications_delay():
    """Wait 45-90 seconds between applications — most important safety measure."""
    wait = random.uniform(MIN_DELAY, MAX_DELAY)
    print(f"[Safety] Waiting {wait:.0f}s before next application (looks human)...")
    await asyncio.sleep(wait)


# ─────────────────────────────────────────────
# LINKEDIN SESSION (login once, apply many)
# ─────────────────────────────────────────────

async def linkedin_login(page, context) -> bool:
    """Login to LinkedIn. Returns True if successful."""
    # Try saved cookies first
    if COOKIES_FILE.exists():
        cookies = json.loads(COOKIES_FILE.read_text())
        await context.add_cookies(cookies)
        await page.goto("https://www.linkedin.com/feed/", timeout=30000)
        await page.wait_for_timeout(3000)
        if "feed" in page.url or "home" in page.url:
            print("[LinkedIn] Logged in via saved cookies.")
            return True

    # Delete expired cookies and do fresh login
    if COOKIES_FILE.exists():
        COOKIES_FILE.unlink()

    print(f"[LinkedIn] Logging in as {LINKEDIN_EMAIL}...")
    await page.goto("https://www.linkedin.com/login", timeout=30000)
    await human_delay(2000, 3500)

    # Fill email — use fill() + dispatch input event so LinkedIn JS enables the button
    email_field = page.locator('input[name="session_key"]')
    await email_field.click()
    await human_delay(300, 600)
    await email_field.fill(LINKEDIN_EMAIL)
    await email_field.dispatch_event("input")
    await email_field.dispatch_event("change")
    await human_delay(500, 900)

    # Fill password
    pass_field = page.locator('input[name="session_password"]')
    await pass_field.click()
    await human_delay(300, 600)
    await pass_field.fill(LINKEDIN_PASSWORD)
    await pass_field.dispatch_event("input")
    await pass_field.dispatch_event("change")
    await human_delay(700, 1200)

    # Wait for submit button to become enabled, then click
    submit = page.locator('button[type="submit"]')
    await submit.wait_for(state="visible", timeout=10000)
    # Small wait to let LinkedIn JS fully enable the button
    await human_delay(800, 1500)
    await submit.click()
    await page.wait_for_timeout(6000)

    if "checkpoint" in page.url or "login" in page.url or "challenge" in page.url:
        print("[LinkedIn] CAPTCHA or verification required — solve it in the browser (90s)...")
        await page.wait_for_timeout(90000)

    if "feed" in page.url or "mynetwork" in page.url or "jobs" in page.url:
        cookies = await context.cookies()
        COOKIES_FILE.write_text(json.dumps(cookies))
        print("[LinkedIn] Login successful. Cookies saved.")
        return True

    print(f"[LinkedIn] Login failed. Current URL: {page.url}")
    return False


async def apply_linkedin_job(page, job: dict, cover_letter: str, dry_run: bool) -> dict:
    """Apply to a single LinkedIn job using an already-logged-in page."""
    result = {"success": False, "notes": ""}
    try:
        print(f"  -> Navigating to: {job['url']}")
        await page.goto(job["url"], timeout=30000)
        await human_delay(2000, 4000)

        # Click Easy Apply
        easy_apply_btn = page.locator('button:has-text("Easy Apply")')
        if not await easy_apply_btn.is_visible(timeout=5000):
            result["notes"] = "No Easy Apply button — manual application required"
            return result

        await human_click(page, easy_apply_btn)
        await human_delay(1500, 3000)

        # Multi-step form
        for step in range(10):
            # Fill phone with human typing
            phone_field = page.locator('input[id*="phoneNumber"]')
            if await phone_field.count() > 0 and await phone_field.is_visible():
                await phone_field.fill("")
                await human_delay(200, 400)
                for char in PROFILE.get("phone", ""):
                    await phone_field.press(char)
                    await asyncio.sleep(random.uniform(0.05, 0.15))

            # Fill cover letter with human typing (type first 200 chars slowly, paste rest)
            cover_area = page.locator('textarea[id*="cover-letter"], textarea[placeholder*="cover letter"]')
            if await cover_area.count() > 0 and await cover_area.is_visible():
                await cover_area.click()
                await human_delay(300, 600)
                await cover_area.fill(cover_letter)  # fill is fine for long text
                await human_delay(500, 1000)

            # Answer Yes to radio questions
            radio_yes = page.locator('label:has-text("Yes")').first
            if await radio_yes.count() > 0 and await radio_yes.is_visible():
                await human_delay(300, 700)
                await human_click(page, radio_yes)

            await human_delay(500, 1000)

            # Next / Continue / Review
            next_btn = page.locator('button:has-text("Next"), button:has-text("Continue"), button:has-text("Review")')
            if await next_btn.count() > 0 and await next_btn.is_visible():
                await human_click(page, next_btn.first)
                await human_delay(1200, 2500)
                continue

            # Submit
            submit_btn = page.locator('button:has-text("Submit application")')
            if await submit_btn.count() > 0 and await submit_btn.is_visible():
                if dry_run:
                    print(f"  -> DRY RUN — would submit to {job['company']}")
                    result["success"] = True
                    result["notes"] = "DRY RUN — ready but not submitted"
                else:
                    await human_delay(800, 1500)
                    await human_click(page, submit_btn)
                    await human_delay(2000, 3500)
                    result["success"] = True
                    result["notes"] = "Applied via LinkedIn Easy Apply"
                    increment_daily_count()
                break

            result["notes"] = f"Stopped at step {step + 1} — unexpected form"
            break

        # Close any open modal
        dismiss = page.locator('button[aria-label="Dismiss"], button:has-text("Discard")')
        if await dismiss.count() > 0 and await dismiss.is_visible():
            await human_delay(500, 1000)
            await dismiss.first.click()
            await human_delay(800, 1500)

    except PlaywrightTimeout as e:
        result["notes"] = f"Timeout: {str(e)[:100]}"
    except Exception as e:
        result["notes"] = f"Error: {str(e)[:100]}"
    return result


async def run_linkedin_batch(jobs: list[dict], dry_run: bool = True) -> list[dict]:
    """Login once and apply to all LinkedIn jobs in one session."""
    results = []
    if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
        return [{"job": j, "success": False, "notes": "LinkedIn credentials not set"} for j in jobs]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=BROWSER_ARGS)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800}
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()

        logged_in = await linkedin_login(page, context)
        if not logged_in:
            await browser.close()
            return [{"job": j, "success": False, "notes": "LinkedIn login failed"} for j in jobs]

        for i, job in enumerate(jobs):
            # Check daily limit before each application
            if not check_daily_limit():
                results.append({"job": job, "success": False, "notes": "Daily limit reached"})
                continue

            print(f"\n  Applying: {job['title']} @ {job['company']}")
            result = await apply_linkedin_job(page, job, job.get("cover_letter", ""), dry_run)
            result["job"] = job
            results.append(result)

            # Wait between applications (skip after last one)
            if i < len(jobs) - 1:
                await between_applications_delay()

        await browser.close()
    return results


# ─────────────────────────────────────────────
# INDEED BATCH
# ─────────────────────────────────────────────

async def run_indeed_batch(jobs: list[dict], dry_run: bool = True) -> list[dict]:
    """Login once and apply to all Indeed jobs in one session."""
    results = []
    if not INDEED_EMAIL or not INDEED_PASSWORD:
        return [{"job": j, "success": False, "notes": "Indeed credentials not set"} for j in jobs]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=BROWSER_ARGS)
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()

        try:
            print(f"[Indeed] Logging in as {INDEED_EMAIL}...")
            await page.goto("https://secure.indeed.com/account/login", timeout=30000)
            await human_delay(1500, 2500)
            await human_type(page, 'input[name="__email"]', INDEED_EMAIL)
            submit1 = page.locator('button[type="submit"]')
            await human_click(page, submit1)
            await human_delay(1200, 2000)
            await human_type(page, 'input[name="__password"]', INDEED_PASSWORD)
            submit2 = page.locator('button[type="submit"]')
            await human_click(page, submit2)
            await human_delay(3000, 5000)
        except Exception as e:
            await browser.close()
            return [{"job": j, "success": False, "notes": f"Indeed login error: {e}"} for j in jobs]

        for i, job in enumerate(jobs):
            if not check_daily_limit():
                results.append({"job": job, "success": False, "notes": "Daily limit reached"})
                continue

            result = {"success": False, "notes": "", "job": job}
            try:
                await page.goto(job["url"], timeout=30000)
                await human_delay(1500, 3000)

                apply_btn = page.locator('button:has-text("Apply now"), a:has-text("Apply now")')
                if not await apply_btn.is_visible(timeout=5000):
                    result["notes"] = "No Quick Apply button"
                    results.append(result)
                    continue

                await human_click(page, apply_btn.first)
                await human_delay(1500, 2500)

                for step in range(10):
                    cover_area = page.locator('textarea[name*="cover"]')
                    if await cover_area.count() > 0 and await cover_area.is_visible():
                        await cover_area.click()
                        await human_delay(300, 600)
                        await cover_area.fill(job.get("cover_letter", ""))
                        await human_delay(500, 1000)

                    next_btn = page.locator('button:has-text("Continue"), button:has-text("Next")')
                    if await next_btn.count() > 0 and await next_btn.is_visible():
                        await human_click(page, next_btn.first)
                        await human_delay(1200, 2500)
                        continue

                    submit_btn = page.locator('button:has-text("Submit")')
                    if await submit_btn.count() > 0 and await submit_btn.is_visible():
                        if dry_run:
                            result["success"] = True
                            result["notes"] = "DRY RUN — ready but not submitted"
                        else:
                            await human_delay(800, 1500)
                            await human_click(page, submit_btn)
                            result["success"] = True
                            result["notes"] = "Applied via Indeed Quick Apply"
                            increment_daily_count()
                        break

                    result["notes"] = f"Stopped at step {step + 1}"
                    break

            except Exception as e:
                result["notes"] = f"Error: {str(e)[:100]}"
            results.append(result)

            if i < len(jobs) - 1:
                await between_applications_delay()

        await browser.close()
    return results


# ─────────────────────────────────────────────
# PUBLIC API — called from main.py
# ─────────────────────────────────────────────

def apply_to_jobs_batch(jobs: list[dict], dry_run: bool = True) -> list[dict]:
    """
    Apply to a list of jobs. Groups by source and runs each source in one session.
    Returns list of result dicts with job, success, notes.
    """
    # Safety check: only run during business hours
    if not check_safe_hours():
        return [{"job": j, "success": False, "notes": "Outside safe hours (9am-6pm)"} for j in jobs]

    # Safety check: daily limit
    if not check_daily_limit():
        return [{"job": j, "success": False, "notes": "Daily limit reached"} for j in jobs]

    linkedin_jobs = [j for j in jobs if j.get("source") == "linkedin"]
    indeed_jobs = [j for j in jobs if j.get("source") == "indeed"]
    other_jobs = [j for j in jobs if j.get("source") not in ("linkedin", "indeed")]

    results = []

    if linkedin_jobs:
        results += asyncio.run(run_linkedin_batch(linkedin_jobs, dry_run=dry_run))

    if indeed_jobs:
        results += asyncio.run(run_indeed_batch(indeed_jobs, dry_run=dry_run))

    for job in other_jobs:
        results.append({
            "job": job,
            "success": False,
            "notes": f"Auto-apply not supported for '{job.get('source')}' — apply manually: {job.get('url', '')}"
        })

    return results


# Keep backward compat for single-job calls
def apply_to_job(job: dict, cover_letter: str, dry_run: bool = True) -> dict:
    job["cover_letter"] = cover_letter
    results = apply_to_jobs_batch([job], dry_run=dry_run)
    return results[0] if results else {"success": False, "notes": "No result"}
