@echo off
:: Navigate to the directory where this batch file is located
cd /d "%~dp0"

:: Launch Python in unbuffered mode using the relative path to host.py
python -u "host.py"