/* Alumni job post: coordinator-style form; POST/PUT /api/alumni/jobs (multipart form_version=2) */

(function () {
  "use strict";

  function qs(id) {
    return document.getElementById(id);
  }

  function authHeaders() {
    var h = {};
    var t = localStorage.getItem("campuslink_token");
    if (t) h["Authorization"] = "Bearer " + t;
    return h;
  }

  function setState(el, msg, isErr) {
    if (!el) return;
    el.textContent = msg || "";
    el.className = "jpf-state" + (isErr ? " jpf-error" : "");
  }

  function buildRoundsUI(container, selectEl, names) {
    if (!container || !selectEl) return;
    var n = parseInt(selectEl.value, 10) || 0;
    container.innerHTML = "";
    names = names || [];
    for (var i = 0; i < n; i++) {
      var row = document.createElement("div");
      row.className = "jpf-round-row";
      row.innerHTML =
        "<span>Round " +
        (i + 1) +
        "</span><input type=\"text\" class=\"jpf-round-name\" data-idx=\"" +
        i +
        "\" placeholder=\"e.g. Aptitude, Technical, HR\" value=\"" +
        (names[i] ? String(names[i]).replace(/"/g, "&quot;") : "") +
        "\" />";
      container.appendChild(row);
    }
  }

  function syncImportantCriteriaPanel() {
    var cb = qs("jpf_important_criteria_enabled");
    var wrap = qs("jpf_important_criteria_wrap");
    var ta = qs("jpf_important_criteria_text");
    if (!wrap) return;
    var on = cb && cb.checked;
    if (on) {
      wrap.classList.add("jpf-important-criteria-panel--open");
      if (ta) ta.disabled = false;
    } else {
      wrap.classList.remove("jpf-important-criteria-panel--open");
      if (ta) ta.disabled = true;
    }
  }

  function validateClient(form) {
    var title = (qs("jpf_title") && qs("jpf_title").value.trim()) || "";
    var company = (qs("jpf_company_name") && qs("jpf_company_name").value.trim()) || "";
    if (!title) return "Job title is required.";
    if (!company) return "Company name is required.";
    if (!form.querySelector('select[name="job_type"]').value) return "Select a job type.";
    if (!form.querySelector('select[name="work_mode"]').value) return "Select a work mode.";
    var loc = (qs("jpf_location") && qs("jpf_location").value.trim()) || "";
    if (!loc) return "Location is required (city & country, or Remote).";
    var about = (qs("jpf_about") && qs("jpf_about").value.trim()) || "";
    if (!about) return "About the role is required.";
    var resp = (qs("jpf_responsibilities") && qs("jpf_responsibilities").value.trim()) || "";
    if (!resp.split(/\n/).map(function (l) { return l.replace(/^[-•*\s]+/, "").trim(); }).filter(Boolean).length) {
      return "Add at least one key responsibility (one per line).";
    }
    var skills = (qs("jpf_required_skills") && qs("jpf_required_skills").value.trim()) || "";
    if (!skills.split(/[,;\n]+/).map(function (s) { return s.trim(); }).filter(Boolean).length) {
      return "Enter at least one required skill (comma-separated).";
    }
    var branches = form.querySelectorAll('input[name="branches_allowed"]:checked');
    if (!branches.length) return "Select at least one eligible branch.";
    var icCb = qs("jpf_important_criteria_enabled");
    var icTa = qs("jpf_important_criteria_text");
    if (icCb && icCb.checked) {
      var icText = (icTa && icTa.value.trim()) || "";
      if (!icText) return "Important criteria text is required when “Mark as Important Job Criteria” is checked.";
    }
    var deadline = (qs("jpf_application_deadline") && qs("jpf_application_deadline").value) || "";
    if (!deadline) return "Application deadline is required.";
    var cg = (qs("jpf_min_cgpa") && qs("jpf_min_cgpa").value.trim()) || "";
    if (cg) {
      var v = parseFloat(cg);
      if (isNaN(v) || v < 0 || v > 10) return "Minimum CGPA must be between 0 and 10.";
    }
    return null;
  }

  function prefillFromJob(f, j) {
    if (!j || !f) return;
    if (qs("jpf_title")) qs("jpf_title").value = j.title || j.role || "";
    if (qs("jpf_company_name")) qs("jpf_company_name").value = j.company_name || j.company || "";
    var jt = j.job_type || j.type || "";
    var wm = j.work_mode || j.mode || "";
    var st = f.querySelector('select[name="job_type"]');
    var sw = f.querySelector('select[name="work_mode"]');
    if (st) st.value = jt;
    if (sw) {
      if (wm === "Onsite") sw.value = "On-site";
      else sw.value = wm;
    }
    if (qs("jpf_location")) qs("jpf_location").value = j.location || "";
    if (qs("jpf_about")) qs("jpf_about").value = (j.about || j.description || "").trim();
    var resp = j.responsibilities;
    if (qs("jpf_responsibilities")) {
      if (Array.isArray(resp) && resp.length) {
        qs("jpf_responsibilities").value = resp.join("\n");
      } else if (!(qs("jpf_responsibilities").value || "").trim()) {
        qs("jpf_responsibilities").value =
          "Replace with concrete responsibilities (one per line). If you had a short legacy post, split tasks into bullets here.";
      }
    }
    var rs = j.required_skills;
    if (qs("jpf_required_skills")) {
      if (Array.isArray(rs) && rs.length) qs("jpf_required_skills").value = rs.join(", ");
      else if (!(qs("jpf_required_skills").value || "").trim()) {
        qs("jpf_required_skills").value = "Replace with required skills (comma-separated).";
      }
    }
    var ps = j.preferred_skills;
    if (Array.isArray(ps) && qs("jpf_preferred_skills")) qs("jpf_preferred_skills").value = ps.join(", ");
    if (qs("jpf_min_cgpa") && j.min_cgpa != null && j.min_cgpa !== "") qs("jpf_min_cgpa").value = String(j.min_cgpa);
    var branches = j.branches_allowed || j.eligible_branches || j.department_allowed || [];
    f.querySelectorAll('input[name="branches_allowed"]').forEach(function (cb) {
      cb.checked = branches.indexOf(cb.value) !== -1;
    });
    if (qs("jpf_batch_year")) qs("jpf_batch_year").value = j.batch_year || "";
    if (qs("jpf_experience")) qs("jpf_experience").value = j.experience || "";
    if (qs("jpf_backlog_criteria")) qs("jpf_backlog_criteria").value = j.backlog_criteria || "";
    if (qs("jpf_other_requirements")) qs("jpf_other_requirements").value = j.other_requirements || "";
    if (qs("jpf_important_criteria_enabled")) qs("jpf_important_criteria_enabled").checked = !!j.important_criteria_enabled;
    if (qs("jpf_important_criteria_text")) qs("jpf_important_criteria_text").value = j.important_criteria_text || "";
    syncImportantCriteriaPanel();
    if (qs("jpf_salary")) qs("jpf_salary").value = j.salary || "";
    var perks = j.perks || [];
    f.querySelectorAll('input[name="perks"]').forEach(function (cb) {
      cb.checked = perks.indexOf(cb.value) !== -1;
    });
    var ad = j.application_deadline || j.deadline || "";
    if (qs("jpf_application_deadline") && ad) qs("jpf_application_deadline").value = ad.length >= 10 ? ad.slice(0, 10) : ad;
    if (qs("jpf_selection_process")) qs("jpf_selection_process").value = j.selection_process || "";
    if (qs("jpf_joining_date") && j.joining_date) qs("jpf_joining_date").value = String(j.joining_date).slice(0, 10);
    var rounds = j.rounds || [];
    var nr = qs("jpf_num_rounds");
    var rc = qs("jpf_rounds_container");
    if (nr && rc) {
      nr.value = String(Math.min(5, Math.max(0, rounds.length)));
      buildRoundsUI(rc, nr, rounds);
    }
  }

  window.AlumniJobPostForm = {
    mount: function (opts) {
      opts = opts || {};
      var editId = opts.editId || null;
      var onCancel = opts.onCancel || function () {};
      var onSuccess = opts.onSuccess || function () {};

      var formEl = document.getElementById("jobPostForm");
      if (!formEl) return;

      var stateEl = qs("jpf_state");
      var submitBtn = qs("jpf_submit");
      var numRounds = qs("jpf_num_rounds");
      var roundsContainer = qs("jpf_rounds_container");
      var roundsJson = qs("jpf_rounds_json");
      var cancelBtn = qs("alumniJpfCancelBtn");

      if (numRounds && roundsContainer) {
        numRounds.addEventListener("change", function () {
          buildRoundsUI(roundsContainer, numRounds, null);
        });
        buildRoundsUI(roundsContainer, numRounds, null);
      }

      var icCb = qs("jpf_important_criteria_enabled");
      if (icCb) {
        icCb.addEventListener("change", syncImportantCriteriaPanel);
        syncImportantCriteriaPanel();
      }

      if (cancelBtn) {
        cancelBtn.addEventListener("click", function () {
          onCancel();
        });
      }

      var pageTitle = qs("jpf_page_title");
      var pageSub = qs("jpf_page_subtitle");

      if (editId) {
        if (pageTitle) pageTitle.textContent = "Edit job posting";
        if (pageSub) pageSub.textContent = "Update role details, eligibility, and attachments.";
        if (submitBtn) submitBtn.textContent = "Save changes";
        fetch("/api/alumni/jobs/" + encodeURIComponent(editId), {
          credentials: "same-origin",
          headers: authHeaders(),
        })
          .then(function (r) {
            return r.json().then(function (d) {
              if (!r.ok) throw new Error((d && d.error) || "Failed to load job");
              return d;
            });
          })
          .then(function (data) {
            var job = data.job || data;
            prefillFromJob(formEl, job);
          })
          .catch(function (e) {
            setState(stateEl, e.message || "Failed to load job", true);
          });
      } else {
        if (pageTitle) pageTitle.textContent = "Create job posting";
        if (pageSub) pageSub.textContent = "Same structured form as coordinator job posts.";
        if (submitBtn) submitBtn.textContent = "Publish job";
      }

      formEl.addEventListener("submit", function (e) {
        e.preventDefault();
        setState(stateEl, "");
        var err = validateClient(formEl);
        if (err) {
          setState(stateEl, err, true);
          return;
        }

        var roundNames = [];
        formEl.querySelectorAll(".jpf-round-name").forEach(function (inp) {
          var t = inp.value.trim();
          if (t) roundNames.push(t);
        });
        if (roundsJson) roundsJson.value = JSON.stringify(roundNames);

        var fd = new FormData(formEl);
        fd.set("form_version", "2");
        if (!editId) {
          var dl = qs("jpf_application_deadline") && qs("jpf_application_deadline").value;
          if (dl) {
            var p = dl.split("-");
            var d = new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
            var today = new Date();
            today.setHours(0, 0, 0, 0);
            if (d <= today) {
              setState(stateEl, "Application deadline must be a future date.", true);
              return;
            }
          }
        }

        var url = "/api/alumni/jobs";
        var method = "POST";
        if (editId) {
          url = "/api/alumni/jobs/" + encodeURIComponent(editId);
          method = "PUT";
        }

        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.textContent = editId ? "Saving…" : "Publishing…";
        }

        var headers = authHeaders();

        fetch(url, { method: method, body: fd, credentials: "same-origin", headers: headers })
          .then(function (r) {
            return r.json().then(function (d) {
              return { ok: r.ok, status: r.status, data: d };
            });
          })
          .then(function (res) {
            if (res.status === 401) {
              window.location.href = "/login";
              return;
            }
            if (!res.ok) throw new Error((res.data && res.data.error) || "Request failed");
            onSuccess();
          })
          .catch(function (er) {
            setState(stateEl, er.message || "Failed to save", true);
          })
          .finally(function () {
            if (submitBtn) {
              submitBtn.disabled = false;
              submitBtn.textContent = editId ? "Save changes" : "Publish job";
            }
          });
      });
    },
  };
})();
