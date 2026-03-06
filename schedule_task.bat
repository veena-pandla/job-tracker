@echo off
echo Setting up daily job application task...

schtasks /create /tn "DailyJobApply" /tr "\"C:\Users\veena\Downloads\job-application-system\run_jobs.bat\"" /sc daily /st 09:00 /f

echo.
echo ============================================
echo   SUCCESS! Task scheduled for 9:00 AM daily
echo   Name: DailyJobApply
echo ============================================
echo.
echo Your computer must be ON at 9am for it to run.
echo To change the time, search "Task Scheduler" in Windows.
pause
