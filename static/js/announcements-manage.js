/* Shared: create + list announcements (coordinator JWT / faculty session). */
(function () {
  function buildHeaders(useJwt) {
    var h = {};
    if (useJwt) {
      var t = localStorage.getItem("campuslink_token");
      if (t) h.Authorization = "Bearer " + t;
    }
    return h;
  }

  function fetchManage(useJwt) {
    return fetch("/api/announcements/manage", {
      credentials: "same-origin",
      headers: buildHeaders(useJwt),
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) throw new Error((data && data.error) || "Failed to load");
        return data;
      });
    });
  }

  function postAnnouncement(useJwt, formData) {
    return fetch("/api/announcements", {
      method: "POST",
      credentials: "same-origin",
      headers: buildHeaders(useJwt),
      body: formData,
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) throw new Error((data && data.error) || "Failed to post");
        return data;
      });
    });
  }

  function audienceLabel(keys) {
    var map = { student: "Student", faculty: "Faculty", alumni: "Alumni" };
    return (keys || []).map(function (k) {
      return map[k] || k;
    }).join(", ");
  }

  function renderList(container, items, statusEl) {
    container.innerHTML = "";
    if (statusEl) statusEl.textContent = "";
    if (!items || !items.length) {
      container.innerHTML = "<div class=\"cl-state\">No announcements posted yet.</div>";
      return;
    }
    items.forEach(function (a) {
      var card = document.createElement("div");
      card.className = "cl-ann-list-card";
      var title = document.createElement("div");
      title.className = "cl-ann-list-title";
      title.textContent = a.title || "—";
      var short = (a.description || a.body || "").trim();
      if (short.length > 160) short = short.slice(0, 157) + "…";
      var desc = document.createElement("div");
      desc.className = "cl-ann-list-desc";
      desc.textContent = short || "—";
      var meta = document.createElement("div");
      meta.className = "cl-ann-list-meta";
      var aud = audienceLabel(a.audience);
      var when = a.created_at ? new Date(a.created_at).toLocaleString() : "";
      meta.textContent = [aud && "Audience: " + aud, when].filter(Boolean).join(" · ");
      card.appendChild(title);
      card.appendChild(desc);
      if (meta.textContent) card.appendChild(meta);
      container.appendChild(card);
    });
  }

  function render(root, opts) {
    opts = opts || {};
    var useJwt = !!opts.useJwt;
    root.innerHTML = "";

    var head = document.createElement("div");
    head.className = "cl-page-head";
    head.innerHTML = "<div><h1>Announcements</h1><p>Create targeted announcements and review everything that has been posted.</p></div>";

    var wrap = document.createElement("div");
    wrap.className = "cl-announcements-split";

    var left = document.createElement("div");
    left.className = "cl-card cl-ann-form";
    left.innerHTML =
      "<h2 class=\"cl-ann-section-title\">Create announcement</h2>" +
      "<form id=\"clAnnForm\" novalidate>" +
      "<div class=\"cl-field\"><label for=\"clAnnTitle\">Title</label><input id=\"clAnnTitle\" name=\"title\" type=\"text\" required maxlength=\"200\" class=\"cl-input\" placeholder=\"Title\" /></div>" +
      "<div class=\"cl-field\"><label for=\"clAnnDesc\">Description</label><textarea id=\"clAnnDesc\" name=\"description\" required rows=\"5\" class=\"cl-input cl-textarea\" placeholder=\"Description\"></textarea></div>" +
      "<div class=\"cl-field\"><span class=\"cl-label\">Audience</span>" +
      "<div class=\"cl-audience-row\"><label class=\"cl-check\"><input type=\"checkbox\" name=\"aud_student\" value=\"student\" /> Student</label>" +
      "<label class=\"cl-check\"><input type=\"checkbox\" name=\"aud_faculty\" value=\"faculty\" /> Faculty</label>" +
      "<label class=\"cl-check\"><input type=\"checkbox\" name=\"aud_alumni\" value=\"alumni\" /> Alumni</label></div></div>" +
      "<div class=\"cl-field\"><label for=\"clAnnMedia\">Media (optional)</label>" +
      "<input id=\"clAnnMedia\" name=\"media\" type=\"file\" multiple class=\"cl-input\" " +
      "accept=\"image/*,video/mp4,video/webm,video/quicktime,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.zip,.txt\" />" +
      "<p class=\"cl-field-hint\">Select multiple files: images, video (MP4/WebM/MOV), PDF, or common documents. Max 15 files.</p></div>" +
      "<div class=\"cl-form-actions\"><button type=\"submit\" class=\"cl-btn primary\" id=\"clAnnSubmit\">Post announcement</button></div>" +
      "<p class=\"cl-form-error\" id=\"clAnnErr\" role=\"alert\"></p>" +
      "</form>";

    var right = document.createElement("div");
    right.className = "cl-card cl-ann-list-wrap";
    right.innerHTML =
      "<h2 class=\"cl-ann-section-title\">All posted announcements</h2>" +
      "<p class=\"cl-ann-list-status\" id=\"clAnnListStatus\"></p>" +
      "<div id=\"clAnnList\"></div>";

    wrap.appendChild(left);
    wrap.appendChild(right);
    root.appendChild(head);
    root.appendChild(wrap);

    var listEl = root.querySelector("#clAnnList");
    var statusEl = root.querySelector("#clAnnListStatus");
    var errEl = root.querySelector("#clAnnErr");
    var form = root.querySelector("#clAnnForm");

    function reloadList() {
      statusEl.textContent = "Loading…";
      fetchManage(useJwt)
        .then(function (data) {
          renderList(listEl, data.items || [], statusEl);
        })
        .catch(function () {
          statusEl.textContent = "";
          listEl.innerHTML = "<div class=\"cl-state cl-error\">Could not load announcements.</div>";
        });
    }

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      errEl.textContent = "";
      var title = (root.querySelector("#clAnnTitle").value || "").trim();
      var description = (root.querySelector("#clAnnDesc").value || "").trim();
      var boxes = root.querySelectorAll(".cl-audience-row input[type=\"checkbox\"]:checked");
      var aud = [];
      boxes.forEach(function (b) {
        aud.push(b.value);
      });
      if (!title) {
        errEl.textContent = "Title is required.";
        return;
      }
      if (!description) {
        errEl.textContent = "Description is required.";
        return;
      }
      if (!aud.length) {
        errEl.textContent = "Select at least one audience.";
        return;
      }
      var fd = new FormData();
      fd.append("title", title);
      fd.append("description", description);
      aud.forEach(function (a) {
        fd.append("audience", a);
      });
      var fileInput = root.querySelector("#clAnnMedia");
      if (fileInput && fileInput.files && fileInput.files.length) {
        for (var i = 0; i < fileInput.files.length; i++) {
          fd.append("media", fileInput.files[i]);
        }
      }
      var btn = root.querySelector("#clAnnSubmit");
      btn.disabled = true;
      postAnnouncement(useJwt, fd)
        .then(function () {
          form.reset();
          reloadList();
        })
        .catch(function (err) {
          errEl.textContent = (err && err.message) || "Failed to post.";
        })
        .finally(function () {
          btn.disabled = false;
        });
    });

    reloadList();
  }

  window.CampusLinkAnnouncementsManage = { render: render };
})();
