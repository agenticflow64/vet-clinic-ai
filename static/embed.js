/**
 * embed.js — встраивание чат-виджета на любой сайт (демо-стенд).
 *
 * Использование:
 *   <script src="https://<host>/embed.js"
 *           data-theme="light"        /* light | dark */
 *           data-accent="c2563a"      /* акцентный цвет без решётки */
 *           data-origin="https://kashtanka64.ru" /* необязательно: baseUrl виджета */
 *           defer></script>
 *
 * Скрипт создаёт плавающую кнопку и iframe с чатом (/widget).
 * Тот же эффект без скрипта — прямой iframe:
 *   <iframe src="https://<host>/widget?theme=light&accent=c2563a"></iframe>
 */
(function () {
  var script = document.currentScript;
  var origin = (script && script.dataset.origin) || "";
  var theme = (script && script.dataset.theme) || "light";
  var accent = (script && script.dataset.accent) || "c2563a";

  var css = document.createElement("style");
  css.textContent = [
    ".vetai-fab{position:fixed;right:20px;bottom:20px;width:56px;height:56px;border:none;",
    "border-radius:50%;background:#" + accent + ";color:#fff;font-size:24px;cursor:pointer;",
    "box-shadow:0 4px 16px rgba(0,0,0,.25);z-index:99998;transition:transform .15s}",
    ".vetai-fab:hover{transform:scale(1.07)}",
    ".vetai-frame{position:fixed;right:20px;bottom:88px;width:380px;max-width:calc(100vw - 32px);",
    "height:560px;max-height:calc(100vh - 120px);border:1px solid rgba(0,0,0,.12);border-radius:16px;",
    "box-shadow:0 12px 40px rgba(0,0,0,.28);background:#fff;z-index:99999;display:none;overflow:hidden}",
    ".vetai-frame.open{display:block}",
    "@media (max-width:480px){.vetai-frame{right:8px;bottom:84px;width:calc(100vw - 16px);height:calc(100vh - 100px)}}"
  ].join("");
  document.head.appendChild(css);

  var frame = document.createElement("iframe");
  frame.className = "vetai-frame";
  frame.src = origin + "/widget?theme=" + encodeURIComponent(theme) + "&accent=" + encodeURIComponent(accent);
  frame.setAttribute("title", "AI-ассистент ветеринарной клиники");
  document.body.appendChild(frame);

  var fab = document.createElement("button");
  fab.className = "vetai-fab";
  fab.setAttribute("aria-label", "Открыть чат с ассистентом");
  fab.textContent = "🐾";
  fab.addEventListener("click", function () {
    frame.classList.toggle("open");
  });
  document.body.appendChild(fab);
})();
