/* Vanterm statik arama: /search-index.json içinde arar, sonuçları temanın orijinal biçiminde gösterir. */
(function () {
  var box = document.getElementById('vt-search');
  if (!box) return;
  var lang = box.getAttribute('data-lang');
  var more = box.getAttribute('data-more');
  var q = (new URLSearchParams(location.search).get('s') || '').trim();

  document.title = document.title.replace('%q%', q);
  document.querySelectorAll('.cspt-tbar-search-word, .vt-q').forEach(function (el) { el.textContent = q; });
  document.querySelectorAll('input.search-field').forEach(function (el) { el.value = q; });

  function norm(s) {
    return (s || '').toLocaleLowerCase(lang === 'tr' ? 'tr' : 'en')
      .normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/ı/g, 'i');
  }
  function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
  function none() { document.getElementById('vt-search-none').style.display = ''; }

  if (!q) { none(); return; }
  fetch('/search-index.json').then(function (r) { return r.json(); }).then(function (items) {
    var terms = norm(q).split(/\s+/).filter(Boolean);
    var hits = items.filter(function (it) {
      if (it.l !== lang) return false;
      var hay = norm(it.t + ' ' + it.x);
      return terms.every(function (t) { return hay.indexOf(t) !== -1; });
    }).map(function (it) {
      var tt = norm(it.t), score = 0;
      terms.forEach(function (t) { if (tt.indexOf(t) !== -1) score += 10; });
      return { it: it, s: score };
    }).sort(function (a, b) { return b.s - a.s; });

    if (!hits.length) { none(); return; }
    box.innerHTML = hits.map(function (h) {
      var it = h.it;
      var img = it.i ? '<div class="cspt-search-results-inner cspt-search-results-left"><div class="cspt-featured-wrapper"><a href="' + it.u + '"><img width="300" height="300" src="' + it.i + '" alt="" loading="lazy" /></a></div></div>' : '';
      return '<article class="container"><div class="cspt-search-results">' + img +
        '<div class="cspt-search-results-right"><h3 class="cspt-post-title"><a href="' + it.u + '">' + esc(it.t) + '</a></h3>' +
        '<div class="cspt-entry-content">' + esc(it.e) + '&hellip;<div class="cspt-read-more-link"><a href="' + it.u + '">' + more + '</a></div></div></div></div></article>';
    }).join('') + '<div class="clearfix"></div>';
  }).catch(none);
})();
