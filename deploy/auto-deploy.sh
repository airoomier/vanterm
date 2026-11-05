#!/bin/bash
# Vanterm otomatik dağıtım (cPanel cron ile her 5 dakikada bir çalışır).
# GitHub'da yeni commit varsa çeker ve site/ klasörünü public_html'e kopyalar.
# Cron komutu:  /bin/bash $HOME/repositories/vanterm/deploy/auto-deploy.sh >/dev/null 2>&1

REPO="$HOME/repositories/vanterm"
TARGET="$HOME/public_html"
LOG="$HOME/vanterm-deploy.log"

cd "$REPO" || exit 1
git fetch -q origin main || { echo "$(date '+%F %T') fetch hatası" >> "$LOG"; exit 1; }

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
[ "$LOCAL" = "$REMOTE" ] && exit 0

git reset -q --hard origin/main
/bin/cp -R site/. "$TARGET/"

# Depodan kaldırılan dosyaları sunucudan da sil (deploy/silinecekler.txt, her satır public_html'e göre yol)
if [ -f deploy/silinecekler.txt ]; then
  while IFS= read -r f; do
    f="${f%%#*}"; f="$(echo "$f" | xargs)"
    [ -z "$f" ] && continue
    case "$f" in *..*) continue;; esac
    rm -rf "$TARGET/$f"
  done < deploy/silinecekler.txt
fi

echo "$(date '+%F %T') dağıtıldı: $(git log -1 --format='%h %s')" >> "$LOG"
