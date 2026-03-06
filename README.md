# Veena's Job Application System

Automated job hunting for remote tech/AI/ML roles.

## What it does
1. **Scrapes** LinkedIn, Indeed, RemoteOK, and We Work Remotely daily
2. **Scores** each job 1–10 using Claude AI against your profile
3. **Generates** a tailored cover letter per job
4. **Auto-applies** via LinkedIn Easy Apply and Indeed Quick Apply
5. **Tracks** everything in a local dashboard

## Quick Start

### 1. Setup
Double-click `setup.bat` OR run in terminal:
```
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure
- **`.env`** — Add your `ANTHROPIC_API_KEY` and job keywords
- **`config.py`** — Fill in YOUR name, skills, experience, and projects

### 3. Run
```bash
# Test scraping only (safe, no AI calls)
python main.py --scrape-only

# Full run — scrape + score + generate cover letters (dry run, won't submit)
python main.py

# Full run AND actually submit applications
python main.py --apply

# Open the visual tracker dashboard
python main.py --dashboard
```

## File Overview
| File | Purpose |
|------|---------|
| `config.py` | **Your profile** — fill this in first |
| `.env` | API keys and settings |
| `main.py` | Run the full pipeline |
| `scraper.py` | Scrapes job boards |
| `ai_engine.py` | Claude AI — scoring and cover letters |
| `auto_apply.py` | Playwright browser automation |
| `database.py` | SQLite job tracker |
| `dashboard.py` | Streamlit visual dashboard |
| `jobs.db` | Auto-created — your job database |

## Getting an API Key
1. Go to https://console.anthropic.com
2. Create an account and go to API Keys
3. Copy your key into `.env` as `ANTHROPIC_API_KEY=sk-ant-...`

## Notes
- Set `dry_run=True` (default) to test the auto-apply flow without submitting
- Jobs are deduplicated by URL — re-running won't create duplicates
- LinkedIn and Indeed may require solving a CAPTCHA on first login
- RemoteOK and We Work Remotely don't require login
