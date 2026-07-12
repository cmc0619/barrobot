#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this installer as root." >&2
  exit 1
fi

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
id barrobot >/dev/null 2>&1 || useradd --system --home /var/lib/barrobot --shell /usr/sbin/nologin barrobot
usermod --append --groups gpio barrobot

cd "$ROOT_DIR"
npm ci
npm run build
make -C motiond clean all
npm prune --omit=dev

install -d -o root -g root -m 0755 /opt/barrobot/app /opt/barrobot/bin
install -d -o barrobot -g barrobot -m 0750 /var/lib/barrobot
cp -a dist node_modules package.json package-lock.json web /opt/barrobot/app/
install -o root -g root -m 0755 motiond/build/barrobot-motiond /opt/barrobot/bin/barrobot-motiond
install -o root -g root -m 0644 deploy/barrobot-motion.service /etc/systemd/system/barrobot-motion.service
install -o root -g root -m 0644 deploy/barrobot.service /etc/systemd/system/barrobot.service

systemctl daemon-reload
systemctl enable --now barrobot-motion.service barrobot.service
systemctl --no-pager --full status barrobot-motion.service barrobot.service
