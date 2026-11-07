#!/bin/sh
# Build everything published from src/ :  sh tools/build_ipk.sh
#   ipk/enigma2-plugin-extensions-saadquranhub_<v>_all.ipk       full package (also in feed/)
#   ipk/enigma2-plugin-extensions-saadquranhub-lite_<v>_all.ipk  small-flash package: big letter pictures and
#                                                                the tafsirs come later as packs on the HDD/USB
#   pack/  fonts-big, tafsir, fonts-4k (.tar.gz + index.json with SHA-256)
#   feed/  Packages, Packages.gz and the full ipk:
#          src/gz saadquranhub https://raw.githubusercontent.com/Saadmelshepiny/SaadQuranHub/main/feed
set -e
cd "$(dirname "$0")/.."
V=$(sed -n 's/^Version: //p' src/CONTROL/control)
PD=usr/lib/enigma2/python/Plugins/Extensions/SaadQuranHub
mkdir -p ipk feed pack

build() {   # $1 = output file, $2 = lite (1/0)
  T=$(mktemp -d)
  mkdir -p "$T/root" "$T/ctl"
  cp -a src/usr "$T/root/"
  find "$T/root" -name __pycache__ -prune -exec rm -rf {} +
  rm -f "$T/root/$PD/bot.conf"                                  # never publish a bot token
  if [ "$2" = "1" ]; then
    rm -f "$T/root/$PD/qtext/atlas62.bin" "$T/root/$PD/qtext/atlas74.bin" "$T/root/$PD/qtext/atlas88.bin"
    rm -rf "$T/root/$PD"/qdata/taf_*
    touch "$T/root/$PD/LITE"
  fi
  cp src/CONTROL/control src/CONTROL/preinst src/CONTROL/postinst "$T/ctl/"
  ( cd "$T" && echo "2.0" > debian-binary \
    && (cd root && tar --owner=0 --group=0 -czf ../data.tar.gz ./usr) \
    && (cd ctl && tar --owner=0 --group=0 -czf ../control.tar.gz ./control ./preinst ./postinst) \
    && rm -f "$1" && ar r "$1" debian-binary control.tar.gz data.tar.gz 2>/dev/null )
  rm -rf "$T"
}
NAME="enigma2-plugin-extensions-saadquranhub_${V}_all.ipk"
LITE="enigma2-plugin-extensions-saadquranhub-lite_${V}_all.ipk"
build "$PWD/ipk/$NAME" 0
build "$PWD/ipk/$LITE" 1

# packs (fixed dates so an unchanged pack keeps its checksum)
T=$(mktemp -d)
mkdir -p "$T/big/qtext" "$T/taf/data" "$T/k4/qtext"
cp src/$PD/qtext/atlas62.bin src/$PD/qtext/atlas74.bin src/$PD/qtext/atlas88.bin "$T/big/qtext/"
cp -r src/$PD/qdata/taf_* "$T/taf/data/"
cp pack-src/qtext/*.bin "$T/k4/qtext/"
for p in big:fonts-big taf:tafsir k4:fonts-4k; do
  d=${p%%:*}; n=${p#*:}
  (cd "$T/$d" && tar --owner=0 --group=0 --mtime='2026-01-01' --sort=name -cf - . | gzip -9n > "$OLDPWD/pack/$n.tar.gz")
done
rm -rf "$T"
python3 - <<'PY'
import hashlib, json, os
idx = {}
for n in ("fonts-big", "tafsir", "fonts-4k"):
    f = "pack/%s.tar.gz" % n
    idx[n] = {"file": os.path.basename(f), "size": os.path.getsize(f),
              "sha256": hashlib.sha256(open(f, "rb").read()).hexdigest()}
json.dump(idx, open("pack/index.json", "w"), indent=1)
PY

# opkg feed: only the newest full package
rm -f feed/*.ipk
cp "ipk/$NAME" "feed/$NAME"
OUT="$PWD/ipk/$NAME"
{
  sed '/^$/d' src/CONTROL/control
  echo "Filename: $NAME"
  echo "Size: $(wc -c < "$OUT" | tr -d ' ')"
  echo "MD5Sum: $(md5sum "$OUT" | cut -d' ' -f1)"
  echo "SHA256sum: $(sha256sum "$OUT" | cut -d' ' -f1)"
  echo ""
} > feed/Packages
gzip -9nc feed/Packages > feed/Packages.gz
ls -la ipk pack
