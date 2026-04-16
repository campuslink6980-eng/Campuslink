/* Coordinator Applications Page - Jobs with student applications */

window.CoordinatorPages = window.CoordinatorPages || {};

window.CoordinatorPages.Applications = (() => {
  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  async function render(root) {
    root.innerHTML = `
      <div class="cl-page-head">
        <div>
          <h1>Applications</h1>
          <p>View jobs where students have applied. Click a job to see applicants and view their full profiles.</p>
        </div>
      </div>
      <div class="cl-state" id="appsState">Loading jobs with applications…</div>
      <div id="appsJobsList" style="display:none;"></div>
    `;

    const stateEl = document.getElementById("appsState");
    const listEl = document.getElementById("appsJobsList");

    try {
      const data = await window.CampusLinkApi.get("/api/coordinator/jobs");
      const allJobs = data.items || [];
      const jobsWithApps = allJobs.filter((j) => (j.application_count || 0) > 0);

      if (!jobsWithApps.length) {
        stateEl.textContent = "No job applications yet. When students apply to your jobs, they will appear here.";
        stateEl.style.display = "block";
        listEl.style.display = "none";
        return;
      }

      stateEl.style.display = "none";
      listEl.style.display = "block";

      const table = document.createElement("table");
      table.className = "cl-table";
      table.innerHTML = `
        <thead>
          <tr>
            <th>Job</th>
            <th>Company</th>
            <th>Applications</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody id="appsJobsBody"></tbody>
      `;
      listEl.innerHTML = "";
      listEl.appendChild(table);

      const tbody = document.getElementById("appsJobsBody");
      jobsWithApps.forEach((job) => {
        const tr = document.createElement("tr");
        const rowLabel = escapeHtml(`${job.role || "Role"} · ${job.company_name || "Company"}`);
        tr.innerHTML = `
          <td><strong>${escapeHtml(job.role || "—")}</strong></td>
          <td>${escapeHtml(job.company_name || "—")}</td>
          <td><span class="cl-badge">${job.application_count || 0}</span></td>
          <td>
            <button type="button" class="cl-btn sm" data-view-job="${escapeHtml(job.id)}" data-job-label="${rowLabel}">View applicants</button>
          </td>
        `;
        tbody.appendChild(tr);
      });

      tbody.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-view-job]");
        const jobId = btn && btn.getAttribute("data-view-job");
        if (!jobId) return;
        const rawLabel = (btn.getAttribute("data-job-label") || "").trim();
        let q = `/job-applicants?type=coordinator&job_id=${encodeURIComponent(jobId)}`;
        if (rawLabel) q += `&label=${encodeURIComponent(rawLabel)}`;
        window.open(q, "_blank", "noopener,noreferrer");
      });
    } catch (e) {
      stateEl.textContent = e.message || "Failed to load jobs with applications";
      stateEl.style.display = "block";
      listEl.style.display = "none";
    }
  }

  return { render };
})();
