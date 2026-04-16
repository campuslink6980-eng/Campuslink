window.FacultyPages = window.FacultyPages || {};

window.FacultyPages.Interview = (function () {
  function esc(v) {
    return String(v || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function cardHtml(d) {
    return (
      '<article class="cl-card" style="padding:14px; border-radius:14px; cursor:pointer;" data-drive-id="' +
      esc(d.id) +
      '">' +
      '<div style="font-weight:800; font-size:16px; color:#1d2226;">' +
      esc(d.company || "Company") +
      "</div>" +
      '<div style="font-size:13px; color:#6b7280; margin-top:4px;">' +
      esc(d.role || "Role") +
      "</div>" +
      "</article>"
    );
  }

  async function render(root) {
    root.innerHTML =
      '<div class="cl-page-head"><div><h1>Interview</h1><p>Browse interview drives and open details.</p></div></div>' +
      '<div id="facultyInterviewList" style="display:grid; gap:12px;"></div>';
    var host = document.getElementById("facultyInterviewList");
    if (!host) return;
    host.innerHTML = '<div class="cl-state">Loading interview drives...</div>';
    try {
      var res = await fetch("/api/interview/drives", { credentials: "same-origin" });
      if (res.status === 401) {
        window.location.href = "/login";
        return;
      }
      var data = await res.json();
      var drives = (data && data.drives) || [];
      if (!drives.length) {
        host.innerHTML = '<div class="cl-state">No interview drives found.</div>';
        return;
      }
      host.innerHTML = '<div class="cl-grid">' + drives.map(cardHtml).join("") + "</div>";
      host.querySelectorAll("[data-drive-id]").forEach(function (el) {
        el.addEventListener("click", function () {
          var id = el.getAttribute("data-drive-id");
          if (id) window.location.href = "/interview-drive/" + encodeURIComponent(id);
        });
      });
    } catch (_) {
      host.innerHTML = '<div class="cl-state cl-error">Unable to load interview drives.</div>';
    }
  }

  return { render: render };
})();
