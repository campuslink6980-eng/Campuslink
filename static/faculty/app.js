(function () {
  var mount = document.getElementById("app");
  if (!mount) return;
  fetch("/api/auth/me", { credentials: "same-origin" })
    .then(function (r) { return r.ok ? r.json() : Promise.reject({ status: r.status }); })
    .then(function (me) {
      var role = (me.role || "").toLowerCase();
      if (role !== "faculty") {
        window.location.href = "/main";
        return;
      }
      mount.innerHTML = "";
      mount.appendChild(window.FacultyLayout.render({ userName: me.name || me.email }));
      if (window.CampusLinkNavNotifications) {
        CampusLinkNavNotifications.init({ announcementUrl: "/faculty/dashboard#/announcements" });
      }
      var root = document.getElementById("facultyContent");
      function renderRoute() {
        var key = window.FacultyLayout.routeFromHash();
        window.FacultyLayout.setActive(key);
        if (key === "announcements") {
          window.FacultyPages.Announcements.render(root);
          return;
        }
        if (key === "students" || key === "verification") {
          window.FacultyPages.Students.render(root, key);
          return;
        }
        if (key === "interview") {
          window.FacultyPages.Interview.render(root);
          return;
        }
        if (key === "applications") {
          window.FacultyPages.Applications.render(root);
          return;
        }
        if (key === "help") {
          window.FacultyPages.Help.render(root);
          return;
        }
        root.innerHTML = "<div class=\"cl-page-head\"><h1>" + key + "</h1></div><div class=\"cl-state\">No content.</div>";
      }
      window.addEventListener("hashchange", renderRoute);
      renderRoute();
    })
    .catch(function () { window.location.href = "/login"; });
})();
