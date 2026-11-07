# -*- coding: utf-8 -*-
"""Ready lists shared with every user (lists/index.json + one file per list).
Whole surahs come from mp3quran.net folders (the same addresses the plugin already uses)."""
import json
import os

MINSH = "https://server10.mp3quran.net/minsh/"
MINSH_TEACH = "https://server10.mp3quran.net/minsh/Almusshaf-Al-Mo-lim/"
HUSARY = "https://server13.mp3quran.net/husr/"
BASIT = "https://server7.mp3quran.net/basit/"
AFASY = "https://server8.mp3quran.net/afs/"
LISTS = [
    ("kids", u"سور الأطفال (المصحف المعلّم)", u"المنشاوي مع الأطفال - من النبأ إلى الناس",
     [(MINSH_TEACH, n) for n in [1] + list(range(114, 77, -1))]),
    ("friday", u"سنن يوم الجمعة والليل", u"الكهف • يس • الملك • السجدة • الواقعة • الدخان - الحصري",
     [(HUSARY, n) for n in (18, 36, 67, 32, 56, 44)]),
    ("short", u"قصار السور مرتلة", u"عبد الباسط عبد الصمد - من الضحى إلى الناس",
     [(BASIT, n) for n in range(93, 115)]),
    ("khatma_minsh", u"ختمة كاملة - المنشاوي مرتل", u"114 سورة بالترتيب", [(MINSH, n) for n in range(1, 115)]),
    ("ruqya", u"آيات الرقية والحفظ", u"الفاتحة • البقرة • المعوذات - العفاسي", [(AFASY, n) for n in (1, 2, 112, 113, 114)]),
]
NAMES = json.load(open(os.path.join(os.path.dirname(__file__), "surah_names.json"), encoding="utf-8"))


def main(out="lists"):
    os.makedirs(out, exist_ok=True)
    index = []
    for lid, name, desc, items in LISTS:
        body = {"name": name, "items": [{"title": u"سورة %s" % NAMES[n - 1], "server": srv, "n": n} for srv, n in items]}
        json.dump(body, open(os.path.join(out, lid + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        index.append({"id": lid, "name": name, "desc": desc, "file": lid + ".json", "count": len(items)})
    json.dump({"lists": index}, open(os.path.join(out, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("%d lists" % len(index))


if __name__ == "__main__":
    main()
