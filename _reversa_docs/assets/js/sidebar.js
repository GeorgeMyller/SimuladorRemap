// Controles com data-param: persistem em localStorage e emitem o evento "rv:param".
(function () {
  var page = document.body.getAttribute("data-page-id") || "page";
  document.querySelectorAll("[data-param]").forEach(function (el) {
    var key = "rv." + page + "." + el.dataset.param;
    try {
      var saved = localStorage.getItem(key);
      if (saved !== null) {
        if (el.type === "checkbox") el.checked = saved === "1";
        else if (el.type === "range") { var v = parseFloat(saved); if (v >= +el.min && v <= +el.max) el.value = v; }
        else el.value = saved;
      }
    } catch (e) { /* mantém o padrão */ }
    var emit = function () {
      var val = el.type === "checkbox" ? el.checked : (el.type === "range" ? parseFloat(el.value) : el.value);
      try { localStorage.setItem(key, el.type === "checkbox" ? (el.checked ? "1" : "0") : String(el.value)); } catch (e) {}
      var out = document.querySelector('[data-out="' + el.dataset.param + '"]');
      if (out) out.textContent = el.value;
      document.dispatchEvent(new CustomEvent("rv:param", { detail: { param: el.dataset.param, value: val } }));
    };
    el.addEventListener("input", emit);
    el.addEventListener("change", emit);
    var out = document.querySelector('[data-out="' + el.dataset.param + '"]');
    if (out) out.textContent = el.value;
  });
  window.RV_PARAM = function (name, fallback) {
    var el = document.querySelector('[data-param="' + name + '"]');
    if (!el) return fallback;
    return el.type === "checkbox" ? el.checked : (el.type === "range" ? parseFloat(el.value) : el.value);
  };
})();
