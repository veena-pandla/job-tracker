@echo off
cd /d "C:\Users\veena\Downloads\job-application-system"
echo ============================================
echo   Job Application System - Daily Run
echo   %date% %time%
echo ============================================
"C:\Users\veena\AppData\Local\Programs\Python\Python314\python.exe" main.py >> logs\run_log.txt 2>&1
echo Done. Check logs\run_log.txt for results.
