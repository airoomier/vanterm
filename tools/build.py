#!/usr/bin/env python3
"""
Vanterm: WordPress yansısını (raw/) statik siteye (site/) çevirir.

Kullanım:
  python3 tools/build.py <raw_kok> [--fetch]

<raw_kok>  : wget ile indirilen www.demo.seowpclub.com klasörü
--fetch    : sayfalarda geçen ama indirilmemiş dosyaları (lazy-load görseller, PDF'ler,
             CSS içindeki fontlar) kaynak siteden indirir.

Metinlere dokunulmaz. Yalnızca: alan adı, dosya sorgu dizeleri (?ver=), WordPress'e özgü
gereksiz <head> satırları, form/arama hedefleri değiştirilir; hreflang eklenir.
"""
import html
import json
import os
from html import unescape as html_unescape
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site"
SITE = "https://vanterm.com"
SRC_HOST = "www.demo.seowpclub.com"
SRC_URL = "https://" + SRC_HOST
FALLBACK_URL = "https://vanterm.com"
import datetime
YEAR = datetime.date.today().year
ASSET_EXT = r"(?:css|js|png|jpe?g|gif|svg|webp|avif|woff2?|ttf|eot|otf|ico|pdf|mp4|webm)"

# Bizim yazdığımız, build'in silmemesi gereken dosyalar
KEEP = {"form-gonder.php", "form-ayarlar.php", "assets", ".htaccess", "robots.txt"}

# ---------------------------------------------------------------- yardımcılar

DOM = r"(?:https?:)?(?:\\/\\/|//)(?:www\.)?demo\.seowpclub\.com"
DOM_RE = re.compile(DOM)
DOM_ENC_RE = re.compile(r"https?%3A%2F%2F(?:www\.)?demo\.seowpclub\.com", re.I)


def to_abs(s: str) -> str:
    """Alan adını yayın adresiyle değiştirir (SEO etiketleri, şema)."""
    s = re.sub(r"https?:\\/\\/(?:www\.)?demo\.seowpclub\.com", SITE.replace("/", "\\/"), s)
    s = re.sub(r"(?:https?:)?//(?:www\.)?demo\.seowpclub\.com", SITE, s)
    return s


def to_rel(s: str) -> str:
    """Kalan tüm alan adı geçişlerini kök-göreli yapar."""
    s = re.sub(r"@(?:www\.)?demo\.seowpclub\.com", "@vanterm.com", s)   # e-posta adresleri
    s = re.sub(DOM + r"(?=[\"'\s)<]|$)", "/", s)
    s = DOM_RE.sub("", s)
    s = DOM_ENC_RE.sub(urllib.parse.quote(SITE, safe=""), s)
    return s


QS_RE = re.compile(r"([\"'(\s,=])([^\"'()\s,<>]+?\." + ASSET_EXT + r")\?([^\"'\s)#,<>]*)", re.I)


def strip_qs(s: str) -> str:
    """Yerel dosya adreslerindeki ?ver=... sorgularını kaldırır (harici adreslere dokunmaz)."""
    def rep(m):
        url = m.group(2)
        if "://" in url or url.startswith("//"):
            return m.group(0)
        return m.group(1) + url
    return QS_RE.sub(rep, s)


HEAD_JUNK = [
    r'<link rel="alternate" type="application/rss\+xml"[^>]*>\s*',
    r'<link rel="alternate" title="oEmbed[^>]*>\s*',
    r'<link rel="alternate" title="JSON"[^>]*>\s*',
    r'<link rel="https://api\.w\.org/"[^>]*>\s*',
    r'<link rel="EditURI"[^>]*>\s*',
    r"<link rel='shortlink'[^>]*>\s*",
    r'<meta name="generator"[^>]*>\s*',
    r'<script type="speculationrules">.*?</script>\s*',
    r'<script src="https://www\.google\.com/recaptcha/api\.js"[^>]*></script>\s*',
]


def remove_wpforms_scripts(h: str) -> str:
    h = re.sub(r"<script[^>]*src=[\"'][^\"']*wpforms[^\"']*[\"'][^>]*></script>\s*", "", h)
    h = re.sub(r"<script[^>]*src=[\"'][^\"']*jquery\.validate[^\"']*[\"'][^>]*></script>\s*", "", h)
    h = re.sub(r"<script[^>]*src=[\"'][^\"']*mailcheck[^\"']*[\"'][^>]*></script>\s*", "", h)
    h = re.sub(r"<script[^>]*>(?:(?!</script>).)*wpforms_settings(?:(?!</script>).)*</script>\s*", "", h, flags=re.S)
    h = re.sub(r'\s+data-token(?:-time)?="[^"]*"', "", h)
    return h


REDIRECTS = {}


def final_url(p: str, pages: set) -> str:
    """Orijinal sitede 301 ile yönlenen adresi son hedefe çevirir (zincirleri de izler)."""
    seen = set()
    while p not in seen:
        seen.add(p)
        if p in REDIRECTS:
            p = REDIRECTS[p]
            continue
        m = re.match(r"^/tr/product/(.+)$", p) or None
        if m and "/tr/urun/" + m.group(1) in pages:
            p = "/tr/urun/" + m.group(1)
            continue
        m = re.match(r"^/tr/application/(.+)$", p)
        if m and "/tr/uygulama-tr/" + m.group(1) in pages:
            p = "/tr/uygulama-tr/" + m.group(1)
            continue
        m = re.match(r"^/(tr/)?(?:author/[^/]+/|\d{4}/(?:\d{2}/)?)$", p)
        if m:
            p = "/" + (m.group(1) or "")
            continue
        break
    return p


def resolve_links(h: str, pages: set) -> str:
    def rep(m):
        url = m.group(2)
        path, sep, frag = url.partition("#")
        new = final_url(path, pages)
        return m.group(1) + new + sep + frag + m.group(3)
    return re.sub(r'(href=")(/[^"]*)(")', rep, h)


def lang_of(path: str) -> str:
    return "tr" if path.startswith("/tr/") or path == "/tr/" else "en"


# ---------------------------------------------------------------- sayfalar

def page_path(rel: Path) -> str:
    p = "/" + str(rel.parent).replace(os.sep, "/")
    if p in ("/.", "/"):
        return "/"
    return p.rstrip("/") + "/"


def find_counterparts(h: str) -> dict:
    """WPML dil seçicisinden EN/TR karşılıklarını çıkarır."""
    out = {}
    for m in re.finditer(r'wpml-ls-item-(en|tr)\b[^>]*>\s*<a[^>]*href="([^"]+)"', h):
        out.setdefault(m.group(1), m.group(2))
    return out


