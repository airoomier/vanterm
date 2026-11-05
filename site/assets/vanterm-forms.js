/* Vanterm: WPForms formlarını statik sitede form-gonder.php'ye gönderir. */
(function () {
  function init() {
    document.querySelectorAll('form.wpforms-form').forEach(function (form) {
      form.setAttribute('action', '/form-gonder.php');
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        if (!form.checkValidity()) { form.reportValidity(); return; }
        var btn = form.querySelector('.wpforms-submit');
        var txt = btn ? btn.textContent : '';
        if (btn) { btn.disabled = true; btn.textContent = btn.getAttribute('data-alt-text') || txt; }
        var old = form.querySelector('.wpforms-error-container');
        if (old) old.remove();
        var data = new FormData(form);
        data.set('page_url', location.pathname);
        fetch('/form-gonder.php', {
          method: 'POST', body: data,
          headers: { 'Accept': 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
        }).then(function (r) { return r.json(); }).then(function (res) {
          if (res.ok) {
            var box = document.createElement('div');
            box.className = 'wpforms-confirmation-container-full wpforms-confirmation-scroll';
            box.setAttribute('role', 'alert');
            box.innerHTML = '<p></p>';
            box.firstChild.textContent = res.message;
            var wrap = form.closest('.wpforms-container') || form;
            wrap.innerHTML = '';
            wrap.appendChild(box);
            box.scrollIntoView({ behavior: 'smooth', block: 'center' });
          } else { throw new Error(res.message); }
        }).catch(function (err) {
          var box = document.createElement('div');
          box.className = 'wpforms-error-container';
          box.setAttribute('role', 'alert');
          box.textContent = (err && err.message) || 'Error';
          form.insertBefore(box, form.firstChild);
          if (btn) { btn.disabled = false; btn.textContent = txt; }
        });
      });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
