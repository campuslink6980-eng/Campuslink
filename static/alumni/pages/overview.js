/* Alumni home — student-style feed/composer (see overview-home.js). */

window.AlumniPages = window.AlumniPages || {};

window.AlumniPages.Overview = {
  render: function (root) {
    if (window.AlumniOverviewHome && typeof window.AlumniOverviewHome.render === "function") {
      window.AlumniOverviewHome.render(root);
      return;
    }
    root.innerHTML =
      "<div class=\"card\" style=\"padding:20px;\">Home could not load. Refresh the page.</div>";
  },
};
