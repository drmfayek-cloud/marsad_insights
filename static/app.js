// MARSAD Insights - small behaviours only: filter auto-submit, mobile menu, confirmations.
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("select[data-auto]").forEach(function (s) {
    s.addEventListener("change", function () { s.form.submit(); });
  });
  var btn = document.querySelector("[data-menu]");
  var side = document.getElementById("side");
  if (btn && side) {
    btn.addEventListener("click", function () { side.classList.toggle("open"); });
  }
  document.querySelectorAll("[data-confirm]").forEach(function (b) {
    b.addEventListener("click", function (e) {
      if (!window.confirm(b.getAttribute("data-confirm"))) { e.preventDefault(); }
    });
  });
});
