@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1

echo ========================================================
echo   毎朝7時！こだいら防災＆まちラジオ 自動生成ランチャー
echo ========================================================
echo.

if not exist ".env" (
    echo [エラー] .env ファイルが見つかりません。
    echo 1. .env.example をコピーして「.env」という名前で保存してください。
    echo 2. メモ帳などで .env を開き、GEMINI_API_KEY= の後ろに
    echo    Google AI Studio の APIキーを貼り付けて保存してください。
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [準備] Python仮想環境を作成し、必要なパッケージをインストールします...
    python -m venv .venv
    if errorlevel 1 goto :fail
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :fail
)

echo [1/3] 今日の放送台本を生成・確認しています...
".venv\Scripts\python.exe" src\generate_episode.py
if errorlevel 1 goto :fail

echo.
echo [2/3] Gemini 3.8 Flash TTS で音声合成・MP3マスタリングを実行中...
".venv\Scripts\python.exe" src\build_radio.py --latest --tts-engine gemini --bitrate 112k
if errorlevel 1 goto :fail

echo.
echo [3/3] 同期プレーヤーとポータルサイトを更新中...
".venv\Scripts\python.exe" src\build_site.py
if errorlevel 1 goto :fail

echo.
echo ========================================================
echo   生成が完了しました！ブラウザでプレーヤーを開きます。
echo ========================================================
start "" "%~dp0docs\index.html"
pause
exit /b 0

:fail
echo.
echo [エラー] 処理の途中で問題が発生しました。上のメッセージをご確認ください。
pause
exit /b 1
