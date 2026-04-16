/* Cross-tab auth sync for CampusLink */
(function (window) {
  "use strict";

  var LOGOUT_KEY = "campuslink_logout_at";

  function clearLocalAuthState() {
    try {
      localStorage.removeItem("campuslink_token");
      localStorage.removeItem("campuslink_role");
      localStorage.removeItem("selected_role");
      localStorage.removeItem("user_roles");
      localStorage.removeItem("user_name");
      localStorage.removeItem("user_email");
    } catch (e) {
      /* ignore */
    }
  }

  function redirectToLogin() {
    if (window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
  }

  function broadcastLogout() {
    try {
      localStorage.setItem(LOGOUT_KEY, String(Date.now()));
    } catch (e) {
      /* ignore */
    }
  }

  function logoutEverywhere() {
    clearLocalAuthState();
    broadcastLogout();
    window.location.href = "/logout";
  }

  function bindLogoutLinks() {
    document.addEventListener("click", function (e) {
      var t = e.target;
      if (!t) return;
      var a = t.closest ? t.closest("a[href='/logout']") : null;
      if (!a) return;
      e.preventDefault();
      logoutEverywhere();
    });
  }

  window.addEventListener("storage", function (e) {
    if (e && e.key === LOGOUT_KEY) {
      clearLocalAuthState();
      redirectToLogin();
    }
  });

  bindLogoutLinks();

  window.CampusLinkAuthSync = {
    logoutEverywhere: logoutEverywhere,
    broadcastLogout: broadcastLogout,
    clearLocalAuthState: clearLocalAuthState
  };
})(window);