def process_html(h: str, path: str, pages: set) -> str:
    for pat in HEAD_JUNK:
        h = re.sub(pat, "", h, flags=re.S)

    # SEO etiketleri ve şema: mutlak yayın adresi
    h = re.sub(r'<link rel="canonical"[^>]*>', lambda m: to_abs(m.group(0)), h)
    h = re.sub(r'<meta (?:property|name)="(?:og|twitter|article):[^"]*"[^>]*>', lambda m: to_abs(m.group(0)), h)
    h = re.sub(r'(<script type="application/ld\+json"[^>]*>)(.*?)(</script>)',
               lambda m: m.group(1) + to_abs(m.group(2)) + m.group(3), h, flags=re.S)
    h = enrich_schema(h, path)

    # hreflang (dil seçicisindeki karşılıklardan)
    cp = {k: to_rel(v) for k, v in find_counterparts(h).items()}
    cp = {k: v for k, v in cp.items() if v in pages}
    if path in pages:
        cp[lang_of(path)] = path
    if "en" in cp and "tr" in cp and "hreflang" not in h:
        tags = (f'<link rel="alternate" hreflang="en" href="{SITE}{cp["en"]}" />\n'
                f'<link rel="alternate" hreflang="tr" href="{SITE}{cp["tr"]}" />\n'
                f'<link rel="alternate" hreflang="x-default" href="{SITE}{cp["en"]}" />\n')
        h = re.sub(r'(<link rel="canonical"[^>]*>\s*)', lambda m: m.group(1) + tags, h, count=1)

    # Diğer her şey kök-göreli
    h = to_rel(h)
    h = live_to_rel_html(h)
    h = strip_qs(h)
    h = resolve_links(h, pages)

    # Arama formu: statik arama sayfası
    h = re.sub(r'(<form[^>]*class="search-form"[^>]*action=")/(")', r"\1/search/\2", h)
    h = re.sub(r'(<form[^>]*class="search-form"[^>]*action=")/tr/(")', r"\1/tr/search/\2", h)
    h = re.sub(r'(<form[^>]*action=")/("[^>]*class="search-form")', r"\1/search/\2", h)
    h = re.sub(r'(<form[^>]*action=")/tr/("[^>]*class="search-form")', r"\1/tr/search/\2", h)

    # Yan sütundaki ay arşivi kutusu (Archives / Arşiv): tarih arşivleri orijinalde de ana sayfaya yönleniyordu
    h = re.sub(r'\s*<aside id="archives-\d+" class="[^"]*widget_archive[^"]*">.*?</aside>', "", h, flags=re.S)

    # Kopyalama kilidi (orijinaldeki "Disable Right Click" betiği): form alanlarında yapıştırma/kopyalama/sağ tık serbest
    FORM_ALANI = "input, textarea, select, [contenteditable]"
    h = h.replace("function nocontextmenu(e) { return false; }",
                  "function nocontextmenu(e) { e = e || window.event; var t = e && e.target; "
                  f"if (t && t.closest && t.closest('{FORM_ALANI}')) return true; return false; }}")
    h = re.sub(r"(element\.addEventListener\(events\[i\], function \(e\) \{\s*)e\.preventDefault\(\);",
               lambda m: m.group(1) + f"if (e.target && e.target.closest && e.target.closest('{FORM_ALANI}')) return; e.preventDefault();", h)

    # Yazı kutularındaki "0 Comment" satırı
    h = re.sub(r'\s*<div class="cspt-meta-date-wrapper cspt-meta-line">\s*<i class="cspt-base-icon-comment-empty"></i>.*?</div>',
               "", h, flags=re.S)

    # Alt bilgi: telif yılı her yıl kendiliğinden güncellenir (statik değer build yılı, JS güncel yılı yazar)
    h = re.sub(r"Copyright © \d{4} Vanterm", f'Copyright © <span class="vt-yil">{YEAR}</span> Vanterm', h)
    # Alt bilgi: tasarım/SEO bağlantısı tek link, nofollow (Google: sitelere dağıtılmış alt bilgi linkleri nofollow olmalı)
    h = re.sub(r'<a href="https://www\.seouzmaniantalya\.com/" target="_blank">Web Design</a>\s*-\s*<a href="https://seowpclub\.com/" target="_blank">SEO</a>',
               '<a href="https://seowpclub.com/" target="_blank" rel="nofollow noopener">Web Design - SEO</a>', h)

    # Düzen standardı CSS'i (tema CSS'lerinden sonra)
    if "vanterm-duzen.css" not in h and "</head>" in h:
        h = h.replace("</head>", '<link rel="stylesheet" href="/assets/vanterm-duzen.css" media="all" />\n</head>', 1)
    if "vanterm-duzen.js" not in h and "</body>" in h:
        h = h.replace("</body>", '<script src="/assets/vanterm-duzen.js"></script>\n</body>', 1)

    # Formlar
    if "wpforms-form" in h:
        h = remove_wpforms_scripts(h)
        if "vanterm-forms.js" not in h:
            h = h.replace("</body>", '<script src="/assets/vanterm-forms.js" defer></script>\n</body>', 1)
    h = add_alts(h, path)
    h = linkify_contacts(h)
    h = describe_links(h)
    h = desktop_spacing(h)
    h = optimize_perf(h, path)
    for src_p, dst_p in REDIRECTS.items():
        h = h.replace(f'{SITE}{src_p}"', f'{SITE}{final_url(dst_p, pages)}"')
        h = h.replace(f'{SITE.replace("/", chr(92) + "/")}{src_p.replace("/", chr(92) + "/")}"',
                      f'{SITE.replace("/", chr(92) + "/")}{final_url(dst_p, pages).replace("/", chr(92) + "/")}"')
    return version_assets(h)


def asset_version(name: str) -> str:
    """Kendi dosyalarımız için sürüm etiketi (içerik değişince değişir → tarayıcı önbelleği yenilenir)."""
    import hashlib
    f = OUT / "assets" / name
    return hashlib.md5(f.read_bytes()).hexdigest()[:8] if f.exists() else "1"


def version_assets(h: str) -> str:
    for name in ("vanterm-duzen.css", "vanterm-duzen.js", "vanterm-forms.js", "vanterm-search.js", "vt-hold.js"):
        h = re.sub(r'/assets/' + re.escape(name) + r'(\?v=[0-9a-f]+)?"', f'/assets/{name}?v={asset_version(name)}"', h)
    return h


LIVE_RE = re.compile(r"(?:https?:)?//(?:www\.)?vanterm\.com(?=[/\"')\s]|$)")


def live_to_rel_css(s: str) -> str:
    """CSS içindeki eski canlı site adreslerini (http://www.vanterm.com/...) kök-göreli yapar."""
    return LIVE_RE.sub("", s)


def live_to_rel_html(h: str) -> str:
    """İçerikteki https://vanterm.com/... linklerini kök-göreli yapar (demo/yerel/canlıda çalışır).
    canonical, hreflang, meta (OG/Twitter) etiketleri ve JSON-LD mutlak kalır."""
    def tag(m):
        t = m.group(0)
        if t.startswith("<meta") or (t.startswith("<link") and ("canonical" in t or "hreflang" in t or "shortlink" in t)):
            return t
        t = re.sub(r'((?:href|src|action|data-[\w-]+)=")(?:https?:)?//(?:www\.)?vanterm\.com(/[^"]*)?"',
                   lambda a: a.group(1) + (a.group(2) or "/") + '"', t)
        t = re.sub(r"url\((['\"]?)(?:https?:)?//(?:www\.)?vanterm\.com/", r"url(\1/", t)
        return t
    return re.sub(r"<(?:a|img|link|script|form|source|iframe|div|section|span|li|input|meta|figure)\b[^>]*>", tag, h)


def process_css(s: str) -> str:
    return strip_qs(live_to_rel_css(to_rel(s)))


# ---------------------------------------------------------------- yapılandırılmış veri (GEO)

# Sitede görünen şirket bilgileri (üst bar, alt bilgi, iletişim sayfası)
ORG_EXTRA = {
    "alternateName": "VANTERM",
    "foundingDate": "1971",
    "email": "bilgi@vanterm.com",
    "telephone": "+90-262-751-0594",
    "address": {"@type": "PostalAddress", "streetAddress": "Gebze Organize Sanayi Bölgesi 800 Sok. No:804",
                "addressLocality": "Gebze", "addressRegion": "Kocaeli", "postalCode": "41480", "addressCountry": "TR"},
    "contactPoint": {"@type": "ContactPoint", "telephone": "+90-262-751-0594", "email": "bilgi@vanterm.com",
                     "contactType": "sales", "availableLanguage": ["en", "tr"]},
    "sameAs": ["https://www.youtube.com/user/VANTERMSince1971"],
}


def enrich_schema(h: str, path: str) -> str:
    """Yoast şemasına: şirket iletişim bilgileri; uygulama (vaka çalışması) sayfalarına Article düğümü."""
    def rep(m):
        try:
            d = json.loads(m.group(2))
        except Exception:
            return m.group(0)
        graph = d.get("@graph", [])
        org = next((n for n in graph if n.get("@type") == "Organization"), None)
        org_id = org.get("@id") if org else f"{SITE}/#organization"
        page = next((n for n in graph if n.get("@type") in ("WebPage", "CollectionPage", "ItemPage")), None)
        for n in graph:
            if n.get("@type") == "Organization":
                for k, v in ORG_EXTRA.items():
                    n.setdefault(k, v)
        is_case = re.match(r"^/(application|tr/uygulama-tr)/[^/]+/$", path)
        if is_case and page and not any(n.get("@type") == "Article" for n in graph):
            url = page.get("url") or page.get("@id")
            art = {"@type": "Article", "@id": url + "#article", "isPartOf": {"@id": url}, "mainEntityOfPage": {"@id": url},
                   "headline": re.sub(r"\s*\|\s*Vanterm\s*$", "", page.get("name", ""))[:110],
                   "articleSection": "Uygulama Örnekleri" if lang_of(path) == "tr" else "Case Studies",
                   "author": {"@id": org_id}, "publisher": {"@id": org_id}, "inLanguage": page.get("inLanguage")}
            for k in ("description", "datePublished", "dateModified"):
                if page.get(k): art[k] = page[k]
            img = next((n for n in graph if n.get("@type") == "ImageObject"), None)
            if img: art["image"] = {"@id": img.get("@id")}
            graph.append(art)
        return m.group(1) + json.dumps(d, ensure_ascii=False, separators=(",", ":")) + m.group(3)
    return re.sub(r'(<script type="application/ld\+json"[^>]*>)(.*?)(</script>)', rep, h, count=1, flags=re.S)


