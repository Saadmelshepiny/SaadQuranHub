# -*- coding: utf-8 -*-
"""Saad Quran Hub - colouring of the best known tajweed rules (pure Python, unit-tested).

Worked out from the letters and harakat of the text itself, the way a teacher marks a mushaf:
ghunnah, ikhfa', iqlab, idgham, qalqalah, madd and letters that are written but not read
(lam shamsiyyah, noon before lam / ra).  It is a reading aid - the printed tajweed mushaf
remains the reference."""
from __future__ import print_function

RULES = [
    ("madd", u"مدّ", 0xE8584A),
    ("ghunnah", u"غُنّة", 0xF39C33),
    ("ikhfa", u"إخفاء", 0x45C47F),
    ("iqlab", u"إقلاب", 0x36B8C8),
    ("idgham", u"إدغام بغنّة", 0xA48CF0),
    ("qalqala", u"قلقلة", 0x5AA2EE),
    ("silent", u"لا يُنطق", 0x8C939C),
]
COLOR = dict((k, c) for k, _n, c in RULES)
# deeper shades of the same colours for a light (paper) page
ON_PAPER = {0xE8584A: 0xC0302A, 0xF39C33: 0xC86A00, 0x45C47F: 0x1E8A4C, 0x36B8C8: 0x0E7E8C,
            0xA48CF0: 0x6747C4, 0x5AA2EE: 0x1F5FB5, 0x8C939C: 0x8A7F6C}

FATHA, DAMMA, KASRA, SUKUN, SHADDA = 0x064E, 0x064F, 0x0650, 0x0652, 0x0651
TANWEEN = (0x064B, 0x064C, 0x064D)
VOWELS = (FATHA, DAMMA, KASRA) + TANWEEN
NOON, MEEM, BA, LAM, RA = 0x0646, 0x0645, 0x0628, 0x0644, 0x0631
ALEFS = (0x0627, 0x0671)
HAMZAS = (0x0621, 0x0623, 0x0625, 0x0624, 0x0626)
IKHFA = set(ord(c) for c in u"تثجدذزسشصضطظفقك")
YANMOU = set(ord(c) for c in u"ينمو")
QALQALA = set(ord(c) for c in u"قطبجد")
SUN = set(ord(c) for c in u"تثدذرزسشصضطظلن")


def _is_mark(cp):
    return 0x0610 <= cp <= 0x061A or 0x064B <= cp <= 0x065F or cp == 0x0670 or 0x06D6 <= cp <= 0x06ED


def _is_letter(cp):
    return 0x0621 <= cp <= 0x064A or cp == 0x0671


def analyse(text):
    """-> list of (char index, mark set, word number) for every letter, in text order."""
    out = []
    word = 0
    i, n = 0, len(text)
    while i < n:
        cp = ord(text[i])
        if text[i].isspace():
            word += 1
            i += 1
            continue
        if _is_letter(cp):
            j = i + 1
            marks = set()
            while j < n and _is_mark(ord(text[j])):
                marks.add(ord(text[j]))
                j += 1
            out.append((i, cp, marks, word))
            i = j
            continue
        if not _is_mark(cp):
            word += 1                    # punctuation / ayah number: a break
        i += 1
    return out


def colors(text):
    """-> {char index: 0xRRGGBB} for the letters a rule applies to."""
    L = analyse(text)
    res = {}

    def put(k, rule):
        if k not in res:
            res[k] = COLOR[rule]

    def nxt(k, skip_carrier=False):
        """index in L of the next letter (skipping the silent alef / alef maqsura after a fathatan)."""
        m = k + 1
        if skip_carrier and m < len(L) and L[m][1] in (0x0627, 0x0649) and not (L[m][2] & set(VOWELS)) \
                and L[m][3] == L[k][3]:
            m += 1
        return m if m < len(L) else None

    for k, (ci, cp, mk, w) in enumerate(L):
        vowel = bool(mk & set(VOWELS))
        # ghunnah: noon / meem with shadda
        if cp in (NOON, MEEM) and SHADDA in mk:
            put(ci, "ghunnah")
            continue
        tanween = bool(mk & set(TANWEEN))
        noon_sakin = cp == NOON and not vowel and SHADDA not in mk
        if noon_sakin or tanween:
            m = nxt(k, skip_carrier=tanween)
            if m is not None:
                ncp, nw = L[m][1], L[m][3]
                across = nw != w
                if ncp == BA:
                    put(ci, "iqlab")
                elif ncp in IKHFA:
                    put(ci, "ikhfa")
                elif across and ncp in YANMOU:
                    put(ci, "idgham")
                elif across and ncp in (LAM, RA):
                    put(ci, "silent")
            continue
        if cp == MEEM and not vowel and SHADDA not in mk:
            m = nxt(k)
            if m is not None and L[m][3] != w:
                if L[m][1] == BA:
                    put(ci, "ikhfa")
                elif L[m][1] == MEEM:
                    put(ci, "ghunnah")
            continue
        # qalqalah: a qalqalah letter with sukun
        if cp in QALQALA and SUKUN in mk:
            put(ci, "qalqala")
            continue
        # lam shamsiyyah: al- + sun letter with shadda -> the lam is not read
        if cp == LAM and not mk and k > 0 and L[k - 1][1] in ALEFS and L[k - 1][3] == w:
            m = nxt(k)
            if m is not None and L[m][3] == w and L[m][1] in SUN and SHADDA in L[m][2]:
                put(ci, "silent")
            continue
        # madd: alef with madda, or a long vowel letter followed by hamza / shadda / madda sign
        if cp == 0x0622 or 0x0653 in mk:
            put(ci, "madd")
            continue
        if not mk and k > 0 and L[k - 1][3] == w:
            pm = L[k - 1][2]
            long_ = (cp == 0x0627 and FATHA in pm) or (cp == 0x0648 and DAMMA in pm) or \
                (cp == 0x064A and KASRA in pm) or (cp == 0x0649 and FATHA in pm)
            if long_:
                m = nxt(k)
                if m is not None and (L[m][1] in HAMZAS or (L[m][3] == w and SHADDA in L[m][2])):
                    put(ci, "madd")
    return res


def legend_text():
    return u"  •  ".join(n for _k, n, _c in RULES)
