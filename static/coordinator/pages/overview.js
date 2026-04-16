/* Overview page (real API data only) */

window.CoordinatorPages = window.CoordinatorPages || {};
window.CoordinatorPages.Overview = (() => {
  function statCard(label, value, hint) {
    const card = document.createElement("div");
    card.className = "cl-card cl-stat";
    card.innerHTML = `
      <div class="label">${label}</div>
      <div class="value">${value}</div>
      <div class="hint">${hint || ""}</div>
    `;
    return card;
  }

  function renderLoading(root) {
    root.innerHTML = `
      <div class="cl-page-head">
        <div>
          <h1>Overview</h1>
          <p>Loading real-time placement metrics…</p>
        </div>
      </div>
      <div class="cl-grid">
        <div class="cl-card cl-stat"><div class="label">Total students</div><div class="value">—</div><div class="hint">Loading…</div></div>
        <div class="cl-card cl-stat"><div class="label">Pending alumni requests</div><div class="value">—</div><div class="hint">Loading…</div></div>
        <div class="cl-card cl-stat"><div class="label">Active job posts</div><div class="value">—</div><div class="hint">Loading…</div></div>
      </div>
    `;
  }

  function renderError(root, message) {
    root.innerHTML = `
      <div class="cl-page-head">
        <div>
          <h1>Overview</h1>
          <p>Couldn’t load dashboard data.</p>
        </div>
      </div>
      <div class="cl-state cl-error">${message}</div>
    `;
  }

  function renderEmpty(root) {
    root.innerHTML = `
      <div class="cl-page-head">
        <div>
          <h1>Overview</h1>
          <p>No metrics available yet.</p>
        </div>
      </div>
      <div class="cl-state">Counts will appear once students, alumni requests, and job posts exist in the database.</div>
    `;
  }

  async function render(root) {
    renderLoading(root);
    try {
      const data = await window.CampusLinkApi.overview();
      const counts = (data && data.counts) || null;

      if (!counts) {
        renderEmpty(root);
        return;
      }

      const keys = ["total_students", "pending_alumni_requests", "active_job_posts"];
      const hasAny = keys.some((k) => typeof counts[k] === "number");
      if (!hasAny) {
        renderEmpty(root);
        return;
      }

      root.innerHTML = "";

      const head = document.createElement("div");
      head.className = "cl-page-head";
      head.innerHTML = `
        <div>
          <h1>Overview</h1>
          <p>Live metrics pulled from backend APIs.</p>
        </div>
      `;
      root.appendChild(head);

      const grid = document.createElement("div");
      grid.className = "cl-grid";

      grid.appendChild(statCard("Total students", typeof counts.total_students === "number" ? String(counts.total_students) : "—", "Registered student users"));
      grid.appendChild(statCard("Pending alumni requests", typeof counts.pending_alumni_requests === "number" ? String(counts.pending_alumni_requests) : "—", "Awaiting coordinator approval"));
      grid.appendChild(statCard("Active job posts", typeof counts.active_job_posts === "number" ? String(counts.active_job_posts) : "—", "status = active"));

      root.appendChild(grid);
    } catch (e) {
      if (e && e.status === 401) {
        // Token missing/expired; API client cleared it already.
        window.location.href = "/login";
        return;
      }
      if (e && e.status === 403) {
        window.location.href = "/main";
        return;
      }
      renderError(root, (e && e.message) ? e.message : "Unknown error");
    }
  }

  return { render };
})();

