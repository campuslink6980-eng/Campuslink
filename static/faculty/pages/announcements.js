/* Faculty: announcements (session). */

window.FacultyPages = window.FacultyPages || {};
window.FacultyPages.Announcements = {
  render: function (root) {
    if (!window.CampusLinkAnnouncementsManage) {
      root.innerHTML =
        "<div class=\"cl-state cl-error\">Announcements module failed to load. Refresh the page.</div>";
      return;
    }
    window.CampusLinkAnnouncementsManage.render(root, { useJwt: false });
  },
};
