#!/bin/bash
# Vanterm otomatik dağıtım.
#  - cron ile her 5 dakikada bir çalışır: GitHub'da yeni commit varsa çeker ve yayınlar.
#  - cPanel "Deploy HEAD Commit" düğmesi (.cpanel.yml) --force ile çalıştırır: değişiklik olmasa da yayınlar.
# Hedef klasör ve mod deploy/hedef.conf dosyasından okunur.
#
# Cron komutu:  /bin/bash $HOME/repositories/vanterm/deploy/auto-deploy.sh >/dev/null 2>&1

REPO="$HOME/repositories/vanterm"
LOG="$HOME/vanterm-deploy.log"
FORCE=0; [ "$1" = "--force" ] && FORCE=1

cd "$REPO" || exit 1
git fetch -q origin main || { echo "$(date '+%F %T') fetch hatası" >> "$LOG"; exit 1; }

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)
[ "$LOCAL" = "$REMOTE" ] && [ $FORCE -eq 0 ] && exit 0

git reset -q --hard origin/main

# Ayarlar (güncel commit'ten)
HEDEF="demo.vanterm.com"; MOD="demo"
[ -f deploy/hedef.conf ] && . deploy/hedef.conf
case "$HEDEF" in ""|/*|*..*) echo "$(date '+%F %T') geçersiz HEDEF: $HEDEF" >> "$LOG"; exit 1;; esac
TARGET="$HOME/$HEDEF"
[ -d "$TARGET" ] || { echo "$(date '+%F %T') hedef klasör yok: $TARGET" >> "$LOG"; exit 1; }

/bin/cp -R site/. "$TARGET/"

# Depodan kaldırılan dosyaları sunucudan da sil (deploy/silinecekler.txt, hedef klasöre göre yol)
if [ -f deploy/silinecekler.txt ]; then
  while IFS= read -r f; do
    f="${f%%#*}"; f="$(echo "$f" | xargs)"
    [ -z "$f" ] && continue
    case "$f" in *..*|/*) continue;; esac
    rm -rf "$TARGET/$f"
  done < deploy/silinecekler.txt
fi

if [ "$MOD" = "demo" ]; then
  # Arama motorlarına kapat
  printf 'User-agent: *\nDisallow: /\n' > "$TARGET/robots.txt"
  {
    echo ''
    echo '# --- DEMO MODU (auto-deploy.sh ekler) ---'
    echo '<IfModule mod_headers.c>'
    echo '  Header always set X-Robots-Tag "noindex, nofollow"'
    echo '</IfModule>'
    # cPanel "Directory Privacy" ile şifre konduysa koru (her dağıtımda .htaccess yenilendiği için)
    PW="$HOME/.htpasswds/$HEDEF/passwd"
    if [ -f "$PW" ]; then
      echo 'AuthType Basic'
      echo 'AuthName "Vanterm Demo"'
      echo "AuthUserFile \"$PW\""
      echo 'Require valid-user'
    fi
  } >> "$TARGET/.htaccess"
fi

echo "$(date '+%F %T') dağıtıldı -> $HEDEF ($MOD): $(git log -1 --format='%h %s')" >> "$LOG"
