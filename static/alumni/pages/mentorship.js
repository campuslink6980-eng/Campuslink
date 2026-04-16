/* Alumni Mentorship – list requests, accept/reject, view mentee */

window.AlumniPages = window.AlumniPages || {};

window.AlumniPages.Mentorship = (function () {
  function escapeHtml(s) {
    return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  }

  function render(root) {
    root.innerHTML = "<div class=\"cl-page-head\"><div><h1>Mentorship</h1><p>View and respond to mentorship requests.</p></div><select id=\"mentorshipFilter\"><option value=\"\">All</option><option value=\"pending\">Pending</option><option value=\"accepted\">Accepted</option><option value=\"rejected\">Rejected</option></select></div><div class=\"cl-state\" id=\"mentorshipState\">Loading…</div><div id=\"mentorshipList\" style=\"display:none;\"></div>";

    var stateEl = document.getElementById("mentorshipState");
    var listEl = document.getElementById("mentorshipList");
    var filterEl = document.getElementById("mentorshipFilter");

    var slotsFull = false;

    function load(status) {
      stateEl.style.display = "block";
      stateEl.textContent = "Loading…";
      listEl.style.display = "none";
      AlumniApi.dashboard()
        .then(function (dash) {
          slotsFull = Boolean(dash.mentee_slots_full);
        })
        .catch(function () {
          slotsFull = false;
        })
        .then(function () {
          return AlumniApi.mentorshipList(status || undefined);
        })
        .then(function (res) {
          var items = (res && res.items) || [];
          stateEl.style.display = "none";
          if (!items.length) {
            stateEl.style.display = "block";
            stateEl.textContent = "No mentorship requests yet. When students send requests, they will appear here.";
            return;
          }
          listEl.style.display = "block";
          listEl.innerHTML = "";
          var table = document.createElement("table");
          table.className = "cl-table";
          table.innerHTML = "<thead><tr><th>Student</th><th>Status</th><th>Date</th><th>Actions</th></tr></thead><tbody id=\"mentorshipTbody\"></tbody>";
          listEl.appendChild(table);
          var tbody = document.getElementById("mentorshipTbody");
          items.forEach(function (item) {
            var tr = document.createElement("tr");
            var statusClass = item.status === "accepted" ? "cl-badge success" : item.status === "rejected" ? "cl-badge danger" : "cl-badge warning";
            var studentId = (item.student_id || "").toString();
            var viewProfileLink = studentId ? "<a class=\"cl-btn sm\" href=\"/mentor-view-profile/" + escapeHtml(studentId) + "\" target=\"_blank\" rel=\"noopener\">View Profile</a>" : "<button class=\"cl-btn sm\" data-view-mentee=\"" + escapeHtml(item.id) + "\">View mentee</button>";
            var acceptDisabled = item.status === "pending" && slotsFull;
            var acceptBtn = item.status === "pending"
              ? " <button class=\"cl-btn sm primary\" data-accept=\"" + escapeHtml(item.id) + "\"" + (acceptDisabled ? " disabled title=\"Mentee slots full\"" : "") + ">Accept</button><button class=\"cl-btn sm danger\" data-reject=\"" + escapeHtml(item.id) + "\">Reject</button>"
              : "";
            if (acceptDisabled) {
              acceptBtn += " <span class=\"ln-slot-hint\">Mentee slots full</span>";
            }
            tr.innerHTML = "<td>" + escapeHtml(item.student_name || item.student_email || "—") + "</td><td><span class=\"" + statusClass + "\">" + escapeHtml(item.status) + "</span></td><td>" + escapeHtml(item.created_at ? new Date(item.created_at).toLocaleDateString() : "—") + "</td><td class=\"cl-actions\">" + viewProfileLink + acceptBtn + "</td>";
            tbody.appendChild(tr);
          });
          tbody.addEventListener("click", function (e) {
            var viewId = e.target.getAttribute("data-view-mentee");
            var acceptId = e.target.getAttribute("data-accept");
            var rejectId = e.target.getAttribute("data-reject");
            if (viewId) {
              AlumniApi.mentorshipMentee(viewId).then(function (mentee) {
                var msg = "Name: " + (mentee.name || "—") + "\nEmail: " + (mentee.email || "—") + "\nBranch: " + (mentee.branch || "—");
                if (mentee.profile && (mentee.profile.basic || mentee.profile.headline)) msg += "\n\nProfile: " + JSON.stringify(mentee.profile, null, 2).slice(0, 500);
                alert(msg);
              }).catch(function () { alert("Could not load mentee."); });
            }
            if (acceptId) {
              if (slotsFull) {
                alert("Mentee slots full. Remove a mentee to accept new requests.");
                return;
              }
              AlumniApi.mentorshipPatch(acceptId, { status: "accepted" }).then(function () { load(filterEl.value); }).catch(function (err) {
                var msg = (err && err.message) || "Failed";
                if (err && err.data && err.data.error) msg = err.data.error;
                alert(msg);
              });
            }
            if (rejectId) {
              AlumniApi.mentorshipPatch(rejectId, { status: "rejected" }).then(function () { load(filterEl.value); }).catch(function (err) { alert((err && err.message) || "Failed"); });
            }
          });
        })
        .catch(function (e) {
          stateEl.textContent = (e && e.message) || "Failed to load mentorship requests.";
          stateEl.classList.add("cl-error");
        });
    }

    filterEl.addEventListener("change", function () { load(filterEl.value || undefined); });
    load();
  }

  return { render: render };
})();
