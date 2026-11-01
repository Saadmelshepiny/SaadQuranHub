#!/bin/sh
# Saad Quran Hub - install / update on an Enigma2 receiver:
#   wget -q --no-check-certificate https://raw.githubusercontent.com/Saadmelshepiny/SaadQuranHub/main/install.sh -O - | /bin/sh
REPO="https://raw.githubusercontent.com/Saadmelshepiny/SaadQuranHub/main"
IPK=$(wget -q --no-check-certificate "$REPO/version.json" -O - | sed -n 's/.*"ipk": *"\([^"]*\)".*/\1/p')
[ -z "$IPK" ] && { echo "Cannot reach GitHub"; exit 1; }
wget -q --no-check-certificate "$IPK" -O /tmp/saadquranhub.ipk || { echo "Download failed"; exit 1; }
opkg install --force-reinstall /tmp/saadquranhub.ipk && rm -f /tmp/saadquranhub.ipk
# later updates also come from the receiver's own "software update" (opkg feed)
echo "src/gz saadquranhub $REPO/feed" > /etc/opkg/saadquranhub-feed.conf
echo "Saad Quran Hub installed - restarting the GUI ..."
killall -9 enigma2 >/dev/null 2>&1
