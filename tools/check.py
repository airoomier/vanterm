#!/usr/bin/env python3
"""
Kontroller:
  1) Metin: her sayfanın görünür metni orijinalle aynı mı (alan adı farkı hariç)
  2) Linkler: site içi href/src adresleri site/ içinde var mı (veya .htaccess yönlendirmesi)
Kullanım: python3 tools/check.py [<raw_kok>]
"""
import json
import re
import sys
import urllib.parse
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site"
redirects = json.loads((ROOT / "tools" / "redirects.json").read_text()) if (ROOT / "tools" / "redirects.json").exists() else {}


def visible_text(h: str) -> str:
    h = re.sub(r"<(script|style|noscript|head)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    t = unescape(h)
    t = re.sub(r"@(www\.)?demo\.seowpclub\.com", "@vanterm.com", t)
    t = re.sub(r"(https?:)?//(www\.)?demo\.seowpclub\.com", "", t)
    t = t.replace("https://vanterm.com", "")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s?0 Comment\b", "", t)  # yazı kutularındaki yorum satırı bilerek kaldırıldı
    return t


def exists(url: str) -> bool:
    p = urllib.parse.unquote(url.split("#")[0].split("?")[0])
    if not p or p == "/":
        return True
    # Yönlendirmeye giden link artık hata sayılır (yerelde çalışmaz, sunucuda fazladan 301 olur)
    f = OUT / p.lstrip("/")
    return f.is_file() or (f / "index.html").is_file()


def main():
    raw = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    text_diff, broken = [], {}
    for f in sorted(OUT.rglob("*.html")):
        h = f.read_text(encoding="utf-8", errors="replace")
        rel = "/" + str(f.relative_to(OUT))
        page = rel[:-len("index.html")] if rel.endswith("/index.html") else rel
        if page in redirects:
            continue  # eski adres için yönlendirme sayfası
        if raw:
            rf = raw / f.relative_to(OUT)
            if rf.exists():
                a = visible_text(rf.read_text(encoding="utf-8", errors="replace"))
                b = visible_text(h)
                if a != b:
                    text_diff.append(rel)
        for m in re.finditer(r'(?:href|src|data-lazy-src)="(/[^"/][^"]*|/)"', h):
            u = m.group(1)
            if u.startswith("//"):
                continue
            if not exists(u):
                broken.setdefault(u, []).append(rel)
    print(f"metin farkı olan sayfa: {len(text_diff)}")
    for r in text_diff[:20]:
        print("  ", r)
    print(f"kırık iç link/dosya: {len(broken)}")
    for u, pages in sorted(broken.items())[:60]:
        print(f"   {u}  ({len(pages)} sayfa, ör. {pages[0]})")


if __name__ == "__main__":
    main()
