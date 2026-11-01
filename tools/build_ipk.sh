#!/bin/sh
# Build the ipk from src/ :  sh tools/build_ipk.sh
#   -> ipk/enigma2-plugin-extensions-saadquranhub_<version>_all.ipk
#   -> feed/ (Packages, Packages.gz and the ipk) for:  src/gz saadquranhub https://raw.githubusercontent.com/Saadmelshepiny/SaadQuranHub/main/feed
set -e
cd "$(dirname "$0")/.."
V=$(sed -n 's/^Version: //p' src/CONTROL/control)
T=$(mktemp -d)
mkdir -p "$T/root" "$T/ctl" ipk feed
cp -a src/usr "$T/root/"
find "$T/root" -name __pycache__ -prune -exec rm -rf {} +
rm -f "$T/root/usr/lib/enigma2/python/Plugins/Extensions/SaadQuranHub/bot.conf"   # never publish a bot token
cp src/CONTROL/control src/CONTROL/preinst src/CONTROL/postinst "$T/ctl/"
NAME="enigma2-plugin-extensions-saadquranhub_${V}_all.ipk"
OUT="$PWD/ipk/$NAME"
( cd "$T" && echo "2.0" > debian-binary \
  && (cd root && tar --owner=0 --group=0 -czf ../data.tar.gz ./usr) \
  && (cd ctl && tar --owner=0 --group=0 -czf ../control.tar.gz ./control ./preinst ./postinst) \
  && rm -f "$OUT" && ar r "$OUT" debian-binary control.tar.gz data.tar.gz 2>/dev/null )
rm -rf "$T"
# opkg feed: only the newest package
rm -f feed/*.ipk
cp "$OUT" "feed/$NAME"
{
  cat src/CONTROL/control | sed '/^$/d'
  echo "Filename: $NAME"
  echo "Size: $(wc -c < "$OUT" | tr -d ' ')"
  echo "MD5Sum: $(md5sum "$OUT" | cut -d' ' -f1)"
  echo "SHA256sum: $(sha256sum "$OUT" | cut -d' ' -f1)"
  echo ""
} > feed/Packages
gzip -9nc feed/Packages > feed/Packages.gz
echo "$OUT"
