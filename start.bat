@echo off
chcp 65001 > nul 2>&1
setlocal EnableDelayedExpansion
title XAUUSD AI Trading System

echo.
echo  =========================================================
echo   XAUUSD AI Trading System  --  Startup
echo  =========================================================
echo.

:: ── 1. Setup .env ─────────────────────────────────────────────
if not exist ".env" (
    if not exist ".env.example" (
        echo  [ERROR] ไม่พบ .env.example -- clone repo ใหม่
        pause & exit /b 1
    )
    copy ".env.example" ".env" > nul
    echo  [SETUP] สร้าง .env แล้ว -- กรุณากรอกข้อมูลต่อไปนี้:
    echo.
    echo    ANTHROPIC_API_KEY  -- จาก https://console.anthropic.com
    echo    MT5_LOGIN          -- หมายเลขบัญชี MT5
    echo    MT5_PASSWORD       -- รหัสผ่าน MT5
    echo    MT5_SERVER         -- เช่น XMGlobal-MT5 13
    echo    X_USERNAME         -- Twitter/X username
    echo    X_PASSWORD         -- Twitter/X password
    echo    X_EMAIL            -- อีเมล Twitter/X
    echo.
    echo  กำลังเปิด .env ใน Notepad...
    start /wait notepad ".env"
    echo  กด Enter เมื่อบันทึกเสร็จแล้ว...
    pause > nul
)

:: ── 2. Create logs dir ────────────────────────────────────────
if not exist "logs" mkdir "logs"

:: ── 3. Check MetaTrader5 ──────────────────────────────────────
echo  [1/4] ตรวจสอบ MetaTrader5 Terminal...
set MT5_FOUND=0
if exist "%ProgramFiles%\MetaTrader 5\terminal64.exe" set MT5_FOUND=1
if exist "%ProgramW6432%\MetaTrader 5\terminal64.exe" set MT5_FOUND=1
if exist "%APPDATA%\MetaQuotes\Terminal" set MT5_FOUND=1

if "%MT5_FOUND%"=="0" (
    echo.
    echo  [!] ไม่พบ MetaTrader5 Terminal
    echo.
    echo      MT5 จำเป็นสำหรับการเทรด -- ดาวน์โหลดฟรีที่:
    echo      https://www.metatrader5.com/en/download
    echo.
    echo      หลังติดตั้ง: เปิด MT5 + Login บัญชีค้างไว้ แล้วรัน start.bat ใหม่
    echo.
    start "" "https://www.metatrader5.com/en/download"
    pause & exit /b 1
)
echo  [OK] MT5 พบแล้ว -- ตรวจสอบว่า MT5 เปิดและ Login แล้ว

:: ── 4. Check Docker ───────────────────────────────────────────
echo  [2/4] ตรวจสอบ Docker...
docker info > nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  [!] Docker Desktop ยังไม่รัน
    echo      กรุณาเปิด Docker Desktop แล้วรอให้ whale icon ปรากฏใน taskbar
    echo      กด Enter เมื่อพร้อมแล้ว...
    pause > nul
    docker info > nul 2>&1
    if %errorlevel% neq 0 (
        echo  [ERROR] Docker ยังไม่พร้อม -- ลองรัน start.bat ใหม่
        pause & exit /b 1
    )
)
echo  [OK] Docker พร้อม

:: ── 5. Start Dashboard ────────────────────────────────────────
echo  [3/4] เริ่ม Dashboard (Docker)...
docker compose up -d --build 2>&1
if %errorlevel% neq 0 (
    echo  [ERROR] Dashboard Docker ล้มเหลว -- ดู error ด้านบน
    pause & exit /b 1
)
echo  [OK] Dashboard >> http://localhost:5050

:: ── 6. Setup Python + Bot ─────────────────────────────────────
echo  [4/4] ตรวจสอบ Python สำหรับ Trading Bot...
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo  [!] ไม่พบ Python -- กำลังติดตั้งผ่าน winget...
    winget install Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    if %errorlevel% neq 0 (
        echo.
        echo  [ERROR] ติดตั้ง Python ไม่สำเร็จ
        echo          ดาวน์โหลดเอง: https://www.python.org/downloads/
        echo          ** เลือก "Add Python to PATH" **
        echo          แล้วรัน start.bat ใหม่
        start "" "https://www.python.org/downloads/"
        pause & exit /b 1
    )
    echo  [OK] ติดตั้ง Python เสร็จแล้ว -- กรุณาปิดและเปิด start.bat ใหม่
    pause & exit /b 0
)
echo  [OK] Python พร้อม

echo       ติดตั้ง packages...
pip install -r requirements.txt -q --disable-pip-version-check
if %errorlevel% neq 0 (
    echo  [ERROR] pip install ล้มเหลว
    pause & exit /b 1
)
echo  [OK] Packages พร้อม

:: ── 7. Launch ─────────────────────────────────────────────────
echo.
echo  =========================================================
echo   ระบบพร้อมทำงาน!
echo.
echo   Dashboard   : http://localhost:5050
echo   Bot Logs    : logs\system.log
echo   Trade Logs  : logs\trades.json
echo.
echo   หยุด Bot      : Ctrl+C ในหน้าต่างนี้
echo   หยุด Dashboard: docker compose down
echo  =========================================================
echo.

python main.py
