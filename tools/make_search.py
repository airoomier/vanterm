#!/usr/bin/env python3
"""Orijinal WordPress arama sonuç sayfalarından statik arama şablonu üretir.
Kullanım: python3 tools/make_search.py <sonuclu.html> <sonucsuz.html> <kelime> <cikti.html> <en|tr>
"""
import re
import sys

res, none, word, out, lang = sys.argv[1:6]
h = open(res, encoding="utf-8").read()
n = open(none, encoding="utf-8").read()
w = re.escape(word)

h = re.sub(r"(<title>)You searched for " + w + r"( \| Vanterm</title>)", r"\1You searched for %q%\2", h)
h = re.sub(r'(class="search-field"[^>]*value=")' + w + '"', r'\1"', h)
h = re.sub(r'(<span class="cspt-tbar-search-word">)' + w + "(</span>)", r"\1\2", h)
h = re.sub(r"&#039;" + w + "&#039;", "&#039;<span class=\"vt-q\"></span>&#039;", h)

h = re.sub(r'<script type="application/ld\+json"[^>]*>.*?</script>\s*', "", h, flags=re.S)
h = re.sub(r'(href="[^"]*?)/tr/\?s=' + w + '"', r'\1/tr/search/"', h)
h = re.sub(r'(href="[^"]*?\.com)/\?s=' + w + '"', r'\1/search/"', h)

# Sonuç listesi + sayfalama yerine boş kapsayıcı
i = h.find("<article")
j = h.find("</main>")
none_block = n[n.find('<div class="search-no-results-content">'):]
none_block = none_block[:none_block.find("</form>") + len("</form>")] + "\n\t\t</div>"
none_block = re.sub(r'(class="search-field"[^>]*value=")zzqqxx"', r'\1"', none_block)
more = "Devamı" if lang == "tr" else "Read More"
h = (h[:i]
     + f'<div id="vt-search" data-lang="{lang}" data-more="{more}"></div>\n'
     + f'<div id="vt-search-none" style="display:none">{none_block}</div>\n'
     + "<script src=\"/assets/vanterm-search.js\" defer></script>\n\t"
     + h[j:])
open(out, "w", encoding="utf-8").write(h)
print("ok", out)
