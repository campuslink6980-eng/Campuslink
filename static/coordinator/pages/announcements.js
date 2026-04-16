/* Coordinator: announcements (JWT). */

window.CoordinatorPages = window.CoordinatorPages || {};
window.CoordinatorPages.Announcements = {
  render: function (root) {
    if (!window.CampusLinkAnnouncementsManage) {
      root.innerHTML =
        "<div class=\"cl-state cl-error\">Announcements module failed to load. Refresh the page.</div>";
      return;
    }
    window.CampusLinkAnnouncementsManage.render(root, { useJwt: true });
  },
};
