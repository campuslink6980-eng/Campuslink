window.FacultyPages = window.FacultyPages || {};
window.FacultyPages.Applications = (function () {
  function esc(s) { return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  async function render(root) {
    root.innerHTML = "<div class=\"cl-page-head\"><div><h1>Department Applications</h1><p>Job applications by students in your department.</p></div></div><div class=\"cl-state\" id=\"facultyAppState\">Loading…</div><div id=\"facultyAppList\" style=\"display:none;\"></div>";
    var stateEl = document.getElementById("facultyAppState");
    var listEl = document.getElementById("facultyAppList");
    try {
      var data = await window.FacultyApi.listApplications();
      var apps = (data && data.applications) || [];
      stateEl.style.display = "none";
      listEl.style.display = "block";
      if (!apps.length) {
        listEl.innerHTML = "<div class=\"cl-state\">No applications from your department yet.</div>";
        return;
      }
      var rows = apps.map(function (a) {
        return "<tr><td>" + esc(a.student_name) + "</td><td>" + esc(a.company) + "</td><td>" + esc(a.role) + "</td><td><span class=\"cl-badge\">" + esc(a.status) + "</span></td><td>" + esc(a.applied_at ? new Date(a.applied_at).toLocaleDateString() : "") + "</td></tr>";
      }).join("");
      listEl.innerHTML = "<table class=\"cl-table\"><thead><tr><th>Student</th><th>Company</th><th>Role</th><th>Status</th><th>Applied</th></tr></thead><tbody>" + rows + "</tbody></table>";
    } catch (e) {
      stateEl.textContent = (e && e.message) || "Failed to load.";
      stateEl.classList.add("cl-error");
    }
  }
  return { render: render };
})();
