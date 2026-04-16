/* Alumni shell — same navbar layout as student dashboard (search left, links right). */

window.AlumniLayout = (function () {
  function routeFromHash() {
    var raw = (window.location.hash || "").replace(/^#\/?/, "").trim();
    return raw || "home";
  }

  function setActiveNav(activeKey) {
    document.querySelectorAll(".nav-link[data-alumni-nav]").forEach(function (a) {
      if (activeKey && a.getAttribute("data-alumni-nav") === activeKey) {
        a.classList.add("active");
      } else {
        a.classList.remove("active");
      }
    });
  }

  /**
   * Top nav + mobile bottom bar active states from hash route key (e.g. home, jobs, dashboard, profile).
   */
  function syncNavForHashRoute(routeKey) {
    var key = routeKey || "home";
    var topKey = "";
    if (key === "home") topKey = "home";
    else if (key === "dashboard" || key === "overview") topKey = "dashboard";
    else if (key === "jobs") topKey = "job";
    else if (key === "network") topKey = "";
    else if (key === "messages") topKey = "messages";
    setActiveNav(topKey);

    var bottomKey = null;
    if (key === "home") bottomKey = "home";
    else if (key === "jobs") bottomKey = "job";
    else if (key === "dashboard" || key === "overview") bottomKey = "dashboard";
    else if (key === "profile" || key === "edit-profile") bottomKey = "profile";

    document.querySelectorAll(".cl-alumni-bottom-nav a[data-alumni-bottom]").forEach(function (a) {
      var k = a.getAttribute("data-alumni-bottom");
      a.classList.toggle("cl-bottom-nav--active", !!(bottomKey && k === bottomKey));
    });
  }

  function startAnnouncementTicker() {
    var inner = document.getElementById("cl-alumni-announcement-ticker-inner");
    if (!inner) return;

    function esc(s) {
      return String(s || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    fetch("/api/dashboard/important-notices", { credentials: "same-origin" })
      .then(function (res) {
        return res.ok ? res.json() : Promise.reject();
      })
      .then(function (data) {
        var items = (data && data.items) || [];
        if (!items.length) {
          inner.classList.add("cl-announcement-ticker-inner--static");
          inner.innerHTML =
            "<span class=\"cl-announcement-ticker-msg--empty\">📢 No announcements right now · tap for details</span>";
          return;
        }
        inner.classList.remove("cl-announcement-ticker-inner--static");
        var parts = items.slice(0, 12).map(function (n) {
          return "📢 " + esc((n.title || "Announcement").trim());
        });
        var line = parts.join("&nbsp;&nbsp;|&nbsp;&nbsp;");
        inner.innerHTML =
          "<span class=\"ticker-seg\">" + line + "</span><span class=\"ticker-seg\" aria-hidden=\"true\">" + line + "</span>";
      })
      .catch(function () {
        inner.classList.add("cl-announcement-ticker-inner--static");
        inner.innerHTML =
          "<span class=\"cl-announcement-ticker-msg--empty\">📢 Campus announcements · tap to open</span>";
      });
  }

  function refreshNotifBadge() {
    if (window.AlumniNav) window.AlumniNav.loadNotifications();
  }

  function render(opts) {
    opts = opts || {};
    var userName = opts.userName || "Alumni";

    var shell = document.createElement("div");
    shell.className = "alumni-app-shell";

    var nav = document.createElement("header");
    nav.className = "nav";
    nav.innerHTML =
      "<div class=\"nav-left\">" +
        "<a href=\"#/home\" class=\"nav-logo\" aria-label=\"CampusLink home\">" +
          "<img src=\"/images/logo.png\" alt=\"CampusLink logo\">" +
        "</a>" +
        "<div class=\"nav-search-wrapper\">" +
          "<div class=\"nav-search\">" +
            "<span>🔍</span>" +
            "<input id=\"search-input\" type=\"text\" placeholder=\"Search jobs, companies, students\" aria-label=\"Search\" autocomplete=\"off\" />" +
          "</div>" +
          "<div class=\"search-results\" id=\"search-results\"></div>" +
        "</div>" +
      "</div>" +
      "<div class=\"nav-right\">" +
        "<span class=\"nav-stats\" id=\"navConnectionsMentor\">Connections: — | Mentees: —</span>" +
        "<nav class=\"nav-links\" role=\"navigation\" aria-label=\"Main navigation\">" +
          "<a class=\"nav-link\" href=\"#/home\" data-alumni-nav=\"home\" aria-label=\"Home\">" +
            "<span class=\"nav-link-icon\">🏠</span><span class=\"nav-link-text\">Home</span></a>" +
          "<a class=\"nav-link\" href=\"#/jobs\" data-alumni-nav=\"job\" aria-label=\"Your job postings\">" +
            "<span class=\"nav-link-icon\">💼</span><span class=\"nav-link-text\">Job</span></a>" +
          "<a class=\"nav-link\" href=\"#/dashboard\" data-alumni-nav=\"dashboard\" aria-label=\"Dashboard\">" +
            "<span class=\"nav-link-icon\">📊</span><span class=\"nav-link-text\">Dashboard</span></a>" +
          "<a class=\"nav-link\" href=\"/interviews\" target=\"_blank\" rel=\"noopener\" data-alumni-nav=\"interview\" aria-label=\"Interview\">" +
            "<span class=\"nav-link-icon\">📝</span><span class=\"nav-link-text\">Interview</span></a>" +
          "<a class=\"nav-link\" href=\"#\" data-campuslink-sos-open data-alumni-nav=\"sos\" aria-label=\"SOS support\">" +
            "<span class=\"nav-link-icon\">🆘</span><span class=\"nav-link-text\">SOS</span></a>" +
          "<a class=\"nav-link\" href=\"/messages\" data-alumni-nav=\"messages\" aria-label=\"Message\">" +
            "<span class=\"nav-link-icon\">💬</span><span class=\"nav-link-text\">Message</span></a>" +
        "</nav>" +
        "<div class=\"nav-notification-wrapper\">" +
          "<div class=\"nav-notification\" aria-label=\"Notification\" role=\"button\" tabindex=\"0\">" +
            "<span>🔔</span>" +
            "<span class=\"nav-notification-badge\" id=\"notification-badge\" style=\"display: none;\">0</span>" +
          "</div>" +
          "<div class=\"notification-dropdown\" id=\"notificationDropdown\">" +
            "<div class=\"notification-header\">" +
              "<h3>Notifications</h3>" +
              "<button type=\"button\" id=\"alumniMarkAllNotif\">Mark all as read</button>" +
            "</div>" +
            "<div class=\"notification-list\" id=\"notificationList\">" +
              "<div class=\"notification-empty\"><div class=\"notification-empty-icon\">🔔</div><p>No notifications yet</p></div>" +
            "</div>" +
          "</div>" +
        "</div>" +
        "<a href=\"/messages\" class=\"cl-alumni-mobile-msg\" aria-label=\"Messages\">💬</a>" +
        "<div class=\"li-profile-wrapper\">" +
          "<div class=\"li-avatar\" role=\"button\" aria-label=\"Profile menu\" aria-expanded=\"false\" tabindex=\"0\">" +
            "<span>Me</span>" +
          "</div>" +
          "<div class=\"li-dropdown\" id=\"liDropdown\" role=\"menu\">" +
            "<div class=\"li-user-info\">" +
              "<div class=\"li-user-avatar\"></div>" +
              "<div>" +
                "<p class=\"li-name\">Your Name</p>" +
                "<p class=\"li-role\">Alumni · CampusLink</p>" +
              "</div>" +
            "</div>" +
            "<a href=\"#/profile\" class=\"li-btn\" role=\"menuitem\">View Profile</a>" +
            "<div class=\"li-divider\"></div>" +
            "<a href=\"#/edit-profile\" class=\"li-link\" role=\"menuitem\">Edit Profile</a>" +
            "<a href=\"#/settings\" class=\"li-link\" role=\"menuitem\">Settings</a>" +
            "<a href=\"#\" class=\"li-link\" id=\"alumniSignOut\" role=\"menuitem\">Sign out</a>" +
          "</div>" +
        "</div>" +
      "</div>";

    var main = document.createElement("div");
    main.id = "clContent";
    main.className = "alumni-main";

    shell.appendChild(nav);

    var ticker = document.createElement("a");
    ticker.href = "/announcements";
    ticker.target = "_blank";
    ticker.rel = "noopener";
    ticker.className = "cl-announcement-ticker cl-alumni-announcement-ticker";
    ticker.setAttribute("aria-label", "Announcements — open full list");
    ticker.innerHTML =
      "<div class=\"cl-announcement-ticker-inner cl-announcement-ticker-inner--static\" id=\"cl-alumni-announcement-ticker-inner\">" +
      "<span class=\"cl-announcement-ticker-msg--empty\">📢 Loading campus announcements…</span>" +
      "</div>";
    shell.appendChild(ticker);

    shell.appendChild(main);

    var bottomNav = document.createElement("nav");
    bottomNav.className = "cl-bottom-nav cl-alumni-bottom-nav";
    bottomNav.setAttribute("aria-label", "Primary mobile navigation");
    bottomNav.innerHTML =
      "<a href=\"#/home\" data-alumni-bottom=\"home\" data-alumni-nav=\"home\"><span>🏠</span><span>Home</span></a>" +
      "<a href=\"#/jobs\" data-alumni-bottom=\"job\" data-alumni-nav=\"job\"><span>💼</span><span>Jobs</span></a>" +
      "<a href=\"#/dashboard\" data-alumni-bottom=\"dashboard\" data-alumni-nav=\"dashboard\"><span>📊</span><span>Dashboard</span></a>" +
      "<a href=\"/interviews\" target=\"_blank\" rel=\"noopener\"><span>🎤</span><span>Interview</span></a>" +
      "<a href=\"#/profile\" data-alumni-bottom=\"profile\" data-alumni-nav=\"profile\"><span>👤</span><span>Profile</span></a>";
    shell.appendChild(bottomNav);

    setTimeout(function () {
      if (window.AlumniNav) window.AlumniNav.init(userName);
      startAnnouncementTicker();
    }, 0);

    return shell;
  }

  return {
    render: render,
    setActiveNav: setActiveNav,
    syncNavForHashRoute: syncNavForHashRoute,
    startAnnouncementTicker: startAnnouncementTicker,
    routeFromHash: routeFromHash,
    refreshNotifBadge: refreshNotifBadge,
  };
})();
