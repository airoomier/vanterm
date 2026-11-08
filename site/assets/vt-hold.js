/* Betikler defer ile yüklenirken jQuery "ready" olayını, tüm eklenti dosyaları (owl, flexslider...) yüklenene kadar beklet. */
if (window.jQuery && jQuery.holdReady) {
  jQuery.holdReady(true);
  document.addEventListener('DOMContentLoaded', function () { jQuery.holdReady(false); });
}
