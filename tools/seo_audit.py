#!/usr/bin/env python3
"""SEO/GEO denetimi: dizine açık sayfalarda başlık, açıklama, H1, alt metin, şema, hreflang, iç link."""
import json, re, collections, sys
from html import unescape
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; OUT = ROOT / "site"
red = json.loads((ROOT / "tools/redirects.json").read_text())
red.update(json.loads((ROOT / "tools/redirects-seo.json").read_text()))
pages = {}
for f in OUT.rglob("index.html"):
    rel = str(f.parent.relative_to(OUT)); u = "/" if rel == "." else "/" + rel + "/"
    if u in red or "search" in u: continue
    pages[u] = f.read_text(encoding="utf-8")
def txt(s): return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s))).strip()
rows = []; titles = collections.defaultdict(list); descs = collections.defaultdict(list); inlinks = collections.Counter()
for u, h in pages.items():
    robots = re.search(r"<meta name=.robots. content=.([^'\"]+)", h)
    noindex = bool(robots and "noindex" in robots.group(1))
    t = re.search(r"<title>(.*?)</title>", h, re.S); t = txt(t.group(1)) if t else ""
    d = re.search(r'<meta name="description" content="([^"]*)"', h); d = unescape(d.group(1)) if d else ""
    main = re.search(r"<main[^>]*>(.*?)</main>", h, re.S); body = main.group(1) if main else h
    h1 = [txt(x) for x in re.findall(r"<h1[^>]*>(.*?)</h1>", h, re.S)]
    imgs = re.findall(r"<img\b[^>]*>", body)
    noalt = [i for i in imgs if not re.search(r'\balt="[^"]+', i)]
    for m in re.finditer(r'href="(/[^"#?]*)', body):
        if m.group(1) in pages and m.group(1) != u: inlinks[m.group(1)] += 1
    schema = re.findall(r'"@type":"([A-Za-z]+)"', h)
    words = len(txt(body).split())
    rows.append(dict(u=u, noindex=noindex, t=t, tl=len(t), d=d, dl=len(d), h1=h1, img=len(imgs), noalt=len(noalt),
                     schema=sorted(set(schema)), hreflang="hreflang" in h, words=words, lang=(re.search(r'<html[^>]*lang="([^"]+)"', h) or [None, "?"])[1]))
    if not noindex: titles[t].append(u); descs[d].append(u)
idx = [r for r in rows if not r["noindex"]]
print(f"Toplam sayfa: {len(rows)}  | dizine açık: {len(idx)}  | noindex: {len(rows)-len(idx)}")
def cnt(f): return sum(1 for r in idx if f(r))
print("\n# Başlık (title)")
print(" boş:", cnt(lambda r: not r["t"]), "| 30 karakterden kısa:", cnt(lambda r: 0 < r["tl"] < 30), "| 60'tan uzun:", cnt(lambda r: r["tl"] > 60))
print(" tekrar eden başlık grubu:", sum(1 for v in titles.values() if len(v) > 1))
print("\n# Açıklama (meta description)")
print(" yok:", cnt(lambda r: not r["d"]), "| 70'ten kısa:", cnt(lambda r: 0 < r["dl"] < 70), "| 160'tan uzun:", cnt(lambda r: r["dl"] > 160))
print(" tekrar eden açıklama grubu:", sum(1 for k, v in descs.items() if k and len(v) > 1))
print("\n# H1")
print(" H1 yok:", cnt(lambda r: len(r["h1"]) == 0), "| birden fazla H1:", cnt(lambda r: len(r["h1"]) > 1))
print("\n# Görseller")
print(" toplam görsel:", sum(r["img"] for r in idx), "| alt metni boş/eksik:", sum(r["noalt"] for r in idx), "| etkilenen sayfa:", cnt(lambda r: r["noalt"] > 0))
print("\n# İçerik")
print(" 300 kelimeden az içerikli sayfa:", cnt(lambda r: r["words"] < 300))
print("\n# Yapılandırılmış veri (schema)")
sc = collections.Counter(t for r in idx for t in r["schema"]); print(" ", dict(sc.most_common(12)))
print(" Organization şeması olan sayfa:", cnt(lambda r: "Organization" in r["schema"]), "| Product şeması:", cnt(lambda r: "Product" in r["schema"]), "| FAQ:", cnt(lambda r: "FAQPage" in r["schema"]))
print("\n# Dil ve hreflang")
print(" html lang:", dict(collections.Counter(r["lang"] for r in idx)), "| hreflang olan:", cnt(lambda r: r["hreflang"]))
print("\n# İç linkler")
orphan = [r["u"] for r in idx if inlinks[r["u"]] == 0]
print(" hiç iç link almayan (yetim) sayfa:", len(orphan), orphan[:8])
if "-v" in sys.argv:
    for r in sorted(idx, key=lambda r: r["u"]):
        print(f'{r["u"][:60]:60s} T{r["tl"]:3d} D{r["dl"]:3d} H1:{len(r["h1"])} alt-eksik:{r["noalt"]} kelime:{r["words"]}')
    print("\nTekrar eden başlıklar:"); [print(" ", k, v) for k, v in titles.items() if len(v) > 1]
    print("\nTekrar eden açıklamalar:"); [print(" ", k[:70], v[:4]) for k, v in descs.items() if k and len(v) > 1]
