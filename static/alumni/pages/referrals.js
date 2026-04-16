/* Alumni Referrals – list requests, approve/reject, view student */

window.AlumniPages = window.AlumniPages || {};

window.AlumniPages.Referrals = (function () {
  function escapeHtml(s) {
    return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  }

  function render(root) {
    root.innerHTML = "<div class=\"cl-page-head\"><div><h1>Referrals</h1><p>View and respond to referral requests from students.</p></div><select id=\"referralsFilter\"><option value=\"\">All</option><option value=\"pending\">Pending</option><option value=\"approved\">Approved</option><option value=\"rejected\">Rejected</option></select></div><div class=\"cl-state\" id=\"referralsState\">Loading…</div><div id=\"referralsList\" style=\"display:none;\"></div>";

    var stateEl = document.getElementById("referralsState");
    var listEl = document.getElementById("referralsList");
    var filterEl = document.getElementById("referralsFilter");

    function load(status) {
      stateEl.style.display = "block";
      stateEl.textContent = "Loading…";
      listEl.style.display = "none";
      AlumniApi.referralsList(status || undefined)
        .then(function (res) {
          var items = (res && res.items) || [];
          stateEl.style.display = "none";
          if (!items.length) {
            stateEl.style.display = "block";
            stateEl.textContent = "No referral requests yet. When students request referrals, they will appear here.";
            return;
          }
          listEl.style.display = "block";
          listEl.innerHTML = "";
          var table = document.createElement("table");
          table.className = "cl-table";
          table.innerHTML = "<thead><tr><th>Student</th><th>Job</th><th>Status</th><th>Date</th><th>Actions</th></tr></thead><tbody id=\"referralsTbody\"></tbody>";
          listEl.appendChild(table);
          var tbody = document.getElementById("referralsTbody");
          items.forEach(function (item) {
            var statusClass = item.status === "approved" ? "cl-badge success" : item.status === "rejected" ? "cl-badge danger" : "cl-badge warning";
            var tr = document.createElement("tr");
            tr.innerHTML = "<td>" + escapeHtml(item.student_name || item.student_email || "—") + "</td><td>" + escapeHtml(item.job_title || "—") + "</td><td><span class=\"" + statusClass + "\">" + escapeHtml(item.status) + "</span></td><td>" + escapeHtml(item.created_at ? new Date(item.created_at).toLocaleDateString() : "—") + "</td><td class=\"cl-actions\"><button class=\"cl-btn sm\" data-view-student=\"" + escapeHtml(item.id) + "\">View student</button>" + (item.status === "pending" ? "<button class=\"cl-btn sm primary\" data-approve=\"" + escapeHtml(item.id) + "\">Approve</button><button class=\"cl-btn sm danger\" data-reject=\"" + escapeHtml(item.id) + "\">Reject</button>" : "") + "</td>";
            tbody.appendChild(tr);
          });
          tbody.addEventListener("click", function (e) {
            var viewId = e.target.getAttribute("data-view-student");
            var approveId = e.target.getAttribute("data-approve");
            var rejectId = e.target.getAttribute("data-reject");
            if (viewId) {
              AlumniApi.referralStudent(viewId).then(function (student) {
                var msg = "Name: " + (student.name || "—") + "\nEmail: " + (student.email || "—") + "\nBranch: " + (student.branch || "—");
                if (student.resume_url) msg += "\nResume: " + student.resume_url;
                alert(msg);
              }).catch(function () { alert("Could not load student."); });
            }
            if (approveId) {
              var note = prompt("Referral note (optional):");
              AlumniApi.referralsPatch(approveId, { status: "approved", referral_note: note || undefined }).then(function () { load(filterEl.value); }).catch(function (err) { alert((err && err.message) || "Failed"); });
            }
            if (rejectId) {
              var note = prompt("Reason or note (optional):");
              AlumniApi.referralsPatch(rejectId, { status: "rejected", referral_note: note || undefined }).then(function () { load(filterEl.value); }).catch(function (err) { alert((err && err.message) || "Failed"); });
            }
          });
        })
        .catch(function (e) {
          stateEl.textContent = (e && e.message) || "Failed to load referrals.";
          stateEl.classList.add("cl-error");
        });
    }

    filterEl.addEventListener("change", function () { load(filterEl.value || undefined); });
    load();
  }

  return { render: render };
})();
