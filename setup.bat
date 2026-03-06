@echo off
echo ============================================
echo   Job Application System — Setup
echo ============================================

echo.
echo [1/4] Installing Python packages...
pip install -r requirements.txt

echo.
echo [2/4] Installing Playwright browsers...
playwright install chromium

echo.
echo [3/4] Creating .env from template...
if not exist .env (
    copy .env.example .env
    echo   .env created! Open it and fill in your API key and credentials.
) else (
    echo   .env already exists, skipping.
)

echo.
echo [4/4] Setup complete!
echo.
echo NEXT STEPS:
echo   1. Edit .env  — add your ANTHROPIC_API_KEY and job search keywords
echo   2. Edit config.py — fill in YOUR profile (name, skills, experience)
echo   3. Run: python main.py --scrape-only    (test scraping)
echo   4. Run: python main.py                  (full run, dry run mode)
echo   5. Run: python main.py --dashboard      (open tracker)
echo.
pause
