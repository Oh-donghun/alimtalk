@echo off
chcp 65001 >nul
cd /d %~dp0
echo 알림톡 자동발송 대기 중... 이 창을 닫으면 자동발송이 멈춥니다.
python run.py --daemon
pause
