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
    h = strip_qs(h)
    h = resolve_links(h, pages)

    # Arama formu: statik arama sayfası
    h = re.sub(r'(<form[^>]*class="search-form"[^>]*action=")/(")', r"\1/search/\2", h)
    h = re.sub(r'(<form[^>]*class="search-form"[^>]*action=")/tr/(")', r"\1/tr/search/\2", h)
    h = re.sub(r'(<form[^>]*action=")/("[^>]*class="search-form")', r"\1/search/\2", h)
    h = re.sub(r'(<form[^>]*action=")/tr/("[^>]*class="search-form")', r"\1/tr/search/\2", h)

    # Yazı kutularındaki "0 Comment" satırı
    h = re.sub(r'\s*<div class="cspt-meta-date-wrapper cspt-meta-line">\s*<i class="cspt-base-icon-comment-empty"></i>.*?</div>',
               "", h, flags=re.S)

    # Düzen standardı CSS'i (tema CSS'lerinden sonra)
    if "vanterm-duzen.css" not in h and "</head>" in h:
        h = h.replace("</head>", '<link rel="stylesheet" href="/assets/vanterm-duzen.css" media="all" />\n</head>', 1)

    # Formlar
    if "wpforms-form" in h:
        h = remove_wpforms_scripts(h)
        if "vanterm-forms.js" not in h:
            h = h.replace("</body>", '<script src="/assets/vanterm-forms.js" defer></script>\n</body>', 1)
    return h


def process_css(s: str) -> str:
    return strip_qs(to_rel(s))


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

    # 2) sayfa listesi
    redirects = {}
    rfile = ROOT / "tools" / "redirects.json"
    if rfile.exists():
        redirects = json.loads(rfile.read_text(encoding="utf-8"))
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

    # 3) dosyaları kopyala/işle
    html_by_path = {}
    for f in src.rglob("*"):
        if f.is_dir():
            continue
        rel = str(f.relative_to(src))
        if "index.html?" in rel or "/feed" in rel or rel.startswith("wp-json"):
            continue
        clean_rel = re.sub(r"\?.*$", "", rel)
        if clean_rel.endswith(".xml"):
            continue
        if f.name == "index.html" and page_path(f.relative_to(src)) in redirects:
            continue
        dest = OUT / clean_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if f.name == "index.html":
            path = page_path(f.relative_to(src))
            h = process_html(f.read_text(encoding="utf-8", errors="replace"), path, pages)
            html_by_path[path] = h
            dest.write_text(h, encoding="utf-8")
        elif clean_rel.endswith(".css"):
            dest.write_text(process_css(f.read_text(encoding="utf-8", errors="replace")), encoding="utf-8")
        else:
            shutil.copy2(f, dest)

    # 4) ek sayfalar (404, arama) — tools/extra/ içinden
    extra = ROOT / "tools" / "extra"
    if extra.exists():
        for f in extra.rglob("*.html"):
            rel = f.relative_to(extra)
            path = page_path(rel) if f.name == "index.html" else "/" + str(rel)
            h = process_html(f.read_text(encoding="utf-8", errors="replace"), path, pages)
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
