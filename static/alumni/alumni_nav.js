/* Navbar: search, notifications, profile menu (student dashboard parity). */

window.AlumniNav = (function () {
  var searchTimeout = null;
  var notificationsData = [];

  function getAuthHeaders() {
    var h = {};
    var t = localStorage.getItem("campuslink_token");
    if (t) h["Authorization"] = "Bearer " + t;
    return h;
  }

  function fetchOpts(extra) {
    extra = extra || {};
    return Object.assign({ credentials: "same-origin", headers: getAuthHeaders() }, extra);
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatTimeAgo(dateStr) {
    if (!dateStr) return "";
    var utcStr = dateStr;
    if (!dateStr.endsWith("Z") && dateStr.indexOf("+", 10) < 0 && dateStr.indexOf("-", 10) < 0) {
      utcStr = dateStr + "Z";
    }
    var date = new Date(utcStr);
    var now = new Date();
    var diffMs = now - date;
    var diffMins = Math.floor(diffMs / 60000);
    var diffHours = Math.floor(diffMs / 3600000);
    var diffDays = Math.floor(diffMs / 86400000);
    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return diffMins + "m ago";
    if (diffHours < 24) return diffHours + "h ago";
    if (diffDays < 7) return diffDays + "d ago";
    return date.toLocaleDateString();
  }

  function getNotificationIconClass(type) {
    switch (type) {
      case "like":
        return "connection";
      case "comment":
        return "message";
      case "mention":
        return "job";
      case "job":
        return "job";
      case "connection":
      case "connection_request":
        return "connection";
      case "message":
        return "message";
      case "application":
        return "application";
      case "announcement":
        return "announcement";
      default:
        return "default";
    }
  }

  function getNotificationIcon(type) {
    switch (type) {
      case "announcement":
        return "📢";
      case "like":
        return "❤️";
      case "comment":
        return "💬";
      case "mention":
        return "@";
      case "job":
        return "💼";
      case "connection":
      case "connection_request":
        return "🤝";
      case "message":
        return "💬";
      case "application":
        return "📋";
      default:
        return "🔔";
    }
  }

  function renderNotifications(items) {
    var list = document.getElementById("notificationList");
    if (!list) return;
    if (!items.length) {
      list.innerHTML =
        "<div class=\"notification-empty\"><div class=\"notification-empty-icon\">🔔</div><p>No notifications yet</p></div>";
      return;
    }
    list.innerHTML = items
      .map(function (notif) {
        var notifType = notif.type || notif.notification_type;
        var iconClass = getNotificationIconClass(notifType);
        var icon = getNotificationIcon(notifType);
        var timeAgo = formatTimeAgo(notif.created_at);
        var unreadClass = notif.is_read ? "" : "unread";
        var metadata = notif.metadata || {};
        var senderName = notif.sender_name || "";
        var displayMessage =
          notif.notification_type === "profile_correction" && metadata.message
            ? metadata.message + (metadata.faculty_name ? " — " + metadata.faculty_name : "")
            : notifType === "announcement" || notif.notification_type === "announcement"
              ? notif.message || (metadata.title ? "New announcement: " + metadata.title : "New campus announcement")
              : notif.message ||
                senderName +
                  " " +
                  (notifType === "like"
                    ? "liked your post"
                    : notifType === "comment"
                      ? "commented on your post"
                      : notifType === "mention"
                        ? "mentioned you in a post"
                        : "sent a notification");
        var isConnectionRequest = notif.notification_type === "connection_request";
        var isPending = metadata.connection_status === "PENDING";
        var connectionId = metadata.connection_id;
        var actionButtons = "";
        if (isConnectionRequest && isPending && connectionId) {
          actionButtons =
            "<div class=\"notification-actions\" onclick=\"event.stopPropagation()\">" +
            "<button type=\"button\" class=\"notif-btn accept\" data-conn-accept=\"" +
            escapeHtml(connectionId) +
            "\" data-notif-id=\"" +
            escapeHtml(notif.id) +
            "\">Accept</button>" +
            "<button type=\"button\" class=\"notif-btn ignore\" data-conn-reject=\"" +
            escapeHtml(connectionId) +
            "\" data-notif-id=\"" +
            escapeHtml(notif.id) +
            "\">Ignore</button></div>";
        } else if (isConnectionRequest && metadata.connection_status === "ACCEPTED") {
          actionButtons = "<div class=\"notification-status accepted\">Connected</div>";
        }
        return (
          "<div class=\"notification-item " +
          unreadClass +
          "\" data-notif-click=\"" +
          escapeHtml(notif.id) +
          "\" data-notif-type=\"" +
          escapeHtml(notifType || "") +
          "\" data-ref-type=\"" +
          escapeHtml(notif.reference_type || "") +
          "\" data-ref-id=\"" +
          escapeHtml(notif.reference_id || "") +
          "\" data-post-id=\"" +
          escapeHtml(notif.post_id || "") +
          "\">" +
          "<div class=\"notification-icon " +
          iconClass +
          "\">" +
          icon +
          "</div>" +
          "<div class=\"notification-content\"><p class=\"notification-message\">" +
          escapeHtml(displayMessage) +
          "</p><span class=\"notification-time\">" +
          escapeHtml(timeAgo) +
          "</span>" +
          actionButtons +
          "</div></div>"
        );
      })
      .join("");

    list.querySelectorAll("[data-conn-accept]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        respondToConnectionNotif(btn.getAttribute("data-conn-accept"), "accept", btn.getAttribute("data-notif-id"));
      });
    });
    list.querySelectorAll("[data-conn-reject]").forEach(function (btn) {
      btn.addEventListener("click", function (e) {
        e.stopPropagation();
        respondToConnectionNotif(btn.getAttribute("data-conn-reject"), "reject", btn.getAttribute("data-notif-id"));
      });
    });
    list.querySelectorAll(".notification-item[data-notif-click]").forEach(function (row) {
      row.addEventListener("click", function () {
        if (row.getAttribute("data-notif-type") === "connection_request") return;
        handleNotificationClick(
          row.getAttribute("data-notif-click"),
          row.getAttribute("data-notif-type"),
          row.getAttribute("data-ref-type"),
          row.getAttribute("data-ref-id"),
          row.getAttribute("data-post-id")
        );
      });
    });
  }

  function loadNotifications() {
    return fetch("/api/notifications", fetchOpts())
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        notificationsData = data.items || [];
        var unreadCount = data.unread_count || notificationsData.filter(function (n) {
          return !n.is_read;
        }).length;
        var badge = document.getElementById("notification-badge");
        if (badge) {
          if (unreadCount > 0) {
            badge.textContent = unreadCount > 99 ? "99+" : String(unreadCount);
            badge.style.display = "flex";
          } else {
            badge.style.display = "none";
          }
        }
        renderNotifications(notificationsData);
      })
      .catch(function () {});
  }

  function toggleNotifications() {
    var dropdown = document.getElementById("notificationDropdown");
    var li = document.getElementById("liDropdown");
    if (!dropdown) return;
    if (li) li.style.display = "none";
    var isShowing = dropdown.classList.contains("show");
    if (isShowing) {
      dropdown.classList.remove("show");
    } else {
      dropdown.classList.add("show");
      loadNotifications();
    }
  }

  function toggleProfileMenu() {
    var menu = document.getElementById("liDropdown");
    var dd = document.getElementById("notificationDropdown");
    if (!menu) return;
    if (dd) dd.classList.remove("show");
    var isOpen = menu.style.display === "block";
    menu.style.display = isOpen ? "none" : "block";
    var avatar = document.querySelector(".li-avatar");
    if (avatar) avatar.setAttribute("aria-expanded", isOpen ? "false" : "true");
  }

  function markAllNotificationsRead() {
    fetch("/api/notifications", fetchOpts({ method: "POST" }))
      .then(function () {
        return loadNotifications();
      })
      .catch(function () {});
  }

  function respondToConnectionNotif(connectionId, action, notifId) {
    fetch("/api/connections/" + encodeURIComponent(connectionId) + "/respond", fetchOpts({
      method: "POST",
      headers: Object.assign({ "Content-Type": "application/json" }, getAuthHeaders()),
      body: JSON.stringify({ action: action === "accept" ? "accept" : "reject" }),
    }))
      .then(function (res) {
        if (!res.ok) return res.json().then(function (d) {
          throw new Error(d.error || "Failed");
        });
        return fetch("/api/notifications/" + encodeURIComponent(notifId) + "/read", fetchOpts({ method: "POST" }));
      })
      .then(function () {
        return loadNotifications();
      })
      .catch(function (e) {
        alert(e.message || "Failed");
      });
  }

  function handleNotificationClick(notifId, notifType, refType, refId, postId) {
    fetch("/api/notifications/" + encodeURIComponent(notifId) + "/read", fetchOpts({ method: "POST" })).catch(function () {});
    var url = null;
    if (notifType === "announcement" || refType === "announcement") {
      try {
        sessionStorage.setItem("campuslink_scroll_announcements", "1");
      } catch (e) {}
      url = "/alumni/dashboard#/home";
    } else if (notifType === "profile_correction") {
      url = "/profile/me";
    } else if ((notifType === "share" || refType === "post") && (postId || refId)) {
      url = "/post/" + encodeURIComponent(postId || refId);
    } else if ((notifType === "like" || notifType === "comment" || notifType === "mention") && (postId || refId)) {
      url = "/alumni/dashboard#/home";
    } else if (refType === "job" && refId) {
      url = "/jobs/" + refId;
    } else if (refType === "profile" && refId) {
      url = "/profile/" + refId;
    } else if (refType === "conversation" && refId) {
      url = "/messages?user=" + refId;
    }
    if (url) {
      window.location.href = url;
    } else {
      var d = document.getElementById("notificationDropdown");
      if (d) d.classList.remove("show");
      loadNotifications();
    }
  }

  function performSearch(query) {
    var searchResults = document.getElementById("search-results");
    var searchInput = document.getElementById("search-input");
    if (!searchResults || !searchInput) return;
    if (!query) {
      searchResults.classList.remove("show");
      searchResults.innerHTML = "";
      return;
    }
    fetch("/api/search/users?q=" + encodeURIComponent(query), fetchOpts())
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        var users = data.users || [];
        searchResults.innerHTML = "";
        if (!users.length) {
          searchResults.innerHTML = "<div class=\"search-no-results\">No users found</div>";
          searchResults.classList.add("show");
          return;
        }
        users.forEach(function (user) {
          var item = document.createElement("div");
          item.className = "search-result-item";
          item.innerHTML =
            "<div class=\"search-result-avatar\"></div><div class=\"search-result-info\"><div class=\"search-result-name\"></div><div class=\"search-result-meta\"></div></div>";
          item.querySelector(".search-result-avatar").textContent = (user.name || "?").charAt(0).toUpperCase();
          item.querySelector(".search-result-name").textContent = user.name || "Unknown";
          var metaParts = [];
          if (user.roll_number) metaParts.push(user.roll_number);
          if (user.branch) metaParts.push(user.branch);
          if (user.role) metaParts.push(user.role);
          item.querySelector(".search-result-meta").textContent = metaParts.join(" · ") || "User";
          item.addEventListener("click", function () {
            window.location.href = "/profile/" + encodeURIComponent(user.id);
          });
          searchResults.appendChild(item);
        });
        searchResults.classList.add("show");
      })
      .catch(function () {
        searchResults.classList.remove("show");
      });
  }

  function refreshNavStats() {
    var el = document.getElementById("navConnectionsMentor");
    if (!el) return;
    fetch("/api/alumni/dashboard", fetchOpts())
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        var conn = d.connection_count != null ? d.connection_count : 0;
        var mentees = d.active_mentees != null ? d.active_mentees : d.students_mentored != null ? d.students_mentored : 0;
        el.textContent = "Connections: " + conn + " | Mentees: " + mentees;
      })
      .catch(function () {
        el.textContent = "Connections: — | Mentees: —";
      });
  }

  function init(userName) {
    var name = userName || "Alumni";
    var liName = document.querySelector(".li-name");
    var liRole = document.querySelector(".li-role");
    if (liName) liName.textContent = name;
    if (liRole) liRole.textContent = "Alumni · CampusLink";

    var avatar = document.querySelector(".li-avatar span");
    if (avatar) avatar.textContent = "Me";

    document.querySelector(".li-avatar") &&
      document.querySelector(".li-avatar").addEventListener("click", function (e) {
        e.stopPropagation();
        toggleProfileMenu();
      });
    document.querySelector(".li-avatar") &&
      document.querySelector(".li-avatar").addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggleProfileMenu();
        }
      });

    document.addEventListener("click", function (e) {
      var wrap = document.querySelector(".li-profile-wrapper");
      if (wrap && !wrap.contains(e.target)) {
        var menu = document.getElementById("liDropdown");
        if (menu) menu.style.display = "none";
        var av = document.querySelector(".li-avatar");
        if (av) av.setAttribute("aria-expanded", "false");
      }
      var nw = document.querySelector(".nav-notification-wrapper");
      if (nw && !nw.contains(e.target)) {
        var dd = document.getElementById("notificationDropdown");
        if (dd) dd.classList.remove("show");
      }
      var sw = document.querySelector(".nav-search-wrapper");
      if (sw && !sw.contains(e.target)) {
        var sr = document.getElementById("search-results");
        if (sr) sr.classList.remove("show");
      }
    });

    var notifBtn = document.querySelector(".nav-notification");
    if (notifBtn) {
      notifBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        toggleNotifications();
      });
      notifBtn.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggleNotifications();
        }
      });
    }

    var searchInput = document.getElementById("search-input");
    if (searchInput) {
      searchInput.addEventListener("input", function (e) {
        var q = e.target.value.trim();
        if (searchTimeout) clearTimeout(searchTimeout);
        searchTimeout = setTimeout(function () {
          performSearch(q);
        }, 300);
      });
      searchInput.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
          var first = document.querySelector(".search-result-item");
          if (first) first.click();
        } else if (e.key === "Escape") {
          var sr = document.getElementById("search-results");
          if (sr) sr.classList.remove("show");
          searchInput.blur();
        }
      });
    }

    var markAllBtn = document.getElementById("alumniMarkAllNotif");
    if (markAllBtn) {
      markAllBtn.addEventListener("click", function () {
        markAllNotificationsRead();
      });
    }

    var signOut = document.getElementById("alumniSignOut");
    if (signOut) {
      signOut.addEventListener("click", function (e) {
        e.preventDefault();
        if (window.CampusLinkAuthSync && window.CampusLinkAuthSync.logoutEverywhere) {
          window.CampusLinkAuthSync.logoutEverywhere();
        } else {
          window.location.href = "/logout";
        }
      });
    }

    loadNotifications();
    refreshNavStats();
  }

  return {
    init: init,
    loadNotifications: loadNotifications,
    refreshNavStats: refreshNavStats,
    toggleProfileMenu: toggleProfileMenu,
  };
})();
