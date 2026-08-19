#!/bin/bash
# ============================================================
#  서버 최초 세팅 (우분투). 사용법:  bash setup_linux.sh
#  - 파이썬 설치, 자동실행 등록(평일 15:30/16:30), 관리페이지 상시 실행
# ============================================================
set -e
cd "$(dirname "$0")"
DIR=$(pwd)

echo "[1/5] 필요한 프로그램 설치..."
sudo apt-get update -y >/dev/null
sudo apt-get install -y python3 python3-pip python3-venv curl >/dev/null
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

echo "[2/5] 시간대를 한국으로..."
sudo timedatectl set-timezone Asia/Seoul

echo "[3/5] 설정 파일 준비..."
[ -f config.yaml ] || cp config.example.yaml config.yaml
mkdir -p logs out

echo "[4/5] 자동 실행 등록(평일 15:30 / 16:30)..."
( crontab -l 2>/dev/null | grep -v "alimtalk" ; \
  echo "30 15 * * 1-5 cd $DIR && .venv/bin/python run.py --shop ojingeo_mom >> logs/cron.log 2>&1  # alimtalk" ; \
  echo "30 16 * * 1-5 cd $DIR && .venv/bin/python run.py --shop donggwang   >> logs/cron.log 2>&1  # alimtalk" ) | crontab -

echo "[5/5] 관리 페이지 서비스 등록..."
sudo tee /etc/systemd/system/alimtalk-web.service >/dev/null <<SVC
[Unit]
Description=Alimtalk admin web
After=network.target
[Service]
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python $DIR/run.py --web
Restart=always
User=$USER
[Install]
WantedBy=multi-user.target
SVC
sudo systemctl daemon-reload
sudo systemctl enable --now alimtalk-web

IP=$(curl -s ifconfig.me || echo "확인실패")
echo ""
echo "===================================================================="
echo " 설치 완료"
echo " 이 서버의 고정 IP (알리고 발신 IP에 등록하세요) :  $IP"
echo ""
echo " 다음 순서:"
echo "   1) nano config.yaml   → 키 값들과 web.token 입력 후 Ctrl+O, Enter, Ctrl+X"
echo "   2) sudo systemctl restart alimtalk-web"
echo "   3) .venv/bin/python run.py --check      (연결 점검)"
echo "   4) 브라우저에서  http://$IP:8080/?token=<web.token 값>"
echo "===================================================================="
