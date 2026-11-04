# -*- coding: utf-8 -*-
"""Saad Quran Hub - English interface (MENU > display > language).  The Quran, tafsir, reciter
and surah names stay in Arabic; screens, menus, buttons and hints are translated.
T(text) translates whole labels, 'Label: value' pairs, a leading emoji and a trailing '...'."""
from __future__ import print_function

import re

LANG = ["ar"]

EN = {
    u"القرص والسرعة والثبات": u"Disk, speed & stability",
    u"الملف الشخصي": u"Profile",
    u"حصاد الشهر": u"Monthly harvest",
    u"حصاد السنة": u"Yearly harvest",
    u"النجوم": u"Stars",
    u"مكتبتي لأجهزة البيت (DLNA)": u"My library for home devices (DLNA)",
    u"مكتبتي لأجهزة البيت": u"My library for home devices",
    u"الرجوع لإصدار سابق": u"Roll back to a previous version",
    u"متاح بدون إنترنت (ما سمعته)": u"Available offline (played before)",
    u"حفظ ما أسمعه على القرص (يعمل بدون إنترنت)": u"Keep what I play on the disk (works offline)",
    u"مسح ما سمعته سابقاً من القرص": u"Clear kept audio from the disk",
    u"إيقاظ القرص قبل الأذان والمواعيد": u"Wake the disk before adhan and schedules",
    u"متابعة التلاوة تلقائياً بعد انقطاع الكهرباء": u"Resume after a power cut",
    u"تنظيف الملفات المؤقتة القديمة الآن": u"Clean old temporary files now",
    u"النسخ اليومية للإعدادات (آخر 7 أيام + 4 أسابيع)": u"Daily settings copies (7 days + 4 weeks)",
    u"النسخ اليومية للإعدادات": u"Daily settings copies",
    u"حفظ نسخة الآن": u"Save a copy now",
    u"إضافة «إذاعتي الخاصة» كقناة في قائمة الراديو": u"Add 'My station' as a radio channel",
    u"إزالة «إذاعتي الخاصة» من قائمة الراديو": u"Remove 'My station' from the radio list",
    u"رسم المصحف كاملاً مسبقاً (أثناء وضع الانتظار)": u"Pre-draw the whole mushaf (in standby)",
    u"قارئ اليوم": u"Reciter of the day",
    # sources / groups / headers
    u"المفضلة": u"Favourites", u"القراء والمصاحف": u"Reciters", u"الإذاعات المباشرة": u"Live radios",
    u"تلاوات نادرة وتليجرام": u"Rare recitations & Telegram", u"مكتبات القرص": u"Disk libraries",
    u"مكتبة القراء الشاملة": u"All reciters (mp3quran)", u"تلاوات بتزامن الآيات": u"Ayah-synced recitations",
    u"موسوعة المصاحف": u"Mushaf encyclopedia", u"موسوعة المصاحف المرتلة": u"Mushaf encyclopedia",
    u"مصاحف تلفزيون القرآن": u"Quran TV mushafs", u"تلاوات عالية الجودة": u"High quality (quran.com)",
    u"قراء المصحف المرتّل": u"Murattal reciters", u"القراء بالروايات": u"Reciters by riwayah",
    u"قراء موقع السبيل": u"Assabile reciters", u"صوتيات إسلام ويب": u"Islamweb audio",
    u"شيوخ موقع قرآننا": u"Ourquraan sheikhs", u"إذاعات القرآن المباشرة": u"Quran live radios",
    u"إذاعات القرآن العربية": u"Arabic Quran radios", u"تلاوات نادرة وأيقونية": u"Rare & iconic recitations",
    u"سجل الاستماع": u"Listening history", u"الأكثر استماعاً": u"Most played", u"قوائمي": u"My playlists",
    u"المحفوظات (HDD)": u"Saved files (HDD)", u"نتائج البحث": u"Search results", u"مكتبتي": u"My library",
    u"القراء": u"Reciters", u"السور": u"Surahs", u"الإذاعات": u"Radios", u"المصاحف": u"Mushafs",
    u"الشيوخ": u"Sheikhs", u"المقاطع": u"Clips", u"الملفات": u"Files", u"النتائج": u"Results",
    u"القوائم": u"Lists", u"السجل": u"History", u"الأكثر": u"Most played", u"المصادر": u"Sources",
    u"المقاطع - تليجرام": u"Clips - Telegram",
    # colour buttons / actions
    u"تصغير": u"Minimise", u"تشغيل / فتح": u"Play / open", u"بحث": u"Search", u"إيقاف": u"Stop",
    u"تسجيل": u"Record", u"مفضلة": u"Favourite", u"السابق": u"Previous", u"التالي": u"Next",
    u"إيقاف مؤقت": u"Pause", u"القائمة": u"Menu", u"مؤقت النوم": u"Sleep timer", u"نوم": u"Sleep",
    u"الصيغة": u"Format", u"القنوات": u"Channels", u"المظهر": u"Theme", u"المظهر التالي": u"Next theme",
    u"حذف المحدد من القائمة": u"Remove selected", u"بحث شامل": u"Global search",
    u"البحث عن قارئ": u"Find a reciter", u"المشغّل الكبير": u"Big player", u"سرعة التلاوة": u"Recitation speed",
    u"حفظ علامة": u"Save bookmark", u"تكرار مقطع A-B": u"A-B repeat", u"شاشة التشغيل الآن": u"Now playing",
    u"الشاشة الرئيسية": u"Home screen", u"قراءة السورة": u"Read the surah", u"تحديث القوائم": u"Refresh lists",
    u"مواقيت الصلاة": u"Prayer times", u"تنزيل الحالي": u"Download current", u"إضافة لقائمة": u"Add to playlist",
    u"رفع الصوت": u"Volume up", u"خفض الصوت": u"Volume down", u"كتم": u"Mute", u"العودة للمباشر": u"Back to live",
    u"تابع الاستماع": u"Resume", u"رجوع 30 ث": u"Back 30 s", u"تقديم 30 ث": u"Forward 30 s",
    u"صيغة التسجيل": u"Recording format", u"المشغّل": u"Player engine", u"القنوات والصورة": u"Channels & picture",
    u"وضع القناة + القرآن": u"Channel + Quran mode", u"اختيار المظهر": u"Choose theme",
    # main menu
    u"القائمة الرئيسية": u"Main menu", u"إغلاق البلاجين وإيقاف القرآن (يعود صوت القناة)": u"Close plugin and stop the Quran (channel sound returns)",
    u"المشغّل الكبير (سرعة • تكرار • علامات)": u"Big player (speed • repeat • bookmarks)",
    u"شاشة التشغيل الآن (صورة القارئ والتقدم)": u"Now playing (reciter picture & progress)",
    u"وضع التلاوة السينمائي (الآية بخط كبير مع الصوت)": u"Cinema mode (the ayah in big letters)",
    u"وضع التلاوة السينمائي": u"Cinema mode", u"تابع الاستماع": u"Resume",
    u"حذف المحدد من القائمة (مصدر لا يعمل أو قارئ) - زر 5": u"Remove selected (dead source or reciter) - key 5",
    u"تحريك المصدر المحدد لأعلى": u"Move selected source up", u"تحريك المصدر المحدد لأسفل": u"Move selected source down",
    u"المحذوفات (استعادة)": u"Removed items (restore)", u"المحذوفات": u"Removed items",
    u"إضافة المحدد إلى «التالي» (يعمل بعد الحالي)": u"Add selected to \"Up next\"",
    u"علاماتي": u"My bookmarks", u"البحث عن قارئ (كل المواقع) - تشغيل وتنزيل": u"Find a reciter (all sites) - play & download",
    u"مصادر من القرص (مجلدات القراء MP3 / FLAC)": u"Disk sources (reciter folders MP3 / FLAC)",
    u"باقة المفضلة في قائمة القنوات": u"Favourites bouquet in the channel list",
    u"مكتبتي (الملفات المنزّلة • تحويل الصيغة)": u"My library (downloads • format conversion)",
    u"بوت تليجرام": u"Telegram bot", u"القرآن مع صورة القناة": u"Quran with the TV picture",
    u"القراءة والتفسير والأذكار": u"Reading, tafsir & adhkar",
    u"الاستوديو: الحفظ • الاختبار • الأطفال • الختمة": u"Studio: memorise • test • kids • khatma",
    u"السجل • الأكثر استماعاً • قوائمي • المحفوظات": u"History • most played • playlists • saved files",
    u"بحث شامل في كل المواقع": u"Search all sites", u"الصلاة والجدولة والتذكيرات": u"Prayer, schedules & reminders",
    u"المظهر والعرض والاختصارات": u"Display, theme & shortcuts", u"التحكم من الجوال": u"Phone control",
    u"قنوات تليجرام (إضافة / حذف)": u"Telegram channels (add / remove)",
    u"باقة الإذاعات في قائمة القنوات": u"Radio bouquet in the channel list", u"نسخ احتياطي واستعادة": u"Backup & restore",
    u"أدوات وتشخيص": u"Tools & diagnostics", u"شاشة البطاقات": u"Cards screen", u"رمضان والمناسبات": u"Ramadan & occasions",
    u"إذاعتي الخاصة": u"My own radio station", u"الوضع المبسّط (لكبار السن)": u"Simple mode (for elderly)",
    u"اللغة / Language": u"Language / اللغة", u"ما الجديد في هذا الإصدار": u"What's new",
    # sub menus
    u"تشغيل سورة": u"Play a surah", u"تشغيل الكل بالترتيب": u"Play all in order", u"تنزيل سور مختارة": u"Download selected surahs",
    u"صيغة التنزيل": u"Download format", u"تنزيل المصحف كاملاً": u"Download the whole mushaf",
    u"صيغة التنزيل (الأصلي = أفضل جودة بلا تحويل)": u"Download format (original = best quality)",
    u"تثبيت ffmpeg لتفعيل كل الصيغ": u"Install ffmpeg for all formats", u"تثبيت ffmpeg الآن": u"Install ffmpeg now",
    u"مكتبتي (الملفات المنزّلة على القرص)": u"My library (files on the disk)",
    u"ترتيب الملفات القديمة في مجلد لكل قارئ": u"Tidy old files into a folder per reciter",
    u"التنزيلات والأعمال الجارية": u"Downloads and running jobs", u"تشغيل الكل": u"Play all",
    u"تحويل الصيغة (مثلاً MP3 ← FLAC)": u"Convert format (e.g. MP3 → FLAC)",
    u"تنقية الصوت لكل الملفات (إزالة التشويش وتوحيد العلو)": u"Clean the sound of all files",
    u"نسخ إلى فلاشة (للسيارة)": u"Copy to a USB stick (for the car)", u"إرسال سورة إلى تليجرام": u"Send a surah to Telegram",
    u"تحويل وحذف الملف القديم": u"Convert and delete the old file", u"تحويل مع الإبقاء على القديم": u"Convert and keep the old file",
    u"إضافة مجلد من HDD / الفلاشة": u"Add a folder from HDD / USB", u"رجوع": u"Back",
    u"مصادر من القرص (ملفات القراء MP3 / FLAC)": u"Disk sources (reciter files MP3 / FLAC)",
    u"اختر المجلد الذي فيه ملفات القراء": u"Choose the folder with the reciters' files",
    u"إنشاء / تحديث باقة «القرآن الكريم - المفضلة» في قائمة القنوات": u"Create / update the favourites bouquet",
    u"إزالة الباقة من قائمة القنوات": u"Remove the bouquet", u"باقة المفضلة": u"Favourites bouquet",
    u"السرعة": u"Speed", u"تكرار الآية الحالية 3 مرات": u"Repeat this ayah 3 times",
    u"تكرار الآية الحالية 5 مرات": u"Repeat this ayah 5 times", u"تكرار الآية الحالية 10 مرات": u"Repeat this ayah 10 times",
    u"تكرار مقطع A-B (زر 0)": u"A-B repeat (key 0)", u"إيقاف التكرار": u"Stop repeating",
    u"حفظ علامة هنا (أزرق)": u"Save a bookmark here (blue)", u"مشاركة الآية (QR)": u"Share the ayah (QR)",
    u"إيقاف التشغيل": u"Stop playback", u"المشغّل": u"Player", u"حذف كل العلامات": u"Delete all bookmarks",
    u"سرعة التلاوة (بنفس صوت الشيخ)": u"Recitation speed (same voice)",
    u"البوت": u"Bot", u"الحالة": u"Status", u"ربط جوال جديد (يظهر رمز على الشاشة)": u"Link a new phone (a code appears on screen)",
    u"الحسابات المربوطة": u"Linked accounts", u"التنبيهات على تليجرام": u"Telegram notifications",
    u"آية الصباح على تليجرام": u"Morning ayah on Telegram", u"إرسال رسالة تجربة": u"Send a test message",
    u"التوكن": u"Token", u"ورد الحفظ على الجوال": u"Daily memorisation on the phone",
    u"نسخة احتياطية أسبوعية على تليجرام": u"Weekly backup to Telegram", u"تقارير الأعطال إليك": u"Error reports to you",
    u"المصحف بالصفحات (604 صفحة مثل المطبوع)": u"Mushaf pages (604, like the printed copy)",
    u"بحث في نص القرآن": u"Search the Quran text", u"اختيار سورة أخرى": u"Choose another surah",
    u"الأذكار والأدعية (حصن المسلم)": u"Adhkar & duas (Hisn al-Muslim)", u"أسماء الله الحسنى": u"The 99 names of Allah",
    u"المصادر والحقوق": u"Sources & licences", u"التشخيص الذاتي (الإنترنت • المواقع • القرص • المشغّلات)": u"Self diagnostics",
    u"إحصائيات الاستماع": u"Listening statistics", u"فحص كل المصادر الآن": u"Check all sources now",
    u"سجل الأخطاء التقني": u"Technical error log", u"تحديث البلاجين (من ملف ipk أو رابط)": u"Update the plugin",
    u"تحديث البلاجين": u"Update the plugin", u"فحص GitHub الآن عن تحديث": u"Check GitHub for an update now",
    u"فحص التحديثات تلقائياً كل يوم": u"Check for updates every day", u"آية عند تشغيل الجهاز": u"Ayah when the receiver starts",
    u"إضافة مصدر التحديث الرسمي (feed) إلى الجهاز": u"Add the official update feed to the receiver",
    u"الإصدار الحالي": u"Current version", u"رابط التحديث": u"Update link",
    u"حفظ الإعدادات والقوائم والمفضلة على HDD/USB": u"Save settings, lists & favourites to HDD/USB",
    u"استعادة آخر نسخة": u"Restore the last backup", u"نسخة تلقائية كل أسبوع": u"Automatic weekly backup",
    u"القناة والعرض والتحكم": u"Display & control", u"العودة إلى البث المباشر": u"Back to live",
    u"الشريط المصغّر": u"Mini bar", u"تخصيص الاختصارات (الألوان والأرقام)": u"Customise shortcuts (colours & numbers)",
    u"المظهر التلقائي": u"Automatic theme", u"المصدر البديل التلقائي": u"Automatic alternative source",
    u"تحديث القوائم (مسح الذاكرة المؤقتة)": u"Refresh lists (clear cache)", u"التنزيل والمحفوظات": u"Downloads & saved files",
    u"البحث عن قارئ وتنزيله بأي صيغة": u"Find a reciter and download in any format",
    u"مكتبتي (تشغيل • تحويل الصيغة • نسخ للفلاشة)": u"My library (play • convert • copy to USB)",
    u"إيقاف التنزيلات": u"Stop downloads", u"فتح المحفوظات": u"Open saved files",
    u"تنزيل المقطع الحالي إلى HDD": u"Download the current item to HDD", u"تنزيل المحدّد": u"Download selected",
    u"تنزيل المصحف كاملاً لهذا القارئ (يكمل من حيث توقف)": u"Download this reciter's whole mushaf (resumes)",
    u"الجدولة ومواقيت الصلاة": u"Schedules & prayer times", u"مدينة الصلاة": u"Prayer city",
    u"نمط تنبيه الأذان": u"Adhan alert mode", u"صوت الأذان": u"Adhan voice", u"تجربة الأذان الآن": u"Test the adhan now",
    u"عرض مواقيت اليوم": u"Today's prayer times", u"جدولة تشغيل جديدة": u"New scheduled playback",
    u"إذاعتي الخاصة: كل المكتبة عشوائياً": u"My station: the whole library, shuffled",
    u"إذاعتي الخاصة: كل المكتبة بالترتيب": u"My station: the whole library, in order",
    u"إذاعتي الخاصة: قارئ واحد": u"My station: one reciter", u"رابط الإذاعة لأجهزة البيت": u"Station link for home devices",
    u"وضع رمضان": u"Ramadan mode", u"تصحيح التاريخ الهجري": u"Hijri date correction",
    u"تذكير المناسبات الهجرية": u"Hijri occasion reminders", u"قارئ ختمة رمضان": u"Ramadan khatma reciter",
    u"تشغيل جزء الليلة الآن": u"Play tonight's juz now", u"خفض الصوت تدريجياً ثم الانتظار": u"Fade out, then standby",
    # values
    u"يعمل": u"On", u"متوقف": u"Off", u"مفعّل": u"On", u"معطّل": u"Off", u"إيقاف (مظهر ثابت)": u"Off (fixed theme)",
    u"تلقائي": u"Automatic", u"غير محددة": u"Not set", u"غير محدد": u"Not set", u"عادية": u"Normal",
    u"نعم، ابدأ": u"Yes, start", u"إلغاء": u"Cancel", u"نعم، احذف": u"Yes, delete",
    u"نعم، ابدأ (يكمل في الخلفية ولو أُغلق البلاجين)": u"Yes, start (continues in the background)",
    # hints
    u"OK إيقاف/تشغيل • ◀▶ 10 ث • ▲▼ دقيقة • 1-9 قفز % • 0 تكرار A-B • أحمر/أخضر السابق/التالي • أصفر السرعة • أزرق علامة • MENU المزيد":
        u"OK pause • ◀▶ 10 s • ▲▼ 1 min • 1-9 jump % • 0 A-B repeat • red/green prev/next • yellow speed • blue bookmark • MENU more",
    u"◀ ▶ صفحة  •  7/9 حجم الخط  •  EXIT رجوع": u"◀ ▶ page  •  7/9 font size  •  EXIT back",
}

