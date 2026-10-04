// Shared by every DREAM Robotics site: highlights the nav link for the section
// on screen, and fills in the missing path on the 404 page.
(function () {
  var links = {};
  document.querySelectorAll('nav ul a[href^="#"]').forEach(function (a) {
    links[a.getAttribute("href").slice(1)] = a;
  });
  var ids = Object.keys(links);
  if ("IntersectionObserver" in window && ids.length) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        ids.forEach(function (id) { links[id].classList.toggle("active", id === entry.target.id); });
      });
    }, { rootMargin: "-40% 0px -55% 0px" });
    ids.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) observer.observe(el);
    });
  }

  var missing = document.getElementById("missing-path");
  if (missing) missing.textContent = window.location.pathname;
})();
