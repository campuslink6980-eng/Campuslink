/* Render announcement media (images, video, PDF, other files) from API payload. */
(function () {
  function inferType(url) {
    var u = (url || "").toLowerCase();
    if (/\.(mp4|webm|mov)(\?|$)/i.test(u) || u.indexOf("/video/upload/") !== -1) return "video";
    if (/\.pdf(\?|$)/i.test(u) || u.indexOf("/raw/upload/") !== -1 || u.indexOf("/raw/") !== -1) return "pdf";
    return "image";
  }

  function appendItems(parent, n) {
    var items = n.media;
    if (!items || !items.length) {
      var u = n.media_url;
      if (u) items = [{ url: u, type: inferType(u) }];
    }
    if (!items || !items.length) return;
    var stack = document.createElement("div");
    stack.className = "announcement-media-stack";
    items.forEach(function (m) {
      var url = m.url;
      if (!url) return;
      var t = (m.type || inferType(url)).toLowerCase();
      if (t === "video") {
        var v = document.createElement("video");
        v.controls = true;
        v.preload = "metadata";
        v.playsInline = true;
        v.className = "announcement-media-video";
        v.src = url;
        stack.appendChild(v);
      } else if (t === "pdf" || t === "file") {
        var a = document.createElement("a");
        a.href = url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        a.className = "announcement-media-link";
        a.textContent = t === "pdf" ? "View PDF" : "Download attachment";
        stack.appendChild(a);
      } else {
        var img = document.createElement("img");
        img.src = url;
        img.alt = "";
        img.className = "announcement-media-img";
        img.loading = "lazy";
        stack.appendChild(img);
      }
    });
    parent.appendChild(stack);
  }

  window.CampusLinkAnnouncementMediaUI = { appendItems: appendItems, inferType: inferType };
})();
