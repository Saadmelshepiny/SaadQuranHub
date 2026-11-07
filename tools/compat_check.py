# -*- coding: utf-8 -*-
"""Checks Saad Quran Hub against the source of several enigma2 images before a release.

    python3 tools/compat_check.py <plugin dir> <enigma2 checkout> [<enigma2 checkout> ...]

For every image it reports:
  * remote-control contexts the plugin binds that the image's keymap.xml does not have,
  * actions (key names) the plugin waits for that no listed context sends on that image,
  * modules / names the plugin imports from Screens, Components, Tools that the image lacks.
The MENU key is bound through both InfobarMenuActions and MenuActions (see ActionMap() in plugin.py),
so it counts as present when either exists."""
import os
import re
import sys

ANY_OF = {"InfobarMenuActions": ("InfobarMenuActions", "MenuActions")}
if os.environ.get("SQH_OLD_MENU"):          # check a build from before 2.0.2 (no MenuActions fallback)
    ANY_OF = {}
NUMBERS = set("0123456789")


def keymap(e2):
    """-> {context: set(action names)} from data/keymap*.xml (+ data/keymaps/*.xml)."""
    files = [os.path.join(e2, "data", f) for f in os.listdir(os.path.join(e2, "data")) if f.startswith("keymap") and f.endswith(".xml")]
    kd = os.path.join(e2, "data", "keymaps")
    if os.path.isdir(kd):
        files += [os.path.join(kd, f) for f in os.listdir(kd) if f.endswith(".xml")]
    out = {}
    for f in files:
        ctx = None
        for line in open(f, encoding="utf-8", errors="ignore"):
            m = re.search(r'<map context="([^"]+)"', line)
            if m:
                ctx = m.group(1)
                out.setdefault(ctx, set())
            m = re.search(r'mapto="([^"]+)"', line)
            if m and ctx:
                out[ctx].add(m.group(1))
            if "</map>" in line:
                ctx = None
    return out


def action_maps(src):
    """-> [(line, [contexts], set(keys))] for every ActionMap(...) call in a source file."""
    lines = src.split("\n")
    out = []
    for i, line in enumerate(lines):
        if "ActionMap(" not in line or line.strip().startswith(("def ", "class ", "#", "return _ActionMap")):
            continue
        chunk = "\n".join(lines[i:i + 8])
        m = re.search(r"ActionMap\(\s*\[([^\]]*)\]\s*,\s*(\{|\w+)", chunk)
        if not m:
            continue
        ctxs = re.findall(r'"([A-Za-z]+)"', m.group(1))
        if m.group(2) == "{":
            body = chunk[m.end() - 1:]
            depth, end = 0, len(body)
            for j, ch in enumerate(body):
                depth += ch == "{"
                depth -= ch == "}"
                if depth == 0:
                    end = j
                    break
            body = body[:end]
        else:                                  # a dict variable built a few lines earlier
            name = m.group(2)
            start = max(0, i - 40)
            body = ""
            for k in range(i, start, -1):
                if re.match(r"\s*%s\s*=\s*\{" % name, lines[k]):
                    body = "\n".join(lines[k:i])
                    break
            body += "\n".join(l for l in lines[max(0, i - 40):i] if re.search(r"\b%s\[" % name, l))
        keys = set(re.findall(r'"([A-Za-z0-9_:]+)"\s*:', body)) | set(re.findall(r'%s\["([A-Za-z0-9_:]+)"\]' % (m.group(2),), body))
        out.append((i + 1, ctxs, keys))
    return out


def imports(src):
    """-> [(module, name)] for 'from Screens/Components/Tools.X import Y'."""
    out = []
    for m in re.finditer(r"^\s*from ((?:Screens|Components|Tools)\.[\w.]+) import ([\w, ]+)", src, re.M):
        for n in m.group(2).split(","):
            n = n.strip().split(" as ")[0]
            if n:
                out.append((m.group(1), n))
    return out


def has_name(e2, module, name):
    path = os.path.join(e2, "lib", "python", *module.split(".")) + ".py"
    if not os.path.exists(path):
        return None
    src = open(path, encoding="utf-8", errors="ignore").read()
    return bool(re.search(r"^(class|def)\s+%s\b|^%s\s*=" % (name, name), src, re.M))


def check(plugin, e2):
    km = keymap(e2)
    problems = []
    seen_imp = set()
    for f in sorted(os.listdir(plugin)):
        if not f.endswith(".py"):
            continue
        src = open(os.path.join(plugin, f), encoding="utf-8").read()
        for line, ctxs, keys in action_maps(src):
            sent = set()
            for c in ctxs:
                alts = ANY_OF.get(c, (c,))
                if not any(a in km for a in alts):
                    problems.append("%s:%d context %s is missing" % (f, line, c))
                for a in alts:
                    sent |= km.get(a, set())
            if "NumberActions" in ctxs:
                sent |= NUMBERS
            if "InfobarMenuActions" in ctxs and ANY_OF:
                sent |= {"mainMenu", "menu"}
            for k in sorted(keys - sent):
                if k.isdigit():
                    continue
                problems.append("%s:%d no key sends '%s' (contexts %s)" % (f, line, k, ",".join(ctxs)))
        for mod, name in imports(src):
            if (mod, name) in seen_imp:
                continue
            seen_imp.add((mod, name))
            ok = has_name(e2, mod, name)
            if ok is None:
                problems.append("%s: module %s is missing" % (f, mod))
            elif not ok:
                problems.append("%s: %s has no %s" % (f, mod, name))
    return problems


def main():
    plugin, images = sys.argv[1], sys.argv[2:]
    bad = 0
    for e2 in images:
        probs = check(plugin, e2)
        print("== %s: %s" % (os.path.basename(e2.rstrip("/")), "OK" if not probs else "%d problem(s)" % len(probs)))
        for p_ in probs:
            print("   " + p_)
        bad += len(probs)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
