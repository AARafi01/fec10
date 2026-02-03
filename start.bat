@echo off
REM DU Crack - Quick Start Script

echo ========================================
echo  DU Crack Web Application
echo ========================================
echo.

echo [1/3] Installing dependencies...
pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo.

echo [2/3] Initializing database...
python init_db.py
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to initialize database
    pause
    exit /b 1
)
echo.

echo [3/3] Starting Flask application...
echo.
echo ========================================
echo  Application is starting...
echo  Home Page: http://localhost:5000
echo  Admin Panel: http://localhost:5000/admin
echo ========================================
echo.
echo Press Ctrl+C to stop the server
echo.

python app.py