VALUES = {u"يعمل": u"On", u"متوقف": u"Off", u"مفعّل": u"On", u"معطّل": u"Off", u"إيقاف": u"Off",
          u"غير محددة": u"Not set", u"غير محدد": u"Not set", u"الأصلي": u"Original"}

_LEAD = re.compile(u"^([^؀-ۿA-Za-z0-9«(]+)")


def on():
    return LANG[0] == "en"


def T(text):
    """Arabic UI label -> English (when the English interface is chosen)."""
    if not on() or not text:
        return text
    try:
        return _t(text)
    except Exception:
        return text


def _t(text):
    if text in EN:
        return EN[text]
    s = text
    lead = u""
    m = _LEAD.match(s)
    if m:
        lead, s = m.group(1), s[m.end():]
    tail = u""
    for end in (u" ...", u"...", u"  ▶"):
        if s.endswith(end):
            s, tail = s[:-len(end)], end
            break
    if s in EN:
        return lead + EN[s] + tail
    if u":" in s:
        head, val = s.split(u":", 1)
        h = EN.get(head.strip())
        if h:
            v = val.strip()
            v2 = VALUES.get(v, EN.get(v, v))
            return u"%s%s: %s%s" % (lead, h, v2, tail)
    m = re.match(u"^(.*?)\\s*(\\([^()]*\\))$", s)
    if m and m.group(1) in EN:
        return lead + EN[m.group(1)] + u" " + m.group(2) + tail
    return text
