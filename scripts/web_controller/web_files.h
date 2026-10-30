// Made by embed_web.py from web/: edit those, not this.
#pragma once

static const char WEB_CONNECT_CSS[] = R"WEBFILE(html, body { height: 100%; margin: 0; }
body { display: flex; align-items: center; justify-content: center; background: {{BACKGROUND}}; color: {{TEXT}}; font-family: "Segoe UI", system-ui, sans-serif; }
main { width: 340px; padding: 28px; background: {{PANEL}}; border: 1px solid {{BORDER}}; border-radius: 8px; text-align: center; }
h1 { margin: 0 0 6px; color: {{ACCENT}}; letter-spacing: 2px; }
p { margin: 0 0 18px; min-height: 1.3em; opacity: 0.8; }
form { display: flex; gap: 8px; margin-bottom: 8px; }
input { flex: 1; min-width: 0; padding: 10px; background: {{BACKGROUND}}; color: {{TEXT}}; border: 1px solid {{BORDER}}; border-radius: 6px; font: inherit; }
button { padding: 10px 16px; background: {{ACCENT}}; color: {{PANEL}}; border: 0; border-radius: 6px; font: inherit; font-weight: 600; cursor: pointer; }
#find { width: 100%; background: transparent; color: {{ACCENT}}; border: 1px solid {{BORDER}}; }
)WEBFILE";

static const char WEB_CONNECT_HTML[] = R"WEBFILE(<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{NAME}}</title>
<style>{{CSS}}</style>
</head>
<body>
<main>
  <h1>{{NAME}}</h1>
  <p id="note">{{NOTE}}</p>
  <form id="go">
    <input id="host" value="{{HOST}}" placeholder="address" spellcheck="false" autofocus>
    <button>CONNECT</button>
  </form>
  <button id="find" type="button">FIND</button>
</main>
<script>{{JS}}</script>
</body>
</html>
)WEBFILE";

static const char WEB_CONNECT_JS[] = R"WEBFILE(// Shown only when there's no robot to show: it tells the window where to go.
(function () {
  var note = document.getElementById("note");
  document.getElementById("go").addEventListener("submit", function (e) {
    e.preventDefault();
    var host = document.getElementById("host").value.trim();
    if (host) {
      note.textContent = "Connecting...";
      chrome.webview.postMessage("go:" + host);
    }
  });
  document.getElementById("find").addEventListener("click", function () {
    note.textContent = "Looking...";
    chrome.webview.postMessage("find");
  });
})();
)WEBFILE";

