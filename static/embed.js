/**
 * embed.js — встраивание чат-виджета на любой сайт (демо-стенд).
 *
 * Использование:
 *   <script src="https://<host>/embed.js"
 *           data-accent="a6613a"      /* акцентный цвет без решётки */
 *           data-origin="https://kashtanka64.ru" /* необязательно: baseUrl виджета */
 *           defer></script>
 *
 * Скрипт создаёт плавающую кнопку и iframe с чатом (/widget).
 * Тот же эффект без скрипта — прямой iframe:
 *   <iframe src="https://<host>/widget"></iframe>
 */
(function () {
  var script = document.currentScript;
  var origin = (script && script.dataset.origin) || "";
  var accent = (script && script.dataset.accent) || "a6613a";

  var css = document.createElement("style");
  css.textContent = [
    ".vetai-fab{position:fixed;right:20px;bottom:20px;width:52px;height:52px;border:none;",
    "border-radius:50%;background:#" + accent + ";color:#fff;cursor:pointer;",
    "box-shadow:0 2px 8px rgba(31,35,40,.25);z-index:99998;transition:transform .15s;",
    "display:grid;place-items:center}",
    ".vetai-fab:hover{transform:scale(1.05)}",
    ".vetai-fab svg{width:24px;height:24px}",
    ".vetai-frame{position:fixed;right:20px;bottom:84px;width:380px;max-width:calc(100vw - 32px);",
    "height:560px;max-height:calc(100vh - 120px);border:1px solid #d0d7de;border-radius:12px;",
    "box-shadow:0 8px 24px rgba(31,35,40,.18);background:#fff;z-index:99999;display:none;overflow:hidden}",
    ".vetai-frame.open{display:block}",
    "@media (max-width:480px){.vetai-frame{right:8px;bottom:80px;width:calc(100vw - 16px);height:calc(100vh - 96px)}}"
  ].join("");
  document.head.appendChild(css);

  var frame = document.createElement("iframe");
  frame.className = "vetai-frame";
  frame.src = origin + "/widget?accent=" + encodeURIComponent(accent);
  frame.setAttribute("title", "Чат ветеринарной клиники");
  document.body.appendChild(frame);

  var fab = document.createElement("button");
  fab.className = "vetai-fab";
  fab.setAttribute("aria-label", "Открыть чат с клиникой");
  fab.innerHTML =
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
    '<ellipse cx="12" cy="15.5" rx="4.6" ry="3.8"/>' +
    '<circle cx="5.6" cy="10.2" r="2.1"/>' +
    '<circle cx="9.9" cy="7.4" r="2.1"/>' +
    '<circle cx="14.1" cy="7.4" r="2.1"/>' +
    '<circle cx="18.4" cy="10.2" r="2.1"/>' +
    "</svg>";
  fab.addEventListener("click", function () {
    frame.classList.toggle("open");
  });
  document.body.appendChild(fab);
})();
