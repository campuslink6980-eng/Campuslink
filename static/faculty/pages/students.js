window.FacultyPages = window.FacultyPages || {};
window.FacultyPages.Students = (function () {
  var MIN_COMPLETION_FOR_VERIFY = 50;

  function esc(s) { return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function badge(status, label) {
    var s = (status || "").toUpperCase();
    var c = s === "VERIFIED" || s === "APPROVED" ? "success" : s === "REJECTED" ? "danger" : "warning";
    return "<span class=\"cl-badge " + c + "\">" + esc(label || status) + "</span>";
  }
  function completionBar(pct) {
    pct = Math.min(100, Math.max(0, parseInt(pct, 10) || 0));
    return "<div class=\"cl-completion-wrap\" style=\"min-width:80px;\"><div class=\"cl-completion-bar\" style=\"height:8px;background:rgba(15,23,42,0.08);border-radius:4px;overflow:hidden;\"><div style=\"width:" + pct + "%;height:100%;background:linear-gradient(90deg,#118a3b,#16a34a);border-radius:4px;\"></div></div><span style=\"font-size:12px;color:var(--muted,#64748b);\">" + pct + "%</span></div>";
  }

  function buildTableActions(s) {
    var pct = parseInt(s.profile_completion, 10) || 0;
    var verStatus = (s.verification_status || "").toUpperCase();

    if (verStatus === "VERIFIED") {
      return "<a href=\"/profile/" + esc(s.id) + "\" target=\"_blank\" rel=\"noopener\" class=\"cl-btn sm\">View Profile</a> " +
        "<button class=\"cl-btn sm primary\" data-correction=\"" + esc(s.id) + "\" data-name=\"" + esc(s.name || "Student") + "\">Correction/Changes</button> " +
        "<button class=\"cl-btn sm\" data-unverify=\"" + esc(s.id) + "\">Unverify</button>";
    }

    if (verStatus === "REJECTED") {
      return "<span class=\"cl-badge danger\" aria-label=\"Rejected\">Rejected</span>";
    }

    if (pct < MIN_COMPLETION_FOR_VERIFY) {
      return "<button class=\"cl-btn sm\" disabled title=\"Complete profile to 50%+ to enable verification\">Verify</button> " +
        "<button class=\"cl-btn sm\" disabled title=\"Complete profile to 50%+ to enable verification\">Needs correction</button> " +
        "<button class=\"cl-btn sm danger\" disabled title=\"Complete profile to 50%+ to enable verification\">Reject</button>";
    }

    return "<button class=\"cl-btn sm primary\" data-verify=\"" + esc(s.id) + "\">Verify</button> " +
      "<button class=\"cl-btn sm\" data-needs=\"" + esc(s.id) + "\">Needs correction</button> " +
      "<button class=\"cl-btn sm danger\" data-reject=\"" + esc(s.id) + "\">Reject</button>";
  }

  function buildCardActions(s) {
    var pct = parseInt(s.profile_completion, 10) || 0;
    var verStatus = (s.verification_status || "").toUpperCase();
    var viewBtn = "<a href=\"/profile/" + esc(s.id) + "\" target=\"_blank\" rel=\"noopener\" class=\"cl-btn sm\">View Profile</a>";

    if (verStatus === "VERIFIED") {
      return "<div style=\"display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;\">" + viewBtn +
        " <button class=\"cl-btn sm primary\" data-correction=\"" + esc(s.id) + "\" data-name=\"" + esc(s.name || "Student") + "\">Correction/Changes</button>" +
        " <button class=\"cl-btn sm\" data-unverify=\"" + esc(s.id) + "\">Unverify</button></div>";
    }

    if (verStatus === "REJECTED") {
      return "<div style=\"display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;\"><span class=\"cl-badge danger\" aria-label=\"Rejected\">Rejected</span></div>";
    }

    if (pct < MIN_COMPLETION_FOR_VERIFY) {
      return "<div style=\"display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;\">" + viewBtn +
        " <span class=\"cl-state\" style=\"display:inline-block;padding:6px 10px;font-size:12px;\">Profile must reach 50% to approve or reject.</span></div>";
    }

    return "<div style=\"display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;\">" + viewBtn +
      " <button class=\"cl-btn sm primary\" data-verify=\"" + esc(s.id) + "\">Approve</button>" +
      " <button class=\"cl-btn sm danger\" data-reject=\"" + esc(s.id) + "\">Reject</button>" +
      " <button class=\"cl-btn sm\" data-needs=\"" + esc(s.id) + "\">Request changes</button></div>";
  }

  function showCorrectionModal(studentId, studentName, onSend, onClose) {
    var existing = document.getElementById("facultyCorrectionModal");
    if (existing) existing.remove();
    var backdrop = document.createElement("div");
    backdrop.id = "facultyCorrectionModal";
    backdrop.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;z-index:1000;padding:20px;";
    var box = document.createElement("div");
    box.style.cssText = "background:var(--paper,#fff);border-radius:12px;padding:20px;max-width:440px;width:100%;box-shadow:0 20px 40px rgba(15,23,42,0.2);color:var(--text,#0f172a);";
    box.innerHTML = "<h3 style=\"margin:0 0 12px;font-size:16px;\">Send correction/changes to " + esc(studentName) + "</h3>" +
      "<p style=\"margin:0 0 12px;font-size:13px;color:var(--muted,#64748b);\">Your message will be sent to the student as a notification.</p>" +
      "<textarea id=\"facultyCorrectionText\" rows=\"4\" placeholder=\"Describe the changes needed...\" style=\"width:100%;padding:10px;border-radius:8px;border:1px solid var(--border,#e2e8f0);font-size:14px;resize:vertical;margin-bottom:12px;\"></textarea>" +
      "<div style=\"display:flex;gap:10px;justify-content:flex-end;\">" +
      "<button type=\"button\" class=\"cl-btn\" id=\"facultyCorrectionCancel\">Cancel</button>" +
      "<button type=\"button\" class=\"cl-btn primary\" id=\"facultyCorrectionSend\">Send</button>" +
      "</div>";
    backdrop.appendChild(box);
    document.body.appendChild(backdrop);

    function close() {
      backdrop.remove();
      if (onClose) onClose();
    }
    backdrop.addEventListener("click", function (e) { if (e.target === backdrop) close(); });
    box.querySelector("#facultyCorrectionCancel").addEventListener("click", close);
    box.querySelector("#facultyCorrectionSend").addEventListener("click", function () {
      var msg = (box.querySelector("#facultyCorrectionText").value || "").trim();
      if (!msg) { alert("Please enter a message."); return; }
      onSend(msg, close);
    });
  }

  var VERIFY_FILTER_KEY = "campuslink_faculty_verification_status_filter";

  function statusFilterOptions(tab, currentVal) {
    var opts = [
      { v: "", l: "All" },
      { v: "PENDING", l: "Pending" },
      { v: "VERIFIED", l: "Verified" },
      { v: "REJECTED", l: "Rejected" },
    ];
    var def = tab === "verification" ? "PENDING" : "";
    var sel = currentVal !== undefined && currentVal !== null ? String(currentVal) : def;
    return opts.map(function (o) {
      var selected = (o.v === sel) ? " selected" : "";
      return "<option value=\"" + esc(o.v) + "\"" + selected + ">" + esc(o.l) + "</option>";
    }).join("");
  }

  function initialStatusFilter(tab, prevFilterEl) {
    if (tab === "verification") {
      try {
        var stored = sessionStorage.getItem(VERIFY_FILTER_KEY);
        if (stored !== null) return stored;
      } catch (e) { /* ignore */ }
      return "PENDING";
    }
    return prevFilterEl ? prevFilterEl.value : "";
  }

  function attachActionHandlers(wrap, root, tab) {
    wrap.addEventListener("click", async function (e) {
      var t = e.target;
      var id = t.getAttribute("data-verify") || t.getAttribute("data-needs") || t.getAttribute("data-reject") || t.getAttribute("data-unverify");
      var correctionId = t.getAttribute("data-correction");
      var correctionName = t.getAttribute("data-name");
      if (correctionId && correctionName) {
        showCorrectionModal(correctionId, correctionName, async function (message, closeModal) {
          try {
            await window.FacultyApi.sendCorrectionMessage(correctionId, message);
            closeModal();
            await render(root, tab);
            alert("Message sent to student.");
          } catch (err) {
            alert(err.message || "Failed to send.");
          }
        });
        return;
      }
      if (t.getAttribute("data-unverify")) {
        if (!confirm("Are you sure you want to unverify this user?")) return;
        try {
          await window.FacultyApi.unverifyStudent(id);
          await render(root, tab);
        } catch (err) { alert(err.message || "Failed"); }
        return;
      }
      if (!id) return;
      if (t.disabled) return;
      try {
        if (t.getAttribute("data-verify")) await window.FacultyApi.verifyStudent(id, "VERIFIED");
        else if (t.getAttribute("data-needs")) await window.FacultyApi.verifyStudent(id, "NEEDS_CORRECTION");
        else if (t.getAttribute("data-reject")) {
          if (!confirm("This will permanently ban this student. They cannot register or log in with this email again. Continue?")) return;
          await window.FacultyApi.verifyStudent(id, "REJECTED");
        }
        await render(root, tab);
      } catch (err) { alert(err.message || "Failed"); }
    });
  }

  async function render(root, tab) {
    tab = tab || "students";
    var isVerification = tab === "verification";
    var title = isVerification ? "Student Verification Requests" : "My Students";
    var subtitle = isVerification
      ? "Students in your branch awaiting verification (faculty only)."
      : "Department students only.";

    var prevFilter = document.getElementById("facultyStatusFilter");
    var initialFilter = initialStatusFilter(tab, prevFilter);
    var filterHtml = statusFilterOptions(tab, initialFilter);

    root.innerHTML = "<div class=\"cl-page-head\"><div><h1>" + esc(title) + "</h1><p>" + esc(subtitle) + "</p></div><select id=\"facultyStatusFilter\">" + filterHtml + "</select></div><div class=\"cl-state\" id=\"facultyState\">Loading…</div><div id=\"facultyTableWrap\" style=\"display:none;\"></div>";

    var stateEl = document.getElementById("facultyState");
    var wrap = document.getElementById("facultyTableWrap");
    var filterEl = document.getElementById("facultyStatusFilter");
    var statusFilter = filterEl ? filterEl.value : "";

    try {
      var data = await window.FacultyApi.listStudents(statusFilter || undefined);
      var students = (data && data.students) || [];
      stateEl.style.display = "none";
      wrap.style.display = "block";

      if (isVerification) {
        if (!students.length) {
          wrap.innerHTML = "<div class=\"cl-state\">No students match this filter for your branch.</div>";
        } else {
          var cards = students.map(function (s) {
            return "<article class=\"cl-card\" style=\"padding:16px;display:flex;flex-direction:column;gap:8px;\">" +
              "<div style=\"display:flex;justify-content:space-between;align-items:flex-start;gap:10px;\">" +
              "<div><div style=\"font-weight:800;font-size:15px;color:var(--primary-dark,#11224e);\">" + esc(s.name) + "</div>" +
              "<div style=\"font-size:13px;color:var(--muted,#64748b);margin-top:4px;\">Branch: <strong>" + esc(s.branch || "—") + "</strong></div></div>" +
              badge(s.verification_status) + "</div>" +
              "<div style=\"font-size:12px;color:var(--muted,#64748b);\">Profile completion</div>" +
              completionBar(s.profile_completion) +
              buildCardActions(s) +
              "</article>";
          }).join("");
          wrap.innerHTML = "<div style=\"display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;\">" + cards + "</div>";
        }
      } else {
        var headers = "<th>Name</th><th>Branch</th><th>Profile</th><th>Profile Completion %</th><th>Actions</th>";
        var rows = students.map(function (s) {
          var verBadge = badge(s.verification_status);
          var completion = completionBar(s.profile_completion);
          var actions = buildTableActions(s);
          return "<tr><td>" + esc(s.name) + "</td><td>" + esc(s.branch) + "</td><td>" + verBadge + "</td><td>" + completion + "</td><td>" + actions + "</td></tr>";
        }).join("");
        wrap.innerHTML = "<table class=\"cl-table\"><thead><tr>" + headers + "</tr></thead><tbody>" + (rows || "<tr><td colspan=\"5\">No students in your department.</td></tr>") + "</tbody></table>";
      }

      attachActionHandlers(wrap, root, tab);
      if (filterEl) {
        filterEl.addEventListener("change", function () {
          if (tab === "verification") {
            try { sessionStorage.setItem(VERIFY_FILTER_KEY, filterEl.value); } catch (e) { /* ignore */ }
          }
          render(root, tab);
        });
      }
    } catch (e) {
      var msg = (e && e.message) || "Failed to load.";
      if (e && e.status === 403) {
        msg = (e.data && e.data.error) || msg;
      }
      stateEl.textContent = msg;
      stateEl.classList.add("cl-error");
      stateEl.style.display = "block";
      wrap.style.display = "none";
    }
  }

  return { render: render };
})();
