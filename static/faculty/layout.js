window.FacultyLayout = (function () {
  var NAV = [
    { key: "students", label: "My Students" },
    { key: "announcements", label: "📢 Announcements" },
    { key: "verification", label: "Student Verification Requests" },
    { key: "interview", label: "Interview" },
    { key: "applications", label: "Department Applications" },
    { key: "help", label: "Help Messages" },
  ];
  function routeFromHash() {
    var raw = (window.location.hash || "").replace(/^#\/?/, "").trim();
    return raw || "students";
  }
  function setActive(key) {
    document.querySelectorAll("[data-faculty-nav]").forEach(function (a) {
      a.setAttribute("aria-current", a.getAttribute("data-faculty-nav") === key ? "page" : "false");
    });
  }
  function render(opts) {
    opts = opts || {};
    var shell = document.createElement("div");
    shell.className = "cl-shell";
    var sidebar = document.createElement("aside");
    sidebar.className = "cl-sidebar";
    var brand = document.createElement("a");
    brand.className = "cl-brand";
    brand.href = "#/students";
    brand.innerHTML = "<img src=\"/images/logo.png\" alt=\"CampusLink\" /><div><div class=\"cl-brand-title\">CampusLink</div><div class=\"cl-brand-sub\">Faculty</div></div>";
    var nav = document.createElement("nav");
    nav.className = "cl-nav";
    NAV.forEach(function (item) {
      var a = document.createElement("a");
      a.href = (item.external && item.href) ? item.href : "#/" + item.key;
      a.textContent = item.label;
      a.setAttribute("data-faculty-nav", item.key);
      if (item.openInNewTab) a.setAttribute("target", "_blank"); else if (item.external) a.setAttribute("target", "_self");
      nav.appendChild(a);
    });
    sidebar.appendChild(brand);
    sidebar.appendChild(nav);
    var main = document.createElement("div");
    main.className = "cl-main";
    main.innerHTML =
      "<header class=\"cl-topbar\">" +
      "<div class=\"cl-topbar-title\">Faculty Dashboard</div>" +
      "<div class=\"cl-topbar-right\">" +
      "<button class=\"cl-btn\" type=\"button\" data-campuslink-sos-open>🆘 Raise Issue / Help</button>" +
      "<div class=\"nav-notification-wrapper\">" +
      "<div class=\"nav-notification\" onclick=\"CampusLinkNavNotifications.toggle()\" aria-label=\"Notifications\" role=\"button\" tabindex=\"0\">" +
      "<span>🔔</span>" +
      "<span class=\"nav-notification-badge\" id=\"notification-badge\" style=\"display:none\">0</span>" +
      "</div>" +
      "<div class=\"notification-dropdown\" id=\"notificationDropdown\">" +
      "<div class=\"notification-header\">" +
      "<h3>Notifications</h3>" +
      "<button type=\"button\" onclick=\"CampusLinkNavNotifications.markAllRead()\">Mark all as read</button>" +
      "</div>" +
      "<div class=\"notification-list\" id=\"notificationList\">" +
      "<div class=\"notification-empty\"><div class=\"notification-empty-icon\">🔔</div><p>No notifications yet</p></div>" +
      "</div></div></div>" +
      "<span class=\"cl-chip\">" +
      (opts.userName || "Faculty") +
      "</span>" +
      "<button class=\"cl-btn danger\" type=\"button\" id=\"facultyLogout\">Sign out</button>" +
      "</div></header><main class=\"cl-content\" id=\"facultyContent\"></main>";
    main.querySelector("#facultyLogout").onclick = function () {
      if (window.CampusLinkAuthSync && window.CampusLinkAuthSync.logoutEverywhere) {
        window.CampusLinkAuthSync.logoutEverywhere();
      } else {
        window.location.href = "/logout";
      }
    };
    shell.appendChild(sidebar);
    shell.appendChild(main);
    setActive(routeFromHash());
    return shell;
  }
  return { render: render, setActive: setActive, routeFromHash: routeFromHash };
})();
