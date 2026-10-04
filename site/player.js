// Shared by the DREAM Robotics sites: a small music player. Any
// <div class="player" data-tracks='[{"title":"...","src":"..."}]'> becomes
// one: play/pause, previous/next, a seek bar, and the track list. Plays the
// next track when one ends.
(function () {
  function fmt(s) {
    if (!isFinite(s)) return "0:00";
    s = Math.floor(s);
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }

  document.querySelectorAll(".player[data-tracks]").forEach(function (box) {
    var tracks = JSON.parse(box.getAttribute("data-tracks"));
    if (!tracks.length) return;
    var audio = new Audio();
    audio.preload = "none";
    var i = 0;

    box.innerHTML =
      '<div class="pl-now"><button class="pl-btn pl-prev" aria-label="Previous">&#9198;</button>' +
      '<button class="pl-btn pl-play" aria-label="Play">&#9654;</button>' +
      '<button class="pl-btn pl-next" aria-label="Next">&#9197;</button>' +
      '<div class="pl-info"><div class="pl-title"></div>' +
      '<div class="pl-bar"><span class="pl-time">0:00</span><input class="pl-seek" type="range" min="0" max="1000" value="0" aria-label="Seek">' +
      '<span class="pl-dur">0:00</span></div></div></div><ol class="pl-list"></ol>';
    var play = box.querySelector(".pl-play"), title = box.querySelector(".pl-title");
    var seek = box.querySelector(".pl-seek"), time = box.querySelector(".pl-time"), dur = box.querySelector(".pl-dur");
    var list = box.querySelector(".pl-list");

    tracks.forEach(function (t, n) {
      var li = document.createElement("li");
      var b = document.createElement("button");
      b.textContent = t.title;
      b.addEventListener("click", function () { load(n); audio.play(); });
      li.appendChild(b);
      list.appendChild(li);
    });

    function load(n) {
      i = (n + tracks.length) % tracks.length;
      audio.src = tracks[i].src;
      title.textContent = tracks[i].title;
      list.querySelectorAll("li").forEach(function (li, k) { li.classList.toggle("on", k === i); });
    }

    play.addEventListener("click", function () { audio.paused ? audio.play() : audio.pause(); });
    box.querySelector(".pl-prev").addEventListener("click", function () { load(i - 1); audio.play(); });
    box.querySelector(".pl-next").addEventListener("click", function () { load(i + 1); audio.play(); });
    audio.addEventListener("play", function () { play.innerHTML = "&#10074;&#10074;"; play.setAttribute("aria-label", "Pause"); });
    audio.addEventListener("pause", function () { play.innerHTML = "&#9654;"; play.setAttribute("aria-label", "Play"); });
    audio.addEventListener("ended", function () { load(i + 1); audio.play(); });
    audio.addEventListener("timeupdate", function () {
      time.textContent = fmt(audio.currentTime);
      dur.textContent = fmt(audio.duration);
      if (audio.duration) seek.value = Math.round(audio.currentTime / audio.duration * 1000);
    });
    seek.addEventListener("input", function () {
      if (audio.duration) audio.currentTime = seek.value / 1000 * audio.duration;
    });
    load(0);
  });
})();
