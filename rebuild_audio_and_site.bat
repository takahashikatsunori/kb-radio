@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1

echo ========================================================
echo   こだいら防災＆まちラジオ 音声＆サイト再ビルド
echo ========================================================
echo.

if not exist ".env" (
    echo [エラー] .env ファイルが見つかりません。
    echo .env.example を「.env」にコピーし、GEMINI_API_KEY を設定してから再実行してください。
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

echo [1/2] 最新エピソードの音声を Gemini 3.8 Flash TTS で再生成中...
".venv\Scripts\python.exe" src\build_radio.py --latest --tts-engine gemini --bitrate 112k
if errorlevel 1 goto :fail

echo.
echo [2/2] 同期プレーヤーとポータルサイトを更新中...
".venv\Scripts\python.exe" src\build_site.py
if errorlevel 1 goto :fail

echo.
echo ========================================================
echo   再ビルドが完了しました！ブラウザでプレーヤーを開きます。
echo ========================================================
start "" "%~dp0docs\index.html"
pause
exit /b 0

:fail
echo.
echo [エラー] 処理の途中で問題が発生しました。上のメッセージをご確認ください。
pause
exit /b 1
