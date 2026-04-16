/**
 * Shared bell + dropdown for faculty / coordinator dashboards (session + JWT).
 * Call CampusLinkNavNotifications.init({ announcementUrl: "..." }) after layout mount.
 */
(function () {
  var notificationsData = [];
  var announcementUrl = "/user/dashboard#announcements-feed-anchor";
  var initialized = false;

  function notificationFetchHeaders() {
    var headers = {};
    var token = localStorage.getItem("campuslink_token");
    if (token) headers["Authorization"] = "Bearer " + token;
    return headers;
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
    if (!dateStr.endsWith("Z") && !dateStr.includes("+") && !dateStr.includes("-", 10)) {
      utcStr = dateStr + "Z";
    }
    var date = new Date(utcStr);
    var now = new Date();
    var diffMs = now - date;
    var diffMins = Math.floor(diffMs / 60000);
    var diffHours = Math.floor(diffMs / 3600000);
    var diffDays = Math.floor(diffMs / 86400000);
    if (diffMins < 0) return "Just now";
    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return diffMins + "m ago";
    if (diffHours < 24) return diffHours + "h ago";
    if (diffDays < 7) return diffDays + "d ago";
    return date.toLocaleDateString();
  }

  function getNotificationIconClass(type) {
    switch (type) {
      case "like": return "connection";
      case "comment": return "message";
      case "mention": return "job";
      case "job": return "job";
      case "connection":
      case "connection_request": return "connection";
      case "message": return "message";
      case "application": return "application";
      case "profile_correction": return "application";
      case "announcement": return "announcement";
      case "comment_like": return "announcement";
      default: return "default";
    }
  }

  function getNotificationIcon(type) {
    switch (type) {
      case "announcement": return "📢";
      case "like": return "❤️";
      case "comment": return "💬";
      case "mention": return "@";
      case "job": return "💼";
      case "connection":
      case "connection_request": return "🤝";
      case "message": return "💬";
      case "application": return "📋";
      case "profile_correction": return "✏️";
      case "comment_like": return "❤️";
      default: return "🔔";
    }
  }

  function renderNotifications(items) {
    var list = document.getElementById("notificationList");
    if (!list) return;
    if (!items.length) {
      list.innerHTML =
        '<div class="notification-empty">' +
        '<div class="notification-empty-icon">🔔</div>' +
        "<p>No notifications yet</p></div>";
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
            : notif.notification_type === "announcement" || notifType === "announcement"
              ? notif.message ||
                (metadata.title ? "New announcement: " + metadata.title : "New campus announcement")
              : notif.message ||
                senderName +
                  " " +
                  (notifType === "like"
                    ? "liked your post"
                    : notifType === "comment"
                      ? "commented on your post"
                      : notifType === "comment_like"
                        ? "liked your comment"
                        : notifType === "mention"
                          ? "mentioned you in a post"
                          : "sent a notification");
        var isConnectionRequest = notif.notification_type === "connection_request";
        var isPending = metadata.connection_status === "PENDING";
        var connectionId = metadata.connection_id;
        var actionButtons = "";
        if (isConnectionRequest && isPending && connectionId) {
          actionButtons =
            '<div class="notification-actions" onclick="event.stopPropagation()">' +
            '<button class="notif-btn accept" onclick="CampusLinkNavNotifications.respondToConnection(\'' +
            connectionId +
            "', 'accept', '" +
            notif.id +
            '\')">Accept</button>' +
            '<button class="notif-btn ignore" onclick="CampusLinkNavNotifications.respondToConnection(\'' +
            connectionId +
            "', 'reject', '" +
            notif.id +
            '\')">Ignore</button></div>';
        } else if (isConnectionRequest && metadata.connection_status === "ACCEPTED") {
          actionButtons = '<div class="notification-status accepted">Connected</div>';
        }
        return (
          '<div class="notification-item ' +
          unreadClass +
          '" onclick="CampusLinkNavNotifications.handleClick(\'' +
          notif.id +
          "', '" +
          (notif.notification_type || "") +
          "', '" +
          (notif.reference_type || "") +
          "', '" +
          (notif.reference_id || "") +
          "', '" +
          (notif.post_id || "") +
          "')\">" +
          '<div class="notification-icon ' +
          iconClass +
          '">' +
          icon +
          "</div>" +
          '<div class="notification-content">' +
          '<p class="notification-message">' +
          escapeHtml(displayMessage) +
          "</p>" +
          '<span class="notification-time">' +
          timeAgo +
          "</span>" +
          actionButtons +
          "</div></div>"
        );
      })
      .join("");
  }

  async function loadNotifications() {
    try {
      var res = await fetch("/api/notifications", {
        credentials: "same-origin",
        headers: notificationFetchHeaders(),
      });
      if (!res.ok) return;
      var data = await res.json();
      notificationsData = data.items || [];
      var unreadCount =
        data.unread_count || notificationsData.filter(function (n) { return !n.is_read; }).length;
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
    } catch (e) {
      console.error("Failed to load notifications", e);
    }
  }

  function toggleNotifications() {
    var dropdown = document.getElementById("notificationDropdown");
    if (!dropdown) return;
    var isShowing = dropdown.classList.contains("show");
    var li = document.getElementById("liDropdown");
    if (li) li.style.display = "none";
    if (isShowing) {
      dropdown.classList.remove("show");
    } else {
      dropdown.classList.add("show");
      loadNotifications();
    }
  }

  async function respondToConnectionNotif(connectionId, action, notifId) {
    try {
      var res = await fetch("/api/connections/" + connectionId + "/respond", {
        method: "POST",
        credentials: "same-origin",
        headers: Object.assign({}, notificationFetchHeaders(), { "Content-Type": "application/json" }),
        body: JSON.stringify({ action: action }),
      });
      if (!res.ok) {
        var data = await res.json().catch(function () { return {}; });
        throw new Error(data.error || "Failed to respond");
      }
      await fetch("/api/notifications/" + notifId + "/read", {
        method: "POST",
        credentials: "same-origin",
        headers: notificationFetchHeaders(),
      });
      loadNotifications();
    } catch (e) {
      console.error("Failed to respond to connection", e);
      alert(e.message || "Failed to respond to connection request");
    }
  }

  async function handleNotificationClick(notifId, notifType, refType, refId, postId) {
    if (notifType === "connection_request") return;
    try {
      await fetch("/api/notifications/" + notifId + "/read", {
        method: "POST",
        credentials: "same-origin",
        headers: notificationFetchHeaders(),
      });
    } catch (e) {
      console.error("Failed to mark notification as read", e);
    }
    var url = null;
    if (notifType === "announcement" || refType === "announcement") {
      url = announcementUrl;
    } else if (notifType === "profile_correction") {
      url = "/profile/me";
    } else if ((notifType === "share" || refType === "post") && (postId || refId)) {
      url = "/post/" + encodeURIComponent(postId || refId);
    } else if (notifType === "comment_like" && postId) {
      url = "/post/" + encodeURIComponent(postId) + "/comments";
    } else if ((notifType === "like" || notifType === "comment" || notifType === "mention") && (postId || refId)) {
      url = "/user/dashboard?post_id=" + encodeURIComponent(postId || refId);
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
      var dd = document.getElementById("notificationDropdown");
      if (dd) dd.classList.remove("show");
      loadNotifications();
    }
  }

  async function markAllNotificationsRead() {
    try {
      await fetch("/api/notifications", {
        method: "POST",
        credentials: "same-origin",
        headers: notificationFetchHeaders(),
      });
      loadNotifications();
    } catch (e) {
      console.error("Failed to mark all as read", e);
    }
  }

  function onDocClick(e) {
    var wrapper = document.querySelector(".nav-notification-wrapper");
    if (wrapper && !wrapper.contains(e.target)) {
      var dd = document.getElementById("notificationDropdown");
      if (dd) dd.classList.remove("show");
    }
  }

  function init(opts) {
    if (initialized) return;
    initialized = true;
    opts = opts || {};
    if (opts.announcementUrl) announcementUrl = opts.announcementUrl;

    var bell = document.querySelector(".nav-notification");
    if (bell) {
      bell.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          toggleNotifications();
        }
      });
    }
    document.addEventListener("click", onDocClick);
    loadNotifications();
  }

  window.CampusLinkNavNotifications = {
    init: init,
    load: loadNotifications,
    toggle: toggleNotifications,
    handleClick: handleNotificationClick,
    markAllRead: markAllNotificationsRead,
    respondToConnection: respondToConnectionNotif,
  };
})();
