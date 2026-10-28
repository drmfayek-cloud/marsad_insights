// MARSAD Insights - small behaviours only: filter auto-submit, closing header menus, confirmations.
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("select[data-auto]").forEach(function (s) {
    s.addEventListener("change", function () { s.form.submit(); });
  });
  var pops = document.querySelectorAll("details.menu-pop");
  document.addEventListener("click", function (e) {
    pops.forEach(function (d) { if (!d.contains(e.target)) { d.removeAttribute("open"); } });
  });
  document.querySelectorAll("[data-confirm]").forEach(function (b) {
    b.addEventListener("click", function (e) {
      if (!window.confirm(b.getAttribute("data-confirm"))) { e.preventDefault(); }
    });
  });
});
