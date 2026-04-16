/* Coordinator dashboard bootstrap + routing */

(async function bootstrap() {
  const mount = document.getElementById("app");
  if (!mount) return;

  // Enforce JWT + coordinator role
  let me;
  try {
    me = await window.CampusLinkApi.me();
  } catch (e) {
    // Unauthorized -> login, Forbidden -> main
    if (e && e.status === 403) {
      window.location.href = "/main";
      return;
    }
    window.location.href = "/login";
    return;
  }

  if (!me || (me.role || "").toLowerCase() !== "coordinator") {
    window.location.href = "/main";
    return;
  }

  mount.innerHTML = "";
  mount.appendChild(window.CoordinatorLayout.render({ userName: me.name || me.email }));
  if (window.CampusLinkNavNotifications) {
    CampusLinkNavNotifications.init({ announcementUrl: "/coordinator/dashboard#/announcements" });
  }

  async function renderRoute() {
    const key = window.CoordinatorLayout.routeFromHash();
    window.CoordinatorLayout.setActiveNav(key);
    const root = document.getElementById("clContent");
    if (!root) return;

    if (key === "overview") {
      await window.CoordinatorPages.Overview.render(root);
      return;
    }

    if (key === "announcements") {
      window.CoordinatorPages.Announcements.render(root);
      return;
    }

    if (key === "student-verification") {
      window.location.hash = "#/overview";
      return;
    }

    if (key === "job-posts") {
      await window.CoordinatorPages.Jobs.render(root);
      return;
    }

    if (key === "interview") {
      await window.CoordinatorPages.Interview.render(root);
      return;
    }

    if (key === "applications") {
      await window.CoordinatorPages.Applications.render(root);
      return;
    }

    if (key === "alumni-approval") {
      await window.CoordinatorPages.AlumniApproval.render(root);
      return;
    }

    // Placeholder view: honest empty state, no fake rows/stats.
    root.innerHTML = `
      <div class="cl-page-head">
        <div>
          <h1>${key.replace(/-/g, " ").replace(/\b\w/g, (m) => m.toUpperCase())}</h1>
          <p>This module will render backend data once its APIs are available.</p>
        </div>
      </div>
      <div class="cl-state">No data loaded for this section yet.</div>
    `;
  }

  window.addEventListener("hashchange", renderRoute);
  await renderRoute();
})();

