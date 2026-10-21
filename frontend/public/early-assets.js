// Starts the logo and the big-heading font early, but only on pages that use them,
// so the browser never warns about a preload nobody used. Loaded async from index.html.
(function () {
  var path = location.pathname.replace(/\/+$/, "") || "/";
  function preload(href, as, type) {
    var l = document.createElement("link");
    l.rel = "preload";
    l.as = as;
    l.href = href;
    if (type) l.type = type;
    if (as === "font") l.crossOrigin = "anonymous";
    document.head.appendChild(l);
  }
  // Every page shows the logo except a patient chart.
  if (!/\/clinician\/patient\//.test(path)) preload("/solace-logo.png", "image", "image/png");
  // Fraunces (Latin) is only used for the headings on the public pages and the QR card.
  if (/^\/(how-it-works|ai-disclosure|stress-test)?$/.test(path) || /^\/[^/]+\/qr$/.test(path)) {
    preload(
      "https://fonts.gstatic.com/s/fraunces/v38/6NU78FyLNQOQZAnv9bYEvDiIdE9Ea92uemAk_WBq8U_9v0c2Wa0KxC9TeP2Xz5c.woff2",
      "font",
      "font/woff2",
    );
  }
})();
