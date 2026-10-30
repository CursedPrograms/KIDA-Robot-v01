// Shown only when there's no robot to show: it tells the window where to go.
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
