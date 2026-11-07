#!/bin/sh
# Saad Quran Hub - install / update on an Enigma2 receiver:
#   wget -q --no-check-certificate https://raw.githubusercontent.com/Saadmelshepiny/SaadQuranHub/main/install.sh -O - | /bin/sh
# Receivers with little free flash get the "lite" package: the big letter pictures and the tafsirs are
# then fetched onto the HDD/USB by the plugin itself.
REPO="https://raw.githubusercontent.com/Saadmelshepiny/SaadQuranHub/main"
INFO=$(wget -q --no-check-certificate "$REPO/version.json" -O -)
[ -z "$INFO" ] && { echo "Cannot reach GitHub"; exit 1; }
IPK=$(echo "$INFO" | sed -n 's/.*"ipk": *"\([^"]*\)".*/\1/p')
LITE=$(echo "$INFO" | sed -n 's/.*"ipk_lite": *"\([^"]*\)".*/\1/p')
FREE=$(df -k /usr 2>/dev/null | awk 'NR==2 {print $4}')
if [ -n "$LITE" ] && [ -n "$FREE" ] && [ "$FREE" -lt 20000 ]; then
  echo "Little free flash (${FREE} KB): installing the lite package"
  IPK="$LITE"
fi
wget -q --no-check-certificate "$IPK" -O /tmp/saadquranhub.ipk || { echo "Download failed"; exit 1; }
opkg install --force-reinstall /tmp/saadquranhub.ipk && rm -f /tmp/saadquranhub.ipk
# later updates also come from the receiver's own "software update" (opkg feed)
echo "src/gz saadquranhub $REPO/feed" > /etc/opkg/saadquranhub-feed.conf
echo "Saad Quran Hub installed - restarting the GUI ..."
killall -9 enigma2 >/dev/null 2>&1
