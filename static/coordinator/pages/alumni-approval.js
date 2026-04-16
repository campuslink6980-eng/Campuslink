/* Coordinator – Alumni Approval Requests */

window.CoordinatorPages = window.CoordinatorPages || {};

window.CoordinatorPages.AlumniApproval = (() => {
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
          <h1>Alumni Approval Requests</h1>
          <p>Review and approve or reject alumni registration requests.</p>
        </div>
      </div>
      <div class="cl-state" id="alumniReqState">Loading…</div>
      <div id="alumniReqList" style="display:none;"></div>
    `;

    const stateEl = document.getElementById("alumniReqState");
    const listEl = document.getElementById("alumniReqList");

    async function load() {
      stateEl.style.display = "block";
      stateEl.textContent = "Loading…";
      listEl.style.display = "none";
      try {
        const data = await window.CampusLinkApi.alumniRequests("pending");
        const items = (data && data.items) || [];
        stateEl.style.display = "none";
        if (!items.length) {
          stateEl.style.display = "block";
          stateEl.textContent = "No pending alumni requests.";
          return;
        }
        listEl.style.display = "block";
        listEl.innerHTML = "";
        const table = document.createElement("table");
        table.className = "cl-table";
        table.innerHTML = `
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Branch</th>
              <th>Passout Year</th>
              <th>Requested</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody id="alumniReqBody"></tbody>
        `;
        listEl.appendChild(table);
        const tbody = document.getElementById("alumniReqBody");
        items.forEach((item) => {
          const tr = document.createElement("tr");
          tr.innerHTML = `
            <td>${escapeHtml(item.first_name + " " + item.last_name)}</td>
            <td>${escapeHtml(item.email)}</td>
            <td>${escapeHtml(item.branch || "—")}</td>
            <td>${escapeHtml(item.passout_year || "—")}</td>
            <td>${escapeHtml(item.created_at ? new Date(item.created_at).toLocaleDateString() : "—")}</td>
            <td class="cl-actions">
              <button class="cl-btn sm primary" data-approve="${escapeHtml(item.id)}">Approve</button>
              <button class="cl-btn sm danger" data-reject="${escapeHtml(item.id)}">Reject</button>
            </td>
          `;
          tbody.appendChild(tr);
        });
        tbody.addEventListener("click", async (e) => {
          const approveId = e.target.getAttribute("data-approve");
          const rejectId = e.target.getAttribute("data-reject");
          if (approveId) {
            if (!confirm("Approve this alumni request? An email will be sent to set their password.")) return;
            try {
              await window.CampusLinkApi.approveAlumniRequest(approveId);
              await load();
            } catch (err) {
              alert((err && err.message) || "Failed to approve.");
            }
          }
          if (rejectId) {
            if (!confirm("Reject this request?")) return;
            try {
              await window.CampusLinkApi.rejectAlumniRequest(rejectId);
              await load();
            } catch (err) {
              alert((err && err.message) || "Failed to reject.");
            }
          }
        });
      } catch (e) {
        stateEl.textContent = (e && e.message) || "Failed to load alumni requests.";
        stateEl.classList.add("cl-error");
      }
    }

    await load();
  }

  return { render };
})();
