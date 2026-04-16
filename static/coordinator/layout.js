/* Reusable CoordinatorLayout */

window.CoordinatorLayout = (() => {
  const NAV_ITEMS = [
    { key: "overview", label: "Overview" },
    { key: "announcements", label: "📢 Announcements" },
    { key: "alumni-approval", label: "Alumni Approval Requests" },
    { key: "job-posts", label: "Job Posts" },
    { key: "interview", label: "Interview" },
    { key: "applications", label: "Applications" },
    { key: "reports", label: "Reports / Analytics" },
    { key: "settings", label: "Settings" },
  ];

  function routeFromHash() {
    const raw = (window.location.hash || "").replace(/^#\/?/, "").trim();
    return raw || "overview";
  }

  function setActiveNav(activeKey) {
    const links = document.querySelectorAll("[data-cl-nav]");
    links.forEach((a) => {
      const key = a.getAttribute("data-cl-nav");
      if (key === activeKey) {
        a.setAttribute("aria-current", "page");
      } else {
        a.removeAttribute("aria-current");
      }
    });
  }

  function render({ userName }) {
    const shell = document.createElement("div");
    shell.className = "cl-shell";

    const sidebar = document.createElement("aside");
    sidebar.className = "cl-sidebar";

    const brand = document.createElement("a");
    brand.className = "cl-brand";
    brand.href = "#/overview";
    brand.innerHTML = `
      <img src="/images/logo.png" alt="CampusLink logo" />
      <div>
        <div class="cl-brand-title">CampusLink</div>
        <div class="cl-brand-sub">Coordinator Console</div>
      </div>
    `;

    const nav = document.createElement("nav");
    nav.className = "cl-nav";
    NAV_ITEMS.forEach((item) => {
      const a = document.createElement("a");
      a.href = item.href || `#/${item.key}`;
      a.textContent = item.label;
      a.setAttribute("data-cl-nav", item.key);
      nav.appendChild(a);
    });

    sidebar.appendChild(brand);
    sidebar.appendChild(nav);

    const main = document.createElement("div");
    main.className = "cl-main";

    const topbar = document.createElement("header");
    topbar.className = "cl-topbar";
    topbar.innerHTML = `
      <div class="cl-topbar-title">Placement Coordinator</div>
      <div class="cl-topbar-right">
        <button class="cl-btn" type="button" data-campuslink-sos-open>🆘 Raise Issue / Help</button>
        <div class="nav-notification-wrapper">
          <div class="nav-notification" onclick="CampusLinkNavNotifications.toggle()" aria-label="Notifications" role="button" tabindex="0">
            <span>🔔</span>
            <span class="nav-notification-badge" id="notification-badge" style="display:none">0</span>
          </div>
          <div class="notification-dropdown" id="notificationDropdown">
            <div class="notification-header">
              <h3>Notifications</h3>
              <button type="button" onclick="CampusLinkNavNotifications.markAllRead()">Mark all as read</button>
            </div>
            <div class="notification-list" id="notificationList">
              <div class="notification-empty">
                <div class="notification-empty-icon">🔔</div>
                <p>No notifications yet</p>
              </div>
            </div>
          </div>
        </div>
        <div class="cl-chip" id="clUserChip">${userName ? userName : "Coordinator"}</div>
        <button class="cl-btn danger" id="clLogoutBtn" type="button">Sign out</button>
      </div>
    `;

    const content = document.createElement("main");
    content.className = "cl-content";
    content.id = "clContent";

    main.appendChild(topbar);
    main.appendChild(content);

    shell.appendChild(sidebar);
    shell.appendChild(main);

    // Events
    topbar.querySelector("#clLogoutBtn").addEventListener("click", () => {
      if (window.CampusLinkAuthSync && window.CampusLinkAuthSync.logoutEverywhere) {
        window.CampusLinkAuthSync.logoutEverywhere();
      } else {
        window.location.href = "/logout";
      }
    });

    // Initialize active state
    setActiveNav(routeFromHash());

    return shell;
  }

  return {
    render,
    setActiveNav,
    routeFromHash,
  };
})();

