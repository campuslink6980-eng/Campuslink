/* Alumni Dashboard: overview metrics, mentees (max 5), pending mentorship actions */

window.AlumniPages = window.AlumniPages || {};

window.AlumniPages.Dashboard = (function () {
  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  var slotsFull = false;

  function statCard(title, valueHtml, footer, footerIsHtml) {
    var foot = footerIsHtml ? footer : escapeHtml(footer);
    return (
      "<article class=\"alumni-dash-stat-card\">" +
        "<div class=\"alumni-dash-stat-title\">" +
        escapeHtml(title) +
        "</div>" +
        "<div class=\"alumni-dash-stat-value\">" +
        valueHtml +
        "</div>" +
        "<div class=\"alumni-dash-stat-foot\">" +
        foot +
        "</div>" +
      "</article>"
    );
  }

  function loadOverview(gridEl) {
    return AlumniApi.dashboard()
      .then(function (d) {
        slotsFull = Boolean(d.mentee_slots_full);
        var jobsHint =
          "<a class=\"alumni-dash-inline-link\" href=\"#/jobs\">Manage job postings →</a>";
        gridEl.innerHTML =
          statCard("Profile completion", escapeHtml(String(d.profile_completion != null ? d.profile_completion : "—")) + "%", "Complete your profile to help students") +
          statCard(
            "Mentorship requests received",
            escapeHtml(String(d.mentorship_requests_received != null ? d.mentorship_requests_received : "—")),
            "Total requests"
          ) +
          statCard("Referrals given", escapeHtml(String(d.referrals_given != null ? d.referrals_given : "—")), "Approved referrals") +
          statCard(
            "Jobs posted",
            escapeHtml(String(d.jobs_posted != null ? d.jobs_posted : "—")),
            "Your job postings · " + jobsHint,
            true
          ) +
          statCard(
            "Students mentored",
            escapeHtml(String(d.students_mentored != null ? d.students_mentored : "—")),
            "Accepted mentorship"
          );
      })
      .catch(function () {
        gridEl.innerHTML = "<p class=\"alumni-dash-err\">Could not load overview.</p>";
      });
  }

  function renderMentees(listEl) {
    listEl.innerHTML = "<p class=\"alumni-dash-muted\">Loading mentees…</p>";
    return AlumniApi.mentorshipList("accepted")
      .then(function (res) {
        var items = ((res && res.items) || []).slice(0, 5);
        if (!items.length) {
          listEl.innerHTML = "<p class=\"alumni-dash-muted\">No active mentees yet.</p>";
          return;
        }
        listEl.innerHTML = "";
        var ul = document.createElement("ul");
        ul.className = "alumni-dash-mentee-list";
        items.forEach(function (it) {
          var li = document.createElement("li");
          li.className = "alumni-dash-mentee-item";
          var sid = (it.student_id || "").toString();
          var name = escapeHtml(it.student_name || it.student_email || "Student");
          var prof =
            sid ?
              "<a class=\"alumni-dash-mentee-link\" href=\"/mentor-view-profile/" +
              escapeHtml(sid) +
              "\" target=\"_blank\" rel=\"noopener\">View profile</a>" :
              "";
          li.innerHTML =
            "<div class=\"alumni-dash-mentee-main\"><strong>" +
            name +
            "</strong>" +
            (it.student_email ? "<span class=\"alumni-dash-muted\">" + escapeHtml(it.student_email) + "</span>" : "") +
            "</div>" +
            prof;
          ul.appendChild(li);
        });
        listEl.appendChild(ul);
      })
      .catch(function () {
        listEl.innerHTML = "<p class=\"alumni-dash-err\">Could not load mentees.</p>";
      });
  }

  function loadPendingContent(mountEl) {
    mountEl.innerHTML = "<p class=\"alumni-dash-muted\">Loading requests…</p>";
    return AlumniApi.dashboard()
      .then(function (d) {
        slotsFull = Boolean(d.mentee_slots_full);
      })
      .catch(function () {})
      .then(function () {
        return AlumniApi.mentorshipList("pending");
      })
      .then(function (res) {
        var items = (res && res.items) || [];
        if (!items.length) {
          mountEl.innerHTML = "<p class=\"alumni-dash-muted\">No pending mentorship requests.</p>";
          return;
        }
        mountEl.innerHTML = "";
        items.forEach(function (it) {
          var card = document.createElement("div");
          card.className = "alumni-dash-request-card";
          var msg = it.message ? "<p class=\"alumni-dash-req-msg\">" + escapeHtml(it.message) + "</p>" : "";
          var sid = (it.student_id || "").toString();
          var view =
            sid ?
              "<a class=\"alumni-dash-inline-link\" href=\"/mentor-view-profile/" +
              escapeHtml(sid) +
              "\" target=\"_blank\" rel=\"noopener\">View student profile</a>" :
              "";
          var acceptDisabled = slotsFull;
          card.innerHTML =
            "<div class=\"alumni-dash-req-head\"><strong>" +
            escapeHtml(it.student_name || it.student_email || "Student") +
            "</strong>" +
            "<span class=\"alumni-dash-muted\">" +
            escapeHtml(it.created_at ? new Date(it.created_at).toLocaleString() : "") +
            "</span></div>" +
            msg +
            view +
            "<div class=\"alumni-dash-req-actions\">" +
            "<button type=\"button\" class=\"alumni-dash-btn alumni-dash-btn-primary\" data-accept=\"" +
            escapeHtml(it.id) +
            "\"" +
            (acceptDisabled ? " disabled title=\"Mentee slots full (max 5)\"" : "") +
            ">Accept</button>" +
            "<button type=\"button\" class=\"alumni-dash-btn alumni-dash-btn-ghost\" data-reject=\"" +
            escapeHtml(it.id) +
            "\">Reject</button>" +
            "</div>";
          if (acceptDisabled) {
            var hint = document.createElement("p");
            hint.className = "alumni-dash-muted";
            hint.style.marginTop = "8px";
            hint.textContent = "Mentee slots full. Remove a mentee before accepting new requests.";
            card.appendChild(hint);
          }
          mountEl.appendChild(card);
        });
      })
      .catch(function () {
        mountEl.innerHTML = "<p class=\"alumni-dash-err\">Could not load pending requests.</p>";
      });
  }

  function render(root) {
    root.innerHTML =
      "<div class=\"alumni-dash\">" +
        "<header class=\"alumni-dash-header\">" +
          "<h1 class=\"alumni-dash-h1\">Overview</h1>" +
          "<p class=\"alumni-dash-sub\">Your alumni dashboard at a glance.</p>" +
        "</header>" +
        "<section class=\"alumni-dash-section\" aria-labelledby=\"dash-overview-stats\">" +
          "<h2 id=\"dash-overview-stats\" class=\"sr-only\">Statistics</h2>" +
          "<div id=\"alumniDashStatGrid\" class=\"alumni-dash-stat-grid\"></div>" +
        "</section>" +
        "<section class=\"alumni-dash-section\" aria-labelledby=\"dash-mentees\">" +
          "<h2 id=\"dash-mentees\" class=\"alumni-dash-h2\">Mentees</h2>" +
          "<p class=\"alumni-dash-muted\">Up to 5 active mentees.</p>" +
          "<div id=\"alumniDashMentees\"></div>" +
        "</section>" +
        "<section class=\"alumni-dash-section\" aria-labelledby=\"dash-pending\">" +
          "<h2 id=\"dash-pending\" class=\"alumni-dash-h2\">Accept / reject mentorship requests</h2>" +
          "<p class=\"alumni-dash-muted\">Respond to students who requested your guidance.</p>" +
          "<div id=\"alumniDashPending\"></div>" +
        "</section>" +
        "<p class=\"alumni-dash-footer-links\"><a class=\"alumni-dash-inline-link\" href=\"#/network\">Open full network &amp; mentorship →</a></p>" +
      "</div>";

    var grid = root.querySelector("#alumniDashStatGrid");
    var mentees = root.querySelector("#alumniDashMentees");
    var pending = root.querySelector("#alumniDashPending");

    function refreshAll() {
      loadOverview(grid);
      renderMentees(mentees);
      loadPendingContent(pending);
      if (window.AlumniLayout && window.AlumniLayout.refreshNotifBadge) {
        window.AlumniLayout.refreshNotifBadge();
      }
    }

    pending.addEventListener("click", function (e) {
      var accEl = e.target.closest("[data-accept]");
      var rejEl = e.target.closest("[data-reject]");
      var acc = accEl && accEl.getAttribute("data-accept");
      var rej = rejEl && rejEl.getAttribute("data-reject");
      if (acc) {
        if (slotsFull) {
          alert("Mentee slots full (max 5).");
          return;
        }
        AlumniApi.mentorshipPatch(acc, { status: "accepted" })
          .then(function () {
            refreshAll();
          })
          .catch(function (err) {
            var m = (err && err.message) || "Failed";
            if (err && err.data && err.data.error) m = err.data.error;
            alert(m);
          });
      }
      if (rej) {
        AlumniApi.mentorshipPatch(rej, { status: "rejected" })
          .then(function () {
            refreshAll();
          })
          .catch(function (err) {
            alert((err && err.message) || "Failed");
          });
      }
    });

    refreshAll();
  }

  return { render: render };
})();
