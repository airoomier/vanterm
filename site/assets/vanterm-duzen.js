/* Vanterm: ikonlu kutuları aynı satırda eşit yüksekliğe getirir.
   - Sütunda tek kutu varsa (+ boşluk öğeleri): sütuna .vt-esit, satırına .vt-esit-satir eklenir; eşitlemeyi CSS yapar.
   - Sütunda alt alta birden fazla kutu varsa: aynı satırdaki sütunlarda 1., 2., ... kutular kendi aralarında
     eşitlenir (min-height). Pencere boyutu değişince yeniden hesaplanır.
   Başlık/metin içeren sütunlara dokunulmaz. */
(function () {
  var multiRows = [];

  function isBoxOnly(w) {
    var kids = Array.prototype.slice.call(w.children);
    if (!kids.length) return null;
    var boxes = kids.filter(function (k) { return k.classList.contains('cspt-ihbox'); });
    var ok = kids.every(function (k) {
      return k.classList.contains('cspt-ihbox') || k.classList.contains('vc_empty_space');
    });
    if (!ok || !boxes.length) return null;
    if (boxes.some(function (b) { return b.classList.contains('cspt-ihbox-style-hsbox'); })) return null;
    return boxes;
  }

  function mark() {
    var rows = new Map();
    document.querySelectorAll('.wpb_column > .vc_column-inner > .wpb_wrapper').forEach(function (w) {
      var boxes = isBoxOnly(w);
      if (!boxes) return;
      var col = w.parentElement.parentElement, row = col.parentElement;
      if (boxes.length === 1) {
        col.classList.add('vt-esit');
        if (row) row.classList.add('vt-esit-satir');
      } else if (row) {
        boxes.forEach(function (b) { b.classList.add('vt-esit-kutu'); });
        if (!rows.has(row)) rows.set(row, []);
        rows.get(row).push(boxes);
      }
    });
    rows.forEach(function (cols) { if (cols.length > 1) multiRows.push(cols); });
    equalize();
  }

  function equalize() {
    multiRows.forEach(function (cols) {
      var n = Math.max.apply(null, cols.map(function (c) { return c.length; }));
      for (var i = 0; i < n; i++) {
        var set = cols.map(function (c) { return c[i]; }).filter(Boolean);
        set.forEach(function (b) { b.style.minHeight = ''; });
        // Yan yana değilse (mobilde alt alta) eşitleme yapma
        var tops = set.map(function (b) { return Math.round(b.getBoundingClientRect().top); });
        var sideBySide = set.length > 1 && set[0].getBoundingClientRect().left !== set[1].getBoundingClientRect().left;
        if (!sideBySide) continue;
        var max = Math.max.apply(null, set.map(function (b) { return b.getBoundingClientRect().height; }));
        set.forEach(function (b) { b.style.minHeight = Math.ceil(max) + 'px'; });
      }
    });
  }

  var t;
  window.addEventListener('resize', function () { clearTimeout(t); t = setTimeout(equalize, 150); });
  window.addEventListener('load', equalize);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(equalize);
  function year() {
    var y = String(new Date().getFullYear());
    document.querySelectorAll('.vt-yil').forEach(function (e) { e.textContent = y; });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { mark(); year(); });
  else { mark(); year(); }
})();
