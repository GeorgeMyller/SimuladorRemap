// Marca a página atual no nav e avisa se os dados embutidos não carregaram.
(function () {
  var id = document.body.getAttribute("data-page-id");
  document.querySelectorAll(".reversa-doc-nav a").forEach(function (a) {
    var pid = a.getAttribute("data-page-id");
    if (pid === id || (id && id.indexOf("feature-") === 0 && pid === "features")) a.setAttribute("aria-current", "page");
  });
  if (!window.RV_DATA) {
    var p = document.createElement("div");
    p.className = "reversa-error-panel";
    p.textContent = "Os dados do mini-site (assets/js/data.js) não foram encontrados. Rode /reversa-docs-publisher novamente.";
    var m = document.getElementById("main");
    if (m) m.insertBefore(p, m.firstChild);
  }
})();
