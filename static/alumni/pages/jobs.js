/* Alumni Jobs – list, create, edit, delete, view applicants */

window.AlumniPages = window.AlumniPages || {};

window.AlumniPages.Jobs = (function () {
  function escapeHtml(s) {
    return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  }

  function render(root) {
    root.innerHTML = "<div class=\"cl-page-head\"><div><h1>Job Postings</h1><p>Post and manage jobs. Only your jobs are shown.</p></div><button class=\"cl-btn primary\" id=\"alumniJobCreateBtn\" type=\"button\">+ Post job</button></div><div class=\"cl-state\" id=\"alumniJobsState\">Loading…</div><div id=\"alumniJobsList\" style=\"display:none;\"></div><div id=\"alumniJobFormWrap\" style=\"display:none;\"></div>";

    var stateEl = document.getElementById("alumniJobsState");
    var listEl = document.getElementById("alumniJobsList");
    var formWrap = document.getElementById("alumniJobFormWrap");
    var createBtn = document.getElementById("alumniJobCreateBtn");

    function loadJobs() {
      stateEl.style.display = "block";
      stateEl.textContent = "Loading…";
      listEl.style.display = "none";
      AlumniApi.jobsList()
        .then(function (res) {
          var items = (res && res.items) || [];
          stateEl.style.display = "none";
          if (!items.length) {
            stateEl.style.display = "block";
            stateEl.textContent = "No jobs posted yet. Click \"Post job\" to add your first job.";
            return;
          }
          listEl.style.display = "block";
          listEl.innerHTML = "";
          var table = document.createElement("table");
          table.className = "cl-table";
          table.innerHTML = "<thead><tr><th>Title</th><th>Company</th><th>Location</th><th>Type</th><th>Applicants</th><th>Actions</th></tr></thead><tbody id=\"alumniJobsTbody\"></tbody>";
          listEl.appendChild(table);
          var tbody = document.getElementById("alumniJobsTbody");
          items.forEach(function (job) {
            var tr = document.createElement("tr");
            var jobLabel = escapeHtml((job.title || "Job") + " · " + (job.company || "Company"));
            tr.innerHTML = "<td><strong>" + escapeHtml(job.title || "—") + "</strong></td><td>" + escapeHtml(job.company || "—") + "</td><td>" + escapeHtml(job.location || "—") + "</td><td>" + escapeHtml(job.job_type || "—") + "</td><td><span class=\"cl-badge\">" + (job.applicant_count != null ? job.applicant_count : 0) + "</span></td><td class=\"cl-actions\"><button type=\"button\" class=\"cl-btn sm\" data-view-applicants=\"" + escapeHtml(job.id) + "\" data-applicants-label=\"" + jobLabel + "\">Applicants</button><button class=\"cl-btn sm\" data-edit=\"" + escapeHtml(job.id) + "\">Edit</button><button class=\"cl-btn sm danger\" data-delete=\"" + escapeHtml(job.id) + "\">Delete</button></td>";
            tbody.appendChild(tr);
          });
          tbody.addEventListener("click", function (e) {
            var applicantsBtn = e.target.closest && e.target.closest("[data-view-applicants]");
            var viewId = applicantsBtn ? applicantsBtn.getAttribute("data-view-applicants") : e.target.getAttribute("data-view-applicants");
            var editId = e.target.getAttribute("data-edit");
            var deleteId = e.target.getAttribute("data-delete");
            if (viewId) {
              var rawLabel = (applicantsBtn && applicantsBtn.getAttribute("data-applicants-label")) || "";
              var q = "/job-applicants?type=alumni&job_id=" + encodeURIComponent(viewId);
              if (rawLabel) q += "&label=" + encodeURIComponent(rawLabel);
              window.open(q, "_blank", "noopener,noreferrer");
            }
            if (editId) showForm(editId);
            if (deleteId) {
              if (!confirm("Delete this job?")) return;
              AlumniApi.jobDelete(deleteId).then(function () { formWrap.style.display = "none"; loadJobs(); }).catch(function (err) { alert((err && err.message) || "Failed"); });
            }
          });
        })
        .catch(function (e) {
          stateEl.textContent = (e && e.message) || "Failed to load jobs.";
          stateEl.classList.add("cl-error");
        });
    }

    function showForm(jobId) {
      formWrap.style.display = "block";
      formWrap.innerHTML = "<div class=\"cl-state\">Loading form…</div>";
      fetch("/static/partials/alumni-job-post-form.html", { credentials: "same-origin" })
        .then(function (r) {
          if (!r.ok) throw new Error("Could not load job form.");
          return r.text();
        })
        .then(function (html) {
          formWrap.innerHTML = html;
          if (!window.AlumniJobPostForm || typeof window.AlumniJobPostForm.mount !== "function") {
            formWrap.innerHTML = "<div class=\"cl-error cl-state\">Job form script missing. Refresh the page.</div>";
            return;
          }
          window.AlumniJobPostForm.mount({
            editId: jobId || null,
            onCancel: function () {
              formWrap.style.display = "none";
              formWrap.innerHTML = "";
              loadJobs();
            },
            onSuccess: function () {
              formWrap.style.display = "none";
              formWrap.innerHTML = "";
              loadJobs();
            },
          });
        })
        .catch(function () {
          formWrap.innerHTML = "<div class=\"cl-error cl-state\">Could not load the job posting form.</div>";
        });
    }

    createBtn.addEventListener("click", function () { showForm(null); });
    loadJobs();
  }

  return { render: render };
})();
