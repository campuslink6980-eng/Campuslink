/* Alumni dashboard bootstrap + hash routing */

(function () {
  var mount = document.getElementById("app");
  if (!mount) return;

  function goLogin() {
    window.location.href = "/login";
  }
  function goMain() {
    window.location.href = "/main";
  }

  AlumniApi.me()
    .then(function (me) {
      var roles = me.roles || [];
      var role = (me.role || "").toString().toLowerCase();
      var ok = role === "alumni" || roles.indexOf("alumni") >= 0;
      if (!ok) {
        goMain();
        return;
      }
      mount.innerHTML = "";
      var shell = AlumniLayout.render({
        userName: me.name || me.email,
        userId: me.id || "",
      });
      mount.appendChild(shell);

      if (!window.location.hash || window.location.hash === "#" || window.location.hash === "#/") {
        history.replaceState(null, "", window.location.pathname + window.location.search + "#/home");
      }

      function renderRoute() {
        var key = AlumniLayout.routeFromHash();
        AlumniLayout.syncNavForHashRoute(key);
        var root = document.getElementById("clContent");
        if (!root) return;

        if (key === "home") {
          window.AlumniPages.Overview.render(root);
          return;
        }
        if (key === "dashboard" || key === "overview") {
          window.AlumniPages.Dashboard.render(root);
          return;
        }
        if (key === "network") {
          window.AlumniPages.Network.render(root);
          return;
        }
        if (key === "profile") {
          window.AlumniPages.Profile.render(root, { startInEditMode: false });
          return;
        }
        if (key === "edit-profile") {
          window.AlumniPages.Profile.render(root, { startInEditMode: true });
          return;
        }
        if (key === "mentorship") {
          window.location.hash = "#/dashboard";
          return;
        }
        if (key === "messages") {
          window.location.href = "/messages";
          return;
        }
        if (key === "jobs") {
          window.AlumniPages.Jobs.render(root);
          return;
        }
        if (key === "settings") {
          window.AlumniPages.Settings && window.AlumniPages.Settings.render(root);
          return;
        }
        if (key === "help") {
          window.location.hash = "#/home";
          return;
        }

        root.innerHTML =
          "<div class=\"cl-page-head\"><div><h1>Page</h1></div></div><div class=\"cl-state\">Not found.</div>";
      }

      window.addEventListener("hashchange", renderRoute);
      renderRoute();
      AlumniLayout.refreshNotifBadge();
    })
    .catch(function (e) {
      if (e && e.status === 403) {
        goMain();
        return;
      }
      goLogin();
    });
})();
