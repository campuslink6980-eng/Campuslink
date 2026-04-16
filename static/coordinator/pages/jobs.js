/* Coordinator Job Posts Page */

window.CoordinatorPages = window.CoordinatorPages || {};

window.CoordinatorPages.Jobs = (() => {
  async function render(root) {
    root.innerHTML = `
      <div class="cl-page-head">
        <div>
          <h1>Job Posts</h1>
          <p>Manage job and internship postings for your department.</p>
        </div>
        <button class="cl-btn primary" id="createJobBtn">+ Create New Job</button>
      </div>
      <div class="cl-state" id="jobsState">Loading job posts…</div>
      <div id="jobsList" style="display:none;"></div>
    `;

    document.getElementById("createJobBtn").addEventListener("click", () => {
      window.location.href = "/coordinator/jobs/create";
    });

    await loadJobs();
  }

  async function loadJobs() {
    const stateEl = document.getElementById("jobsState");
    const listEl = document.getElementById("jobsList");

    try {
      const data = await window.CampusLinkApi.get("/api/coordinator/jobs");
      const items = data.items || [];

      if (!items.length) {
        stateEl.textContent = "No job posts yet. Click 'Create New Job' to add your first posting.";
        stateEl.style.display = "block";
        listEl.style.display = "none";
        return;
      }

      stateEl.style.display = "none";
      listEl.style.display = "block";
      listEl.innerHTML = "";

      // Create table
      const table = document.createElement("table");
      table.className = "cl-table";
      table.innerHTML = `
        <thead>
          <tr>
            <th>Company</th>
            <th>Role</th>
            <th>Type</th>
            <th>Mode</th>
            <th>Deadline</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody id="jobsTableBody"></tbody>
      `;
      listEl.appendChild(table);

      const tbody = document.getElementById("jobsTableBody");
      items.forEach((job) => {
        const tr = document.createElement("tr");
        const statusClass = job.status === "active" ? "cl-badge success" : "cl-badge warning";
        tr.innerHTML = `
          <td><strong>${escapeHtml(job.company_name || "—")}</strong></td>
          <td>${escapeHtml(job.role || "—")}</td>
          <td><span class="cl-badge">${escapeHtml(job.type || "—")}</span></td>
          <td>${escapeHtml(job.mode || "—")}</td>
          <td>${escapeHtml(job.deadline || "—")}</td>
          <td><span class="${statusClass}">${escapeHtml(job.status || "active")}</span></td>
          <td class="cl-actions">
            <button class="cl-btn sm" data-view="${job.id}">View</button>
            <button class="cl-btn sm" data-edit="${job.id}">Edit</button>
            <button class="cl-btn sm danger" data-delete="${job.id}">Delete</button>
          </td>
        `;
        tbody.appendChild(tr);
      });

      // Event delegation for action buttons
      tbody.addEventListener("click", async (e) => {
        const viewId = e.target.getAttribute("data-view");
        const editId = e.target.getAttribute("data-edit");
        const deleteId = e.target.getAttribute("data-delete");

        if (viewId) {
          window.location.href = `/coordinator/jobs/${viewId}`;
        }
        if (editId) {
          window.location.href = `/coordinator/jobs/create?edit=${editId}`;
        }
        if (deleteId) {
          if (!confirm("Are you sure you want to delete this job post?")) return;
          try {
            await window.CampusLinkApi.del(`/api/jobs/${deleteId}`);
            await loadJobs(); // Refresh the list
          } catch (err) {
            alert(err.message || "Failed to delete job");
          }
        }
      });

    } catch (e) {
      stateEl.textContent = e.message || "Failed to load job posts";
      stateEl.style.display = "block";
      listEl.style.display = "none";
    }
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  return { render };
})();