def write_llms(pages_html: dict):
    """Yapay zeka arama motorları için site özeti (llms.txt, https://llmstxt.org biçimi)."""
    def info(p):
        h = pages_html.get(p, "")
        d = re.search(r'<meta name="description" content="([^"]+)"', h)
        if not d:
            j = re.search(r'"@type":"WebPage"[^}]*?"description":"([^"]+)"', h)
            d = j
        return page_name(h, p), (html_unescape(d.group(1)) if d else "")

    def section(title, prefix, exclude=()):
        lines = [f"\n## {title}\n"]
        for p in sorted(x for x in pages_html if re.match(prefix, x) and x not in exclude):
            n, d = info(p)
            if n:
                lines.append(f"- [{n}]({SITE}{p})" + (f": {d}" if d else ""))
        return lines

    out = ["# Vanterm", "",
           "> VANTERM (Gebze, Kocaeli, Turkey) has designed and manufactured industrial dust collectors, fume extractors "
           "and filtration systems since 1971: mobile and central filter units, extraction arms, workbenches and cutting "
           "tables for welding, laser/plasma cutting, grinding, sandblasting and woodworking. The site is bilingual "
           "(English at /, Turkish at /tr/).", "",
           f"Contact: bilgi@vanterm.com · +90 262 751 05 94 · {SITE}/contact-us/"]
    out += ["\n## Company\n"] + [f"- [{info(p)[0]}]({SITE}{p})" for p in ("/about-us/", "/products/", "/applications/", "/info-center/", "/contact-us/", "/product-registration/") if p in pages_html]
    out += section("Products", r"^/product/[^/]+/$")
    out += section("Product categories", r"^/portfolio-category/[^/]+/$")
    out += section("Applications (case studies)", r"^/application/[^/]+/$")
    out += section("Articles", r"^/(?!tr/|product/|application/|portfolio-category/|category/|tag/|application-category/|author/|search/)[^/]+/$",
                   exclude=("/about-us/", "/products/", "/applications/", "/info-center/", "/contact-us/", "/product-registration/", "/privacy-policy/"))
    out += ["\n## Türkçe\n"] + [f"- [{info(p)[0]}]({SITE}{p})" for p in ("/tr/", "/tr/hakkimizda/", "/tr/urunler/", "/tr/uygulamalar/", "/tr/bilgi-merkezi/", "/tr/iletisim/") if p in pages_html]
    (OUT / "llms.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- performans (PageSpeed)

FONTS_CSS = ROOT / "site" / "assets" / "fonts" / "fonts.css"
ASYNC_CSS = ("magnific-popup.css", "balloon.min.css", "font-awesome/css/all.min.css", "v4-shims.min.css",
             "font-awesome/css/font-awesome.min.css")
YT_EMBED_RE = re.compile(r'<iframe\b[^>]*\bsrc="https://www\.youtube(?:-nocookie)?\.com/embed/([\w-]{6,})[^"]*"[^>]*>\s*</iframe>', re.I)


def make_webp(src: Path):
    try:
        from PIL import Image
    except ImportError:
        print("Pillow yok, WebP atlandı"); return
    n = 0
    for f in list(src.rglob("*")):
        clean = f.name.split("?")[0]
        if Path(clean).suffix.lower() not in (".jpg", ".jpeg", ".png") or not f.is_file():
            continue
        w = f.with_name(clean + ".webp")
        if w.exists() or f.stat().st_size < 4000:
            continue
        try:
            import io
            im = Image.open(f)
            if im.mode in ("P", "LA", "RGBA", "PA") or "transparency" in im.info:
                im = im.convert("RGBA")
                if im.getchannel("A").getextrema()[0] == 255:      # aslında saydam değil
                    im = im.convert("RGB")
            if im.mode == "RGBA":
                adaylar = []
                for kw in (dict(lossless=True, method=6), dict(quality=85, alpha_quality=90, method=6)):
                    b = io.BytesIO(); im.save(b, "WEBP", **kw); adaylar.append(b.getvalue())
                w.write_bytes(min(adaylar, key=len))
            else:
                im.convert("RGB").save(w, "WEBP", quality=80, method=6)
            if w.stat().st_size > f.stat().st_size * 0.9:   # kazanç yoksa tutma
                w.unlink(); w.write_bytes(b"")  # boş işaret dosyası: tekrar denenmesin
            n += 1
        except Exception:
            pass
    print(f"webp üretildi/denendi: {n}")


CSS_BUNDLES = {}


def bundle_css(h: str) -> str:
    """Engelleyici yerel CSS dosyalarını sırasıyla tek dosyada birleştirir (istek sayısı ~20 → 1).
    Satır içi <style> blokları paketin hemen ardından, orijinal sıralarıyla kalır."""
    head_end = h.find("</head>")
    head = h[:head_end]
    links = list(re.finditer(r"<link rel='stylesheet'[^>]*href='(/[^']+\.css)'[^>]*media='all'[^>]*/?>\s*", head))
    links = [m for m in links if "onload=" not in m.group(0)]
    if len(links) < 2:
        return h
    files = [m.group(1) for m in links]
    key = "|".join(files)
    if key not in CSS_BUNDLES:
        import hashlib
        parts = []
        for f in files:
            p = OUT / f.lstrip("/")
            if not p.exists():
                return h
            css = p.read_text(encoding="utf-8", errors="replace")
            base = f.rsplit("/", 1)[0] + "/"
            css = re.sub(r"url\(\s*(['\"]?)(?!data:|https?:|//|/|#)([^'\")]+)\1\s*\)",
                         lambda m: "url(" + m.group(1) + urllib.parse.urljoin(base, m.group(2)) + m.group(1) + ")", css)
            css = re.sub(r"@charset[^;]+;", "", css)
            parts.append(f"/* {f} */\n{css}")
        data = "@charset \"UTF-8\";\n" + "\n".join(parts)
        name = "bundle-" + hashlib.md5(data.encode()).hexdigest()[:10] + ".css"
        (OUT / "assets" / name).write_text(data, encoding="utf-8")
        CSS_BUNDLES[key] = name
    name = CSS_BUNDLES[key]
    first = links[0]
    out = head[:first.start()] + f"<link rel='stylesheet' id='vt-bundle-css' href='/assets/{name}' media='all' />\n"
    pos = first.end()
    for m in links[1:]:
        out += head[pos:m.start()]
        pos = m.end()
    out += head[pos:]
    return out + h[head_end:]


def critical_css(html_by_path: dict):
    import hashlib, tempfile
    node_mods = ROOT / "tools" / "node_modules"
    if not (node_mods / "purgecss").exists() or shutil.which("node") is None:
        print("purgecss yok: kritik CSS atlandı (cd tools && npm i)"); return
    crit_dir = OUT / "assets" / "crit"
    if crit_dir.exists():
        shutil.rmtree(crit_dir)
    crit_dir.mkdir(parents=True)
    for old in (OUT / "assets").glob("full-*.css"):
        old.unlink()
    duzen = (OUT / "assets" / "vanterm-duzen.css").read_text(encoding="utf-8")
    full_names, jobs, tmp = {}, [], Path(tempfile.mkdtemp())
    for path, h in html_by_path.items():
        m = re.search(r"<link rel='stylesheet' id='vt-bundle-css' href='/assets/(bundle-[0-9a-f]+\.css)' media='all' />", h)
        if not m:
            continue
        b = m.group(1)
        if b not in full_names:
            data = (OUT / "assets" / b).read_text(encoding="utf-8") + "\n/* vanterm-duzen.css */\n" + duzen
            name = "full-" + hashlib.md5(data.encode()).hexdigest()[:10] + ".css"
            (OUT / "assets" / name).write_text(data, encoding="utf-8")
            full_names[b] = name
        page_html = tmp / (hashlib.md5(path.encode()).hexdigest() + ".html")
        page_html.write_text(h, encoding="utf-8")
        jobs.append({"css": str(OUT / "assets" / full_names[b]), "html": str(page_html),
                     "out": str(tmp / (page_html.stem + ".css")), "path": path, "bundle": b})
    # Tam paketleri de sadeleştir: herhangi bir sayfada veya herhangi bir JS dosyasında geçen kurallar kalır
    all_html = [str(p) for p in tmp.glob("*.html")]
    js_files = [str(p) for p in OUT.rglob("*.js") if p.stat().st_size < 600_000]
    full_jobs = [{"css": str(OUT / "assets" / n), "html": all_html + js_files, "out": str(OUT / "assets" / n)}
                 for n in set(full_names.values())]
    ff = tmp / "full.json"; ff.write_text(json.dumps(full_jobs), encoding="utf-8")
    r = subprocess.run(["node", str(ROOT / "tools" / "purge.js"), str(ff)], env={**os.environ, "NODE_PATH": str(node_mods)},
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("tam paket sadeleştirme atlandı:", r.stderr[-300:])
    jf = tmp / "jobs.json"; jf.write_text(json.dumps(jobs), encoding="utf-8")
    r = subprocess.run(["node", str(ROOT / "tools" / "purge.js"), str(jf)], env={**os.environ, "NODE_PATH": str(node_mods)},
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("purgecss hatası, kritik CSS atlandı:", r.stderr[-400:]); return
    for j in jobs:
        css = Path(j["out"]).read_text(encoding="utf-8")
        name = hashlib.md5(css.encode()).hexdigest()[:12] + ".css"
        if not (crit_dir / name).exists():
            (crit_dir / name).write_text(css, encoding="utf-8")
        full = full_names[j["bundle"]]
        h = html_by_path[j["path"]]
        h = h.replace(f"<link rel='stylesheet' id='vt-bundle-css' href='/assets/{j['bundle']}' media='all' />",
                      f"<link rel='stylesheet' id='vt-crit-css' href='/assets/crit/{name}' media='all' />\n"
                      f"<link rel='stylesheet' id='vt-full-css' href='/assets/{full}' media='print' onload=\"this.media='all'\" />"
                      f"<noscript><link rel='stylesheet' href='/assets/{full}' media='all' /></noscript>", 1)
        h = re.sub(r'<link rel="stylesheet" href="/assets/vanterm-duzen\.css(\?v=[0-9a-f]+)?" media="all" />\s*', "", h)
        html_by_path[j["path"]] = h
        dest = OUT / (j["path"].lstrip("/") + "index.html")
        dest.write_text(h, encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"kritik CSS: {len(jobs)} sayfa, {len(list(crit_dir.glob('*.css')))} dosya, {len(full_names)} tam paket")


def optimize_perf(h: str, path: str) -> str:
    if "</head>" not in h or 'http-equiv="refresh"' in h:
        return h

    # 1) Google Fonts yerine siteye gömülü fontlar (temanın bozuk ve engelleyici font isteği kaldırılır)
    h = re.sub(r"<link rel='dns-prefetch' href='//fonts\.googleapis\.com' />\s*", "", h)
    h = re.sub(r"<link[^>]*href=['\"](?:https?:)?//fonts\.googleapis\.com/[^'\"]*['\"][^>]*>\s*", "", h)
    h = re.sub(r"<link[^>]*href=['\"](?:https?:)?//fonts\.gstatic\.com['\"][^>]*>\s*", "", h)
    if FONTS_CSS.exists() and "vt-fonts" not in h:
        pre = ('<link rel="preload" href="/assets/fonts/barlow-condensed-latin-500-normal.woff2" as="font" type="font/woff2" crossorigin>\n'
               f'<style id="vt-fonts">{FONTS_CSS.read_text(encoding="utf-8")}</style>\n')
        h = re.sub(r"(<meta charset[^>]*>\s*)", lambda m: m.group(1) + pre, h, count=1) if "<meta charset" in h \
            else h.replace("</head>", pre + "</head>", 1)

    # 1b) Sayfada slayt yoksa Revolution Slider betikleri ve CSS'i yüklenmesin (~230 KB)
    if "<rs-module" not in h:
        h = re.sub(r"<link rel='stylesheet' id='rs-plugin-settings-css'[^>]*>\s*", "", h)
        h = re.sub(r"<style id='rs-plugin-settings-inline-css'[^>]*>.*?</style>\s*", "", h, flags=re.S)
        h = re.sub(r"<script[^>]*(?:rbtools|rs6)\.min\.js[^>]*></script>\s*", "", h)
        h = re.sub(r"<script[^>]*>(?:(?!</script>).)*(?:RS_MODULES|setREVStartSize|revslider_showDoubleJqueryError)(?:(?!</script>).)*</script>\s*",
                   "", h, flags=re.S)

    # 2) Kritik olmayan CSS'ler (ikon fontları, lightbox, ipucu) sayfa çizimini engellemesin
    def css_async(m):
        tag = m.group(0)
        if not any(k in tag for k in ASYNC_CSS) or "onload=" in tag:
            return tag
        t = re.sub(r"media=['\"]all['\"]", "", tag).replace("/>", "").rstrip(">").rstrip()
        return f"{t} media=\"print\" onload=\"this.media='all'\" />"
    h = re.sub(r"<link rel='stylesheet'[^>]*>", css_async, h)
    h = bundle_css(h)

    # 3) Harici betikler: defer (sıra korunur); jQuery'ye bağlı satır içi betikler DOMContentLoaded'da
    def ext(m):
        tag = m.group(0)
        if "type=\"application/ld+json\"" in tag or re.search(r"\bdefer\b", tag):
            return tag
        # jQuery'ye bağlı async betikler (Revolution Slider) jQuery'den önce çalışmasın: async -> defer
        if re.search(r"\basync\b", tag):
            if re.search(r"revslider|rbtools|rs6", tag):
                return re.sub(r"\basync\b", "defer", tag, count=1)
            return tag
        return tag.replace("<script", "<script defer", 1)
    h = re.sub(r"<script\b[^>]*\bsrc=[\"'][^\"']+[\"'][^>]*>", ext, h)
    # jQuery'nin hemen ardından: "ready" olayını tüm defer betikler yüklenene kadar beklet
    if "vt-hold.js" not in h:
        h = re.sub(r"(<script defer id=\"jquery-migrate-js\"[^>]*></script>|<script defer id=\"jquery-core-js\"[^>]*></script>)",
                   lambda m: m.group(1) + '\n<script defer src="/assets/vt-hold.js"></script>', h, count=1)

    def inline(m):
        attrs, code = m.group(1), m.group(2)
        if "ld+json" in attrs or "text/html" in attrs or "vt-defer" in attrs:
            return m.group(0)
        if "revslider_showDoubleJqueryError ===" in code:     # yalnızca bir fonksiyon tanımı; global kalmalı
            return m.group(0)
        if re.search(r"\bjQuery\s*[(.]|\btpj\b|\$\(", code) and "document.write" not in code:
            # Sarmalayınca üst düzey "var x" yerel olur; global kalsın diye window.x yapılır
            code = re.sub(r"(?m)^(\s*)var(\s+)(\w+)\s*;", r"\1window.\3 = window.\3;", code)
            code = re.sub(r"(?m)^(\s*)var(\s+)(\w+)\s*=", r"\1window.\3 =", code)
            return (f"<script{attrs} data-vt-defer>document.addEventListener('DOMContentLoaded',function(){{\n"
                    f"{code}\n}});</script>")
        return m.group(0)
    h = re.sub(r"<script((?:(?!\bsrc=)[^>])*)>(.*?)</script>", inline, h, flags=re.S)

    # 4) YouTube video kartları: tıklayınca yüklenen önizleme (1,5 MB YouTube betiği açılışta inmez)
    def yt(m):
        vid = m.group(1)
        w = (re.search(r'width="(\d+)"', m.group(0)) or [None, "711"])[1]
        hh = (re.search(r'height="(\d+)"', m.group(0)) or [None, "400"])[1]
        return (f'<div class="vt-yt" data-id="{vid}" style="aspect-ratio:{w}/{hh}">'
                f'<img src="https://i.ytimg.com/vi/{vid}/hqdefault.jpg" alt="YouTube video" loading="lazy" decoding="async" width="480" height="360">'
                f'<button type="button" class="vt-yt-play" aria-label="Play video / Videoyu oynat"></button></div>')
    h = YT_EMBED_RE.sub(yt, h)

    # 5) Görseller: ilk ekrandaki (ilk içerik satırı + ilk büyük görsel) eager; geri kalanı tembel yükleme
    ms = re.search(r"<main[^>]*>", h)
    if ms:
        rest = h[ms.end():]
        rows = [m.start() for m in re.finditer(r'<div[^>]*class="vc_row wpb_row', rest)]
        first_row_end = rows[1] if len(rows) > 1 else 4000
        hero_done = False

        def img(m):
            nonlocal hero_done
            t = m.group(0)
            if "rs-lazyload" in t or "data-lazyload" in t or "data-lazy-src" in t or "dummy.png" in t or re.search(r"\bloading=", t):
                return t
            w = int((re.search(r'width="(\d+)"', t) or [0, "0"])[1] or 0)
            big = w >= 300 or not re.search(r'width="', t)
            if not hero_done and big and m.start() < max(first_row_end, 1500) + 6000:
                hero_done = True
                return t.replace("<img", '<img fetchpriority="high" decoding="async"', 1)
            if m.start() < first_row_end:
                return t.replace("<img", '<img decoding="async"', 1)
            return t.replace("<img", '<img loading="lazy" decoding="async"', 1)
        h = h[:ms.end()] + re.sub(r"<img\b[^>]*>", img, rest)

    # 6) LCP arka plan görseli: ilk satırın arka planı veya sayfa başlık bandı önceden yüklenir
    pre_img = None
    body = h[ms.end():] if ms else ""
    row = re.search(r'class="vc_row [^"]*?(vc_custom_\d+)[^"]*cspt-bgimage-yes', body[:3000])
    if row:
        bg = re.search(r"\." + row.group(1) + r"\{[^}]*background-image:\s*url\(([^)]+)\)", h)
        if bg:
            pre_img = bg.group(1).strip("'\"")
    if not pre_img and "cspt-title-bar-wrapper" in h:
        pre_img = "/wp-content/uploads/2019/10/common-bgg-1.jpg"
    if pre_img and f'href="{pre_img}" as="image"' not in h:
        h = h.replace("</head>", f'<link rel="preload" href="{pre_img}" as="image" fetchpriority="high">\n</head>', 1)
    return h


# ---------------------------------------------------------------- tıklanabilir telefon / e-posta

# Aranabilir numaralar (faks +90 (262) 751 1350 bilerek dışarıda)
PHONES = {"+90 (262) 751 0594": "+902627510594"}
EMAIL_RE = re.compile(r"(?<![\w.+-])([\w.+-]+@(?:[\w-]+\.)+[a-z]{2,})(?![\w-])", re.I)



def desktop_spacing(h: str) -> str:
    """Masaüstünde iç sayfa bölümlerinin (vc_row) üst/alt boşluklarını ~1,75 kat artırır.
    Ana sayfa hariç; mobil değerler aynı kalır."""
    body = re.search(r'<body[^>]*class="([^"]*)"', h)
    if not body:
        return h
    canon = re.search(r'<link rel="canonical" href="https://vanterm\.com(/[^"]*)"', h)
    canon = canon.group(1) if canon else ""
    # ana sayfa ve iletişim sayfalarında biraz daha geniş
    factor = 2.0 if (re.search(r'\bhome\b', body.group(1)) or canon in ("/contact-us/", "/tr/iletisim/")) else 1.75
    order, bgs = [], []
    for m2 in re.finditer(r'class="(vc_row wpb_row vc_row-fluid(?![^"]*vc_inner)[^"]*)"', h):
        c = re.search(r'vc_custom_(\d+)', m2.group(1))
        order.append(c.group(1) if c else "")
        bg = re.search(r'cspt-bg-color-(white|light|transparent|[a-z]+color)\b', m2.group(1))
        bgs.append(("white" if bg and bg.group(1) in ("white", "transparent") else bg.group(1)) if bg else "white")
    rows = set(o for o in order if o)
    m = re.search(r'(<style data-type="vc_shortcodes-custom-css">)(.*?)(</style>)', h, re.S)
    if not m or not rows:
        return h
    decls = dict(re.findall(r'\.vc_custom_(\d+)\{([^}]*)\}', m.group(2)))
    def pad(cid, side):
        v = re.search(r'padding-' + side + r':\s*(\d+)px', decls.get(cid, ""))
        return int(v.group(1)) if v else None
    # alt boşluğu küçük (<=20px) bir satır, altındaki satıra bağlı tasarlanmıştır (ör. başlık + içerik):
    # o birleşimi büyütme
    keep = set()
    for i, (a, b) in enumerate(zip(order, order[1:])):
        pb = pad(a, "bottom") if a else None
        if pb is not None and pb <= 20 and bgs[i] == bgs[i + 1]:
            keep.add((a, "bottom"))
            if b:
                keep.add((b, "top"))
    # renk değişen bölüm sınırlarında en az 70px
    edge = set()
    for i, (a, b) in enumerate(zip(order, order[1:])):
        if bgs[i] != bgs[i + 1]:
            if a: edge.add((a, "bottom"))
            if b: edge.add((b, "top"))
    out = []
    for cid, decl in decls.items():
        if cid not in rows:
            continue
        parts = []
        for side in ("top", "bottom"):
            v = re.search(r'padding-' + side + r':\s*(\d+)px', decl)
            if (cid, side) in keep:
                continue
            if v and int(v.group(1)) > 0:
                n = min(100, int(round(int(v.group(1)) * factor / 5.0)) * 5)
                if (cid, side) in edge:
                    n = max(n, 70)
                parts.append(f"padding-{side}:{n}px !important")
        if parts:
            out.append(f"body #content .vc_row.vc_custom_{cid}{{{';'.join(parts)}}}")
    if not out:
        return h
    extra = "<style id=\"vt-bosluk\">@media (min-width:992px){" + "".join(out) + "}</style>"
    return h[:m.end()] + extra + h[m.end():]


GENERIC_LINK_RE = re.compile(r'(<a\s[^>]*href="([^"]+)"[^>]*>)(\s*(?:Read More|Read more|More|Devamı|Devamını Oku)\s*)(</a>)')


X_SVG = ('<svg viewBox="0 0 24 24" width="1em" height="1em" fill="currentColor" focusable="false">'
         '<path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>')


def describe_links(h: str) -> str:
    """"Read More / More / Devamı" linklerine, görünen metni değiştirmeden, ekran okuyucu ve
    arama motorları için gizli açıklama ekler (linkin gittiği yazının başlığı)."""
    def title_for(href, before, span=6000):
        win = before[-span:]
        best = None
        hm = re.search(r'<h[1-6][^>]*>\s*<a\s[^>]*href="' + re.escape(href) + r'"[^>]*>([^<]{3,200})</a>', win)
        if hm:
            return html.unescape(hm.group(1)).strip()
        for m in re.finditer(r'<a\s[^>]*href="' + re.escape(href) + r'"[^>]*>([^<]{3,200})</a>', win):
            t = html.unescape(m.group(1)).strip()
            if t and not GENERIC_LINK_RE.fullmatch('<a href="x">' + m.group(1) + '</a>') and len(t) > len(best or ''):
                best = t
        if best:
            return best
        for m in re.finditer(r'<a\s[^>]*href="' + re.escape(href) + r'"[^>]*>\s*<img[^>]*\salt="([^"]{3,200})"', win):
            best = html.unescape(m.group(1)).strip()
        return best

    out, pos = [], 0
    for m in GENERIC_LINK_RE.finditer(h):
        if 'vt-sr' in m.group(3):
            continue
        t = title_for(m.group(2), h[:m.start()])
        if not t:
            continue
        out.append(h[pos:m.start()])
        out.append(m.group(1) + m.group(3).rstrip() + '<span class="vt-sr">: ' + html.escape(t, quote=False) + '</span>' + m.group(4))
        pos = m.end()
    out.append(h[pos:])
    h = "".join(out)
    tr = '<html lang="tr' in h

    # İçinde metin olmayan linkler (ikon/görsel): aria-label
    def empty_link(m):
        tag, href, inner = m.group(1), m.group(2), m.group(3)
        vis = re.sub(r'<span class="creativesplanet-hide">.*?</span>', '', inner, flags=re.S)
        if 'aria-label=' in tag or re.sub(r'<[^>]+>', '', vis).strip() or re.search(r'<img[^>]*\salt="[^"]+"', inner):
            return m.group(0)
        icon = re.search(r'cspt-base-icon-(twitter|youtube-play|facebook|linkedin|instagram)', inner)
        if 'youtube.com/watch' in href:
            t = 'YouTube video'
        elif icon:
            t = {'twitter': 'X', 'youtube-play': 'YouTube', 'facebook': 'Facebook',
                 'linkedin': 'LinkedIn', 'instagram': 'Instagram'}[icon.group(1)]
        elif 'scroll-to-top' in tag:
            t = 'Sayfa başına dön' if tr else 'Back to top'
        else:
            t = title_for(href, h, len(h)) or None
        if not t:
            return m.group(0)
        return tag[:-1] + ' aria-label="' + html.escape(t) + '">' + inner + '</a>'
    h = re.sub(r'(<a\s[^>]*href="([^"]+)"[^>]*>)((?:(?!</a>).){0,2000}?)</a>', empty_link, h, flags=re.S)

    h = h.replace('<button id="menu-toggle" class="nav-menu-toggle">',
                  '<button id="menu-toggle" class="nav-menu-toggle" aria-label="' + ('Menü' if tr else 'Menu') + '">')
    h = h.replace('<a role="button" tabindex="0" class="cli_settings_button"',
                  '<a role="button" tabindex="0" class="cli_settings_button" aria-label="' + ('Çerez ayarları' if tr else 'Cookie settings') + '"')
    h = h.replace('<span class="wpml-ls-native" role="menuitem">', '<span class="wpml-ls-native">')
    # Twitter kuşu yerine X logosu
    h = h.replace('<i class="cspt-base-icon-twitter"></i>', '<i class="vt-x" aria-hidden="true">' + X_SVG + '</i>')
    h = h.replace('title="Share on Twitter"', 'title="Share on X"')
    h = re.sub(r'<button type="submit" class="search-submit">([^<]+)</button>',
               lambda m: '<button type="submit" class="search-submit" aria-label="' + m.group(1).strip() + '">' + m.group(1) + '</button>', h)
    return h


def linkify_contacts(h: str) -> str:
    """Görünen metindeki telefon ve e-postaları tel: / mailto: linki yapar (link, script, stil ve başlık içi hariç)."""
    parts = re.split(r"(<[^>]+>)", h)
    skip = {"a": 0, "script": 0, "style": 0, "head": 0, "title": 0, "textarea": 0, "option": 0, "button": 0}
    out = []
    for part in parts:
        if part.startswith("<"):
            m = re.match(r"<(/?)([a-zA-Z]+)", part)
            if m and m.group(2).lower() in skip and not part.endswith("/>"):
                skip[m.group(2).lower()] += -1 if m.group(1) else 1
                skip[m.group(2).lower()] = max(0, skip[m.group(2).lower()])
            out.append(part)
            continue
        if any(skip.values()) or not part.strip():
            out.append(part)
            continue
        t = part
        for shown, num in PHONES.items():
            t = t.replace(shown, f'<a href="tel:{num}" class="vt-tel">{shown}</a>')
        t = EMAIL_RE.sub(lambda e: f'<a href="mailto:{e.group(1)}" class="vt-mail">{e.group(1)}</a>', t)
        out.append(t)
    return "".join(out)


# ---------------------------------------------------------------- görsel alt metinleri

TR_WORDS = {"application": "uygulama", "applications": "uygulamaları", "photo": "fotoğraf", "photos": "fotoğraflar",
            "certification": "sertifika", "certificate": "sertifika", "detail": "detay", "details": "detaylar",
            "and": "ve", "filter": "filtre", "unit": "ünitesi", "units": "üniteleri"}


# Referans logoları (dosya adı anlamsız olanlar; logolara bakılarak eşlendi)
CLIENT_LOGOS = {"client-logo-6-1": "Borusan Cat", "client-logo-2": "Siemens", "client-logo-3": "Kirchhoff Automotive",
                "client-logo-4": "Mercedes-Benz", "client-logo-7": "Aygaz", "client-logo-8": "IPG Photonics",
                "client-logo-9": "Teknik Malzeme", "client-logo-1": "Turkish Technic", "client-logo-5": "Hektaş"}
SLUG_ALT = re.compile(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+){2,}")


def humanize(name: str, lang: str) -> str:
    """Dosya adı/başlıktan okunur metin: 'KTM-1500-1-770x350.jpg' -> 'KTM 1500'."""
    n = re.sub(r"\.(jpe?g|png|gif|webp|svg)$", "", name, flags=re.I)
    n = re.sub(r"-\d+x\d+$", "", n)
    n = re.sub(r"(?:[-_ ]\d{1,2})+$", "", n)            # sondaki -1, -2-1 gibi sıra ekleri
    n = re.sub(r"[-_]+", " ", n).strip()
    n = re.sub(r"\b(?:scaled|copy|min|edited|e\d+)\b", "", n, flags=re.I).strip()
    if lang == "tr":
        n = " ".join(TR_WORDS.get(w.lower(), w) for w in n.split())
    return n[:1].upper() + n[1:] if n else ""


def page_name(h: str, path: str = "") -> str:
    m = None if path in ("/", "/tr/") else re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S)
    t = html_unescape(re.sub(r"<[^>]+>", " ", m.group(1))).strip() if m else ""
    if not t or len(t) > 90:
        m = re.search(r"<title>(.*?)</title>", h, re.S)
        t = html_unescape(m.group(1)).strip() if m else ""
        t = re.sub(r"\s*[|\-–]\s*Vanterm.*$", "", t)
        t = re.sub(r"^Vanterm\s*[|\-–]\s*", "", t)
    return re.sub(r"\s+", " ", t).strip()


def esc_attr(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def add_alts(h: str, path: str) -> str:
    """Ana içerikte alt metni olmayan görsellere bağlamdan açıklayıcı alt metin ekler."""
    lang = lang_of(path)
    name = page_name(h, path)
    ms = re.search(r"<main[^>]*>", h); me = h.rfind("</main>")
    if not ms or me < 0:
        return h
    a, b = ms.end(), me
    body = h[a:b]

    def strip(x):
        return re.sub(r"\s+", " ", html_unescape(re.sub(r"<[^>]+>", " ", x))).strip()

    out, pos = [], 0
    for im in re.finditer(r"<img\b[^>]*>", body):
        tag = im.group(0)
        cur = re.search(r'\balt="([^"]*)"', tag)
        before, after = body[max(0, im.start() - 600):im.start()], body[im.end():im.end() + 3000]
        in_card = bool(re.search(r"<article class=\"creativesplanet-ele creativesplanet-ele-(service|portfolio|blog)", before)) and \
            "</article>" not in before[before.rfind("<article"):]
        # Kart görsellerinde alt metin her zaman kartın başlığı (orijinalde EN sayfada TR alt metinler vardı);
        # diğerlerinde anlamlı alt metin varsa korunur
        if not in_card and cur and cur.group(1).strip() and not SLUG_ALT.fullmatch(cur.group(1).strip()):
            continue
        src = (re.search(r'src="([^"]+)"', tag) or [None, ""])[1].split("/")[-1]
        title_attr = (re.search(r'title="([^"]*)"', tag) or [None, ""])[1]
        alt = ""
        # 1) Kart (uygulama/ürün/yazı): kartın başlığı
        if re.search(r"<article class=\"creativesplanet-ele creativesplanet-ele-(service|portfolio|blog)", before) and \
                "</article>" not in before[before.rfind("<article"):]:
            t = re.search(r'class="cspt-(?:service|portfolio|post)-title"[^>]*>(.*?)</h3>', after.split("</article>")[0], re.S)
            if t: alt = strip(t.group(1))
        # 2) Müşteri/referans logosu
        if not alt and re.search(r"creativesplanet-ele-client|cspt-client", before):
            key = re.sub(r"\.(png|jpe?g|gif|webp)$", "", src, flags=re.I)
            n = CLIENT_LOGOS.get(key) or humanize(src, lang)
            generic = not n or re.match(r"(?i)client logo|logo$", n)
            alt = ("Referans müşteri logosu" if lang == "tr" else "Reference customer logo") if generic else \
                  re.sub(r"(?i)\s*logo\s*$", "", n) + " logo"
        # 3) Özellik kutusu: ürün adı + kutu başlığı
        if not alt and "cspt-static-box" in before[-300:]:
            t = re.search(r'creativesplanet-box-title"><h4>(.*?)</h4>', after[:800], re.S)
            if t: alt = f"{name} – {strip(t.group(1))}" if name else strip(t.group(1))
        # 4) Öne çıkan görsel (yazı/uygulama başı): sayfa adı
        if not alt and re.search(r'cspt-featured-wrapper"?>\s*(<a[^>]*>)?\s*$', before):
            alt = name
        # 5) Diğer (galeri, içerik görseli): sayfa adı + dosya adından model/konu
        if not alt:
            n = humanize(title_attr or src, lang)
            # Dosya adı sayfa adıyla başlıyorsa tekrarı at: "Push pull system solution welding ..." -> "welding ..."
            if n and name:
                nw, pw = n.lower().split(), re.sub(r"[^\w\s]", " ", name.lower()).split()
                k = 0
                while k < len(nw) and k < len(pw) and nw[k] == pw[k]:
                    k += 1
                if k >= 2:
                    n = " ".join(n.split()[k:])
            if lang == "tr" and n and not re.search(r"\d", n):
                # Türkçe sayfada İngilizce dosya adı eklenmez; model kodu yoksa sayfa türüne göre Türkçe ifade
                n = "uygulama fotoğrafı" if path.startswith("/tr/uygulama-tr/") else \
                    "ürün görseli" if path.startswith(("/tr/urun/", "/tr/urun-kategorisi/")) else ""
            if n and name and n.lower() not in name.lower():
                alt = f"{name} – {n}"
            else:
                alt = name or n
        if not alt:
            continue
        new = re.sub(r'\salt="[^"]*"', "", tag)
        new = new.replace("<img", f'<img alt="{esc_attr(alt)}"', 1)
        out.append(body[pos:im.start()]); out.append(new); pos = im.end()
    out.append(body[pos:])
    return h[:a] + "".join(out) + h[b:]


# ---------------------------------------------------------------- form ayarları

def extract_forms(html_by_path: dict) -> dict:
    forms = {}
    for path, h in html_by_path.items():
        for fm in re.finditer(r'<form[^>]*class="wpforms-validate wpforms-form"[^>]*data-formid="(\d+)".*?</form>', h, re.S):
            fid, body = fm.group(1), fm.group(0)
            if fid in forms:
                continue
            fields = {}
            for c in re.finditer(r'<div id="wpforms-\d+-field_(\d+)-container" class="wpforms-field wpforms-field-(\w+)[^"]*"[^>]*>(.*?)(?=<div id="wpforms-\d+-field_\d+-container"|</div><!-- \.wpforms-field-container -->)', body, re.S):
                num, typ, inner = c.groups()
                lab = re.search(r'<label class="wpforms-field-label"[^>]*>(.*?)</label>', inner, re.S)
                if lab:
                    label = re.sub(r"<span class=\"wpforms-required-label\">.*?</span>", "", lab.group(1))
                else:
                    il = re.search(r'<label class="wpforms-field-label-inline"[^>]*>(.*?)</label>', inner, re.S)
                    label = il.group(1) if il else f"Alan {num}"
                label = re.sub(r"<[^>]+>", "", label).strip()
                if typ == "checkbox":
                    label = "Privacy Policy / Gizlilik onayı"
                fields[num] = {"etiket": label, "tip": "email" if typ == "email" else typ,
                               "zorunlu": "wpforms-field-required" in inner}
            title = re.search(r'name="page_title" value="([^"]*)"', body)
            tr = lang_of(path) == "tr"
            forms[fid] = {
                "ad": (title.group(1) if title else "Form") + f" ({'TR' if tr else 'EN'})",
                "sayfa": path,
                "alanlar": fields,
                "basari": "Formunuz için teşekkür ederiz. En kısa sürede sizinle iletişime geçeceğiz." if tr
                          else "Thanks for contacting us! We will be in touch with you shortly.",
                "hata": "Gönderim sırasında bir sorun oluştu. Lütfen zorunlu alanları kontrol edip tekrar deneyin." if tr
                        else "There was a problem submitting the form. Please check the required fields and try again.",
            }
    return forms


def php_export(v, ind=0):
    sp = "    " * ind
    if isinstance(v, dict):
        items = [f"{sp}    {php_export(str(k))} => {php_export(x, ind + 1)}," for k, x in v.items()]
        return "[\n" + "\n".join(items) + f"\n{sp}]"
    if isinstance(v, bool):
        return "true" if v else "false"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


# ---------------------------------------------------------------- eksik dosyalar

REF_RE = re.compile(r"""(?:src|href|data-lazy-src|data-src|data-bg|data-lazyload|data-thumb|poster|content)=["'](/[^"'<>]+?)["']"""
                    r"""|url\(\s*["']?(/[^"')]+?)["']?\s*\)"""
                    r"""|(?:srcset|data-lazy-srcset)=["']([^"']+)["']""")


def collect_refs(text: str) -> set:
    refs = set()
    for m in REF_RE.finditer(text):
        if m.group(3):
            for part in m.group(3).split(","):
                u = part.strip().split(" ")[0]
                if u.startswith("/"):
                    refs.add(u)
        else:
            refs.add(m.group(1) or m.group(2))
    clean = set()
    for u in refs:
        u = u.split("#")[0].split("?")[0]
        if u.startswith("//") or not re.search(r"\." + ASSET_EXT + r"$", u, re.I):
            continue
        clean.add(u)
    return clean


def css_relative_refs(css_path: Path, text: str) -> set:
    """CSS içindeki göreli url(...) adreslerini site köküne göre çözer."""
    refs = set()
    base = "/" + str(css_path.relative_to(OUT).parent).replace(os.sep, "/") + "/"
    for m in re.finditer(r"url\(\s*[\"']?([^\"')]+?)[\"']?\s*\)", text):
        u = m.group(1).split("#")[0].split("?")[0]
        if u.startswith(("data:", "http", "//", "/")) or not u:
            continue
        refs.add(urllib.parse.urljoin(base, u))
    return refs


def fetch(url_path: str, src: Path) -> bool:
    """Eksik dosyayı kaynak siteden önce raw/ içine indirir (sonraki build'lerde kalıcı olsun), sonra site/'a kopyalar."""
    rel = urllib.parse.unquote(url_path).lstrip("/")
    disk, raw = OUT / rel, src / rel
    if disk.exists():
        return True
    if not raw.exists():
        raw.parent.mkdir(parents=True, exist_ok=True)
        q = urllib.parse.quote(urllib.parse.unquote(url_path), safe="/%-._~")
        ok = False
        for base in (SRC_URL, FALLBACK_URL):   # demo'da yoksa canlı siteden
            r = subprocess.run(["curl", "-sS", "-f", "-L", "--max-time", "120", "-o", str(raw), base + q],
                               stderr=subprocess.DEVNULL)
            if r.returncode == 0:
                ok = True
                break
        if not ok:
            raw.unlink(missing_ok=True)
            return False
    disk.parent.mkdir(parents=True, exist_ok=True)
    if raw.suffix == ".css":
        disk.write_text(process_css(raw.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
    else:
        shutil.copy2(raw, disk)
    return True


# ---------------------------------------------------------------- ana akış

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    src = Path(sys.argv[1]).resolve()
    do_fetch = "--fetch" in sys.argv

    # 1) çıktı klasörünü temizle (bizim dosyalarımız hariç)
    OUT.mkdir(exist_ok=True)
    for p in OUT.iterdir():
        if p.name in KEEP:
            continue
        shutil.rmtree(p) if p.is_dir() else p.unlink()

    for old in (OUT / "assets").glob("bundle-*.css"):
        old.unlink()

    # 1b) WebP kopyaları (raw içinde bir kez üretilir, sonra kopyalanır): görsel.jpg -> görsel.jpg.webp
    make_webp(src)

    # 2) sayfa listesi
    redirects = {}
    rfile = ROOT / "tools" / "redirects.json"
    if rfile.exists():
        redirects = json.loads(rfile.read_text(encoding="utf-8"))
    # SEO kararıyla eklenen yönlendirmeler (orijinalde canonical ile ana sayfayı gösteren kopya arşiv sayfaları)
    sfile = ROOT / "tools" / "redirects-seo.json"
    if sfile.exists():
        redirects.update(json.loads(sfile.read_text(encoding="utf-8")))
    REDIRECTS.update(redirects)
    html_files = [p for p in src.rglob("index.html") if "?" not in str(p) and "wp-content" not in p.parts
                  and page_path(p.relative_to(src)) not in redirects]
    pages = {page_path(p.relative_to(src)) for p in html_files}

    # .htaccess yönlendirme bölümü
    ht = OUT / ".htaccess"
    if ht.exists():
        lines = "\n".join(
            f"RewriteRule ^{re.escape(k.strip('/'))}/?$ {v} [L,R=301]" for k, v in sorted(redirects.items()))
        t = ht.read_text(encoding="utf-8")
        t = re.sub(r"(# YONLENDIRMELER-BASLA\n).*?(# YONLENDIRMELER-BITIR)", lambda m: m.group(1) + lines + "\n" + m.group(2), t, flags=re.S)
        ht.write_text(t, encoding="utf-8")

    # 3) dosyaları kopyala/işle — önce tüm dosyalar (CSS paketleme için hazır olsunlar), sonra sayfalar
    html_by_path = {}
    page_files = []
    for f in src.rglob("*"):
        if f.is_dir():
            continue
        rel = str(f.relative_to(src))
        if "index.html?" in rel or "/feed" in rel or rel.startswith("wp-json"):
            continue
        clean_rel = re.sub(r"\?.*$", "", rel)
        if clean_rel.endswith(".webp") and f.stat().st_size == 0:
            continue
        if clean_rel.endswith(".xml"):
            continue
        if f.name == "index.html":
            if page_path(f.relative_to(src)) not in redirects:
                page_files.append((f, clean_rel))
            continue
        dest = OUT / clean_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if clean_rel.endswith(".css"):
            dest.write_text(process_css(f.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
        else:
            shutil.copy2(f, dest)
    for f, clean_rel in page_files:
        dest = OUT / clean_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        path = page_path(f.relative_to(src))
        h = process_html(f.read_text(encoding="utf-8", errors="replace"), path, pages)
        html_by_path[path] = h
        dest.write_text(h, encoding="utf-8")

    # 4) ek sayfalar (404, arama) — tools/extra/ içinden
    extra = ROOT / "tools" / "extra"
    if extra.exists():
        for f in extra.rglob("*.html"):
            rel = f.relative_to(extra)
            path = page_path(rel) if f.name == "index.html" else "/" + str(rel)
            h = process_html(f.read_text(encoding="utf-8", errors="replace"), path, pages)
            if str(rel) == "404.html":
                # Sunucu tüm 404'lerde bu sayfayı gösterir; Türkçe adreslerde Türkçe 404'e geç
                h = h.replace("<head>", '<head>\n<script>if(/^\\/tr(\\/|$)/.test(location.pathname))location.replace("/tr/404.html");</script>', 1)
            dest = OUT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(h, encoding="utf-8")

    # 4a) eski adresler için yönlendirme sayfaları (sunucuda .htaccess 301 önce çalışır;
    #     bu sayfalar yerel önizlemede ve .htaccess'in çalışmadığı durumda devreye girer)
    for src_path, dst in redirects.items():
        dst = final_url(dst, pages)
        d = OUT / src_path.strip("/") / "index.html"
        if d.exists():
            continue
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_text(
            '<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<meta name="robots" content="noindex, follow">'
            f'<link rel="canonical" href="{SITE}{dst}">'
            f'<meta http-equiv="refresh" content="0; url={dst}">'
            f'<script>location.replace("{dst}"+location.search+location.hash)</script>'
            f'</head><body><a href="{dst}">{SITE}{dst}</a></body></html>\n', encoding="utf-8")

    # 4b) site haritaları (orijinal Yoast haritaları, alan adı değiştirilerek)
    for f in (ROOT / "tools" / "sitemaps").glob("*.xml"):
        x = f.read_text(encoding="utf-8")
        x = re.sub(r"<\?xml-stylesheet[^>]*\?>", "", x)
        # yönlendirilen (artık var olmayan) adresleri haritadan çıkar
        x = re.sub(r"<url>\s*<loc>(?:https?:)?//(?:www\.)?demo\.seowpclub\.com([^<]*)</loc>.*?</url>\s*",
                   lambda m: "" if m.group(1) in redirects else m.group(0), x, flags=re.S)
        (OUT / f.name).write_text(to_abs(x), encoding="utf-8")

    # 5) form ayarları
    forms = extract_forms(html_by_path)
    (OUT / "form-ayarlar.php").write_text(
        "<?php\n// build.py tarafından üretilir — elle düzenleme (başarı/hata metinleri hariç)\nreturn "
        + php_export(forms) + ";\n", encoding="utf-8")

    # 5b) arama dizini
    index = []
    for path, h in sorted(html_by_path.items()):
        if "/page/" in path:
            continue
        t = re.search(r"<title>(.*?)</title>", h, re.S)
        title = re.sub(r"\s*[|\-–]\s*Vanterm\s*$", "", t.group(1).strip()) if t else path
        title = html_unescape(title)
        m = re.search(r'<main[^>]*>(.*?)</main>', h, re.S)
        body = m.group(1) if m else ""
        body = re.sub(r"<(script|style|form)[^>]*>.*?</\1>", " ", body, flags=re.S)
        text = re.sub(r"\s+", " ", html_unescape(re.sub(r"<[^>]+>", " ", body))).strip()
        d = re.search(r'<meta name="description" content="([^"]*)"', h)
        exc = html_unescape(d.group(1)) if d else text[:160]
        img = re.search(r'<meta property="og:image" content="([^"]+)"', h)
        img = img.group(1).replace(SITE, "") if img else ""
        index.append({"u": path, "l": lang_of(path), "t": title, "e": exc[:200], "i": img, "x": text[:4000]})
    (OUT / "search-index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # 5b2) Sayfa başına kritik CSS: sayfanın kullandığı kurallar engelleyici, tam CSS arkadan (aynı sonuç)
    critical_css(html_by_path)
    # artık hiçbir sayfanın bağlamadığı ara paketleri sil
    used = set()
    for hp in OUT.rglob("*.html"):
        used.update(re.findall(r"/assets/(bundle-[0-9a-f]+\.css)", hp.read_text(encoding="utf-8", errors="ignore")))
    for old in (OUT / "assets").glob("bundle-*.css"):
        if old.name not in used:
            old.unlink()

    # 5c) yapay zeka arama motorları için site özeti
    write_llms(html_by_path)

    # 6) eksik dosyaları bul / indir
    missing = set()
    for _ in range(3):
        refs = set()
        for f in OUT.rglob("*"):
            if f.suffix in (".html", ".css", ".js"):
                t = f.read_text(encoding="utf-8", errors="replace")
                refs |= collect_refs(t)
                if f.suffix == ".css":
                    refs |= css_relative_refs(f, t)
        missing = {u for u in refs if not (OUT / urllib.parse.unquote(u).lstrip("/")).exists()}
        if not do_fetch or not missing:
            break
        print(f"indiriliyor: {len(missing)} dosya")
        for u in sorted(missing):
            fetch(u, src)
    missing = {u for u in missing if not (OUT / urllib.parse.unquote(u).lstrip("/")).exists()}

    report = {"sayfa": len(pages), "form": {k: v["ad"] for k, v in forms.items()}, "eksik": sorted(missing)}
    (ROOT / "tools" / "build-rapor.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"sayfa: {len(pages)}  form: {len(forms)}  eksik dosya: {len(missing)}")


if __name__ == "__main__":
    main()
