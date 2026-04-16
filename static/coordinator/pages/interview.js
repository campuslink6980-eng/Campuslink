/* Coordinator Interview page – in-dashboard interview cards */

window.CoordinatorPages = window.CoordinatorPages || {};

window.CoordinatorPages.Interview = (() => {
  function esc(v) {
    return String(v || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function cardHtml(d) {
    return `
      <article class="cl-card" style="padding:14px; border-radius:14px; cursor:pointer;" data-drive-id="${esc(d.id)}">
        <div style="font-weight:800; font-size:16px; color:#1d2226;">${esc(d.company || "Company")}</div>
        <div style="font-size:13px; color:#6b7280; margin-top:4px;">${esc(d.role || "Role")}</div>
        ${
          d.can_delete
            ? `<button type="button" class="cl-btn sm" style="margin-top:10px; color:#dc2626; border-color:rgba(220,14,14,0.35);" data-delete-id="${esc(d.id)}">Delete</button>`
            : ""
        }
      </article>
    `;
  }

  async function loadDrives(root) {
    const host = root.querySelector("#coInterviewList");
    if (!host) return;
    host.innerHTML = `<div class="cl-state">Loading interview drives...</div>`;
    try {
      const res = await fetch("/api/interview/drives", { credentials: "same-origin" });
      if (res.status === 401) {
        window.location.href = "/login";
        return;
      }
      const data = await res.json();
      const drives = (data && data.drives) || [];
      if (!drives.length) {
        host.innerHTML = `<div class="cl-state">No interview drives found.</div>`;
        return;
      }
      host.innerHTML = `<div class="cl-grid">${drives.map(cardHtml).join("")}</div>`;
      host.querySelectorAll("[data-drive-id]").forEach((el) => {
        el.addEventListener("click", () => {
          const id = el.getAttribute("data-drive-id");
          if (id) window.location.href = "/interview-drive/" + encodeURIComponent(id);
        });
      });
      host.querySelectorAll("[data-delete-id]").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
          e.preventDefault();
          e.stopPropagation();
          const id = btn.getAttribute("data-delete-id");
          if (!id) return;
          if (!window.confirm("Delete this interview drive?")) return;
          try {
            const delRes = await fetch("/api/coordinator/interview-drives/" + encodeURIComponent(id), {
              method: "DELETE",
              credentials: "same-origin",
            });
            const delData = await delRes.json();
            if (!delRes.ok) {
              alert(delData.error || "Delete failed.");
              return;
            }
            await loadDrives(root);
          } catch (_) {
            alert("Delete failed.");
          }
        });
      });
    } catch (_) {
      host.innerHTML = `<div class="cl-state cl-error">Unable to load interview drives.</div>`;
    }
  }

  async function render(root) {
    root.innerHTML = `
      <div class="cl-page-head">
        <div>
          <h1>Interview</h1>
          <p>Manage interview drives from this dashboard panel.</p>
        </div>
        <a href="/coordinator/post-interview" class="cl-btn primary">+ Add Interview</a>
      </div>
      <div id="coInterviewList" style="display:grid; gap:12px;"></div>
    `;
    await loadDrives(root);
  }

  return { render };
})();
