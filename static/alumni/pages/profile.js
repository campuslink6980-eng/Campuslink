/* Alumni profile editor with student-style cards and modals. */

window.AlumniPages = window.AlumniPages || {};

window.AlumniPages.Profile = (function () {
  var MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var WORK_DOMAIN_OPTIONS = ["Backend", "Frontend", "ML", "Product", "HR", "Others"];
  var COUNCILS = ["IEEE", "CSI", "TPC", "E-cell", "IIC", "Alumni Committee", "ACM", "Sports Council", "Student Council", "GDG", "Other"];
  var CLUBS = ["Writer's Club", "Theatre Club", "Singing Club", "Sports Club", "Dancing Club"];

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function authHeaders() {
    var t = localStorage.getItem("campuslink_token");
    var h = {};
    if (t) h.Authorization = "Bearer " + t;
    return h;
  }

  function ensureStyles() {
    if (document.getElementById("alumniProfileEditorStyles")) return;
    var style = document.createElement("style");
    style.id = "alumniProfileEditorStyles";
    style.textContent = [
      ".ap-grid{display:grid;gap:16px;}",
      ".ap-card{background:#fff;border:1px solid #e5e7eb;border-radius:16px;overflow:hidden;box-shadow:0 1px 2px rgba(16,24,40,.06);}",
      ".ap-head{padding:14px 16px;display:flex;justify-content:space-between;align-items:center;gap:12px;border-bottom:1px solid #e5e7eb;}",
      ".ap-head strong{font-size:15px;color:#111827;}",
      ".ap-body{padding:16px;}",
      ".ap-empty{color:#6b7280;font-size:13px;padding:8px 0;}",
      ".ap-item{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;padding:12px;border:1px solid #e5e7eb;border-radius:12px;background:#fff;margin-bottom:10px;}",
      ".ap-item:last-child{margin-bottom:0;}",
      ".ap-item h4{margin:0 0 6px;font-size:14px;color:#111827;}",
      ".ap-sub{font-size:12px;color:#6b7280;line-height:1.45;}",
      ".ap-actions{display:flex;gap:8px;align-items:flex-start;}",
      ".ap-icon{border:none;background:transparent;color:#6b7280;width:32px;height:32px;border-radius:10px;cursor:pointer;font-size:14px;}",
      ".ap-icon:hover{background:#f3f4f6;color:#0a66c2;}",
      ".ap-icon.danger:hover{background:rgba(217,48,37,.08);color:#d93025;}",
      ".ap-summary{display:grid;gap:8px;}",
      ".ap-line{font-size:13px;color:#111827;}",
      ".ap-line.muted{color:#6b7280;}",
      ".ap-photo-grid{display:grid;grid-template-columns:minmax(160px,220px) 1fr;gap:16px;align-items:start;}",
      ".ap-photo-block{display:grid;gap:10px;}",
      ".ap-avatar{width:96px;height:96px;border-radius:50%;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);display:flex;align-items:center;justify-content:center;font-size:30px;font-weight:700;color:#fff;overflow:hidden;}",
      ".ap-avatar img{width:100%;height:100%;object-fit:cover;}",
      ".ap-cover{width:100%;min-height:132px;border-radius:14px;border:1px solid #e5e7eb;background:#f8fafc center/cover no-repeat;display:flex;align-items:center;justify-content:center;color:#94a3b8;font-size:13px;}",
      ".ap-photo-actions{display:flex;gap:8px;flex-wrap:wrap;}",
      ".ap-modal-backdrop{position:fixed;inset:0;background:rgba(15,23,42,.38);display:none;align-items:center;justify-content:center;padding:16px;z-index:60;}",
      ".ap-modal{width:100%;max-width:960px;max-height:calc(100vh - 32px);overflow:auto;background:#fff;border:1px solid #e5e7eb;border-radius:18px;box-shadow:0 30px 80px rgba(0,0,0,.18);}",
      ".ap-modal-head,.ap-modal-foot{padding:14px 16px;display:flex;justify-content:space-between;align-items:center;gap:12px;}",
      ".ap-modal-head{border-bottom:1px solid #e5e7eb;}",
      ".ap-modal-foot{border-top:1px solid #e5e7eb;justify-content:flex-end;}",
      ".ap-modal-body{padding:16px;display:grid;gap:12px;}",
      ".ap-row{display:grid;grid-template-columns:1fr 1fr;gap:12px;}",
      ".ap-form label{display:block;margin:0 0 6px;font-size:13px;font-weight:700;color:#374151;}",
      ".ap-form input,.ap-form select,.ap-form textarea{width:100%;padding:10px 12px;border:1px solid #d1d5db;border-radius:10px;background:#fff;color:#111827;outline:none;box-sizing:border-box;}",
      ".ap-form input:focus,.ap-form select:focus,.ap-form textarea:focus{border-color:rgba(10,102,194,.6);box-shadow:0 0 0 4px rgba(10,102,194,.15);}",
      ".ap-form textarea{min-height:96px;resize:vertical;}",
      ".ap-form input[type='checkbox']{width:18px;height:18px;accent-color:#0a66c2;box-shadow:none;}",
      ".ap-checkbox{display:flex;align-items:center;gap:10px;font-size:14px;color:#374151;}",
      ".ap-date-range{display:flex;gap:12px;align-items:flex-start;}",
      ".ap-date-pair{flex:1;display:grid;grid-template-columns:1fr 1fr;gap:12px;}",
      ".ap-date-end{flex:1;overflow:hidden;transition:max-width .18s ease,opacity .18s ease,transform .18s ease;max-width:360px;opacity:1;transform:translateX(0);}",
      ".ap-date-end.collapsed{max-width:0;opacity:0;transform:translateX(-8px);pointer-events:none;}",
      ".ap-msg{display:none;margin-bottom:14px;padding:10px 12px;border-radius:10px;font-size:13px;}",
      ".ap-msg.ok{display:block;background:rgba(5,118,66,.08);color:#0a7d4f;border:1px solid rgba(5,118,66,.2);}",
      ".ap-msg.err{display:block;background:rgba(217,48,37,.08);color:#d93025;border:1px solid rgba(217,48,37,.18);}",
      ".ap-help{font-size:12px;color:#6b7280;}",
      "@media (max-width:800px){.ap-photo-grid,.ap-row{grid-template-columns:1fr;}.ap-date-range{flex-direction:column;}.ap-date-end,.ap-date-end.collapsed{max-width:none;}}"
    ].join("");
    document.head.appendChild(style);
  }

  function monthNumToLabel(monthStr) {
    var m = parseInt(String(monthStr || ""), 10);
    return m >= 1 && m <= 12 ? MONTH_LABELS[m - 1] : "";
  }

  function renderMonthOptions(selectedMonth) {
    var sel = selectedMonth ? String(selectedMonth).padStart(2, "0") : "";
    return MONTH_LABELS.map(function (label, idx) {
      var value = String(idx + 1).padStart(2, "0");
      return "<option value=\"" + value + "\"" + (sel === value ? " selected" : "") + ">" + label + "</option>";
    }).join("");
  }

  function renderYearOptions(selectedYear) {
    var nowYear = new Date().getFullYear();
    var sel = selectedYear ? String(selectedYear).slice(0, 4) : "";
    var out = "";
    for (var y = nowYear; y >= 1990; y -= 1) {
      out += "<option value=\"" + y + "\"" + (String(y) === sel ? " selected" : "") + ">" + y + "</option>";
    }
    return out;
  }

  function ymToISO(monthStr, yearStr) {
    var mm = parseInt(String(monthStr || ""), 10);
    var yy = parseInt(String(yearStr || "").slice(0, 4), 10);
    if (!mm || mm < 1 || mm > 12 || !yy) return "";
    return yy + "-" + String(mm).padStart(2, "0") + "-01";
  }

  function formatMonthYear(monthStr, yearStr) {
    var m = monthNumToLabel(monthStr);
    var y = String(yearStr || "").trim();
    if (!m && !y) return "";
    if (!m) return y;
    if (!y) return m;
    return m + " " + y;
  }

  function formatRange(startMonth, startYear, endMonth, endYear, current) {
    var start = formatMonthYear(startMonth, startYear);
    if (current) return start ? start + " - Present" : "Present";
    var end = formatMonthYear(endMonth, endYear);
    if (start && end) return start + " - " + end;
    return start || end || "";
  }

  function getPhotoUrl(photo) {
    if (!photo) return "";
    if (typeof photo === "string") return photo;
    return photo.secure_url || photo.url || photo.media_url || "";
  }

  function getInitials(name) {
    if (!name) return "A";
    return String(name)
      .trim()
      .split(/\s+/)
      .map(function (p) { return p.charAt(0).toUpperCase(); })
      .slice(0, 2)
      .join("") || "A";
  }

  function showMsg(root, text, ok) {
    var el = root.querySelector("#alumniProfMsg");
    if (!el) return;
    el.textContent = text || "";
    el.className = "ap-msg " + (ok ? "ok" : "err");
    el.style.display = text ? "block" : "none";
  }

  function withIds(list) {
    return (Array.isArray(list) ? list : []).map(function (item, idx) {
      var out = {};
      Object.keys(item || {}).forEach(function (k) { out[k] = item[k]; });
      out.id = out.id || ("item_" + idx + "_" + Date.now() + "_" + Math.random().toString(36).slice(2, 7));
      return out;
    });
  }

  function normalizeSkills(skills) {
    return (Array.isArray(skills) ? skills : [])
      .map(function (skill, idx) {
        if (typeof skill === "string") {
          return { id: "skill_" + idx + "_" + Date.now(), name: skill, level: "" };
        }
        if (skill && typeof skill === "object") {
          return {
            id: skill.id || ("skill_" + idx + "_" + Date.now()),
            name: skill.name || skill.skill || skill.value || "",
            level: skill.level || ""
          };
        }
        return null;
      })
      .filter(function (x) { return x && x.name; });
  }

  function normalizeData(data) {
    var cloned = {};
    Object.keys(data || {}).forEach(function (k) { cloned[k] = data[k]; });
    cloned.education = withIds(data.education || []);
    cloned.experience = withIds(data.experience || []);
    cloned.projects = withIds(data.projects || []);
    cloned.skills = normalizeSkills(data.skills || []);
    cloned.clubs = withIds(data.clubs || []);
    cloned.certifications = withIds(data.certifications || []);
    cloned.achievements = withIds(data.achievements || []);
    cloned.student_resources = withIds(data.student_resources || []);
    cloned.work_profile = data.work_profile && typeof data.work_profile === "object" ? data.work_profile : {};
    return cloned;
  }

  function cloneStateData(data) {
    return JSON.parse(JSON.stringify(data || {}));
  }

  function requestJson(path, opts) {
    opts = opts || {};
    var headers = opts.headers || authHeaders();
    if (opts.body != null && !opts.isFormData) headers["Content-Type"] = "application/json";
    return fetch(path, {
      method: opts.method || "GET",
      headers: headers,
      credentials: "same-origin",
      body: opts.body == null ? undefined : (opts.isFormData ? opts.body : JSON.stringify(opts.body))
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) throw new Error((data && data.error) || "Request failed");
        return data;
      });
    });
  }

  function saveProfile(state, root, opts) {
    opts = opts || {};
    var payload = {
      full_name: state.data.full_name || "",
      phone: state.data.phone || "",
      headline: state.data.headline || "",
      current_company: state.data.current_company || "",
      designation: state.data.designation || "",
      location: state.data.location || "",
      branch: state.data.branch || "",
      passing_year: state.data.passing_year || "",
      degree: state.data.degree || "",
      bio: state.data.bio || "",
      linkedin_url: state.data.linkedin_url || "",
      portfolio_url: state.data.portfolio_url || "",
      work_profile: {
        organization: (state.data.work_profile || {}).organization || "",
        department: (state.data.work_profile || {}).department || "",
        responsibilities: Array.isArray((state.data.work_profile || {}).responsibilities) ? state.data.work_profile.responsibilities : [],
        technologies_used: (state.data.work_profile || {}).technologies_used || "",
        work_domain: (state.data.work_profile || {}).work_domain || ""
      },
      student_resources: (state.data.student_resources || []).map(function (item) {
        return {
          id: item.id,
          description: item.description || "",
          links: Array.isArray(item.links) ? item.links : [],
          media_urls: Array.isArray(item.media_urls) ? item.media_urls : []
        };
      }),
      education: state.data.education || [],
      experience_timeline: [],
      experience: state.data.experience || [],
      projects: state.data.projects || [],
      skills: (state.data.skills || []).map(function (item) {
        return { id: item.id, name: item.name || "", level: item.level || "" };
      }),
      clubs: state.data.clubs || [],
      certifications: state.data.certifications || [],
      achievements: state.data.achievements || []
    };
    return AlumniApi.profilePut(payload).then(function (res) {
      showMsg(root, opts.message || "Profile saved.", true);
      state.data.profile_completion = res && res.profile_completion != null ? res.profile_completion : state.data.profile_completion;
      return res;
    }).catch(function (err) {
      showMsg(root, err.message || "Save failed", false);
      throw err;
    });
  }

  function listCard(title, bodyId, addKey, editMode) {
    return (
      "<section class=\"ap-card\"><div class=\"ap-head\"><strong>" + escapeHtml(title) + "</strong>" +
      (editMode ? "<button type=\"button\" class=\"cl-btn primary\" data-add=\"" + addKey + "\">+ Add</button>" : "") +
      "</div><div class=\"ap-body\" id=\"" + bodyId + "\"></div></section>"
    );
  }

  function summaryLines(lines) {
    var rows = lines.filter(Boolean);
    if (!rows.length) return "<div class=\"ap-empty\">No details added yet.</div>";
    return "<div class=\"ap-summary\">" + rows.map(function (line) { return "<div class=\"ap-line\">" + escapeHtml(line) + "</div>"; }).join("") + "</div>";
  }

  function renderLayout(root, data, editMode) {
    var photoUrl = getPhotoUrl(data.profile_photo);
    var coverUrl = getPhotoUrl(data.cover_photo);
    root.innerHTML =
      "<div class=\"cl-page-head\"><div><h1>" + (editMode ? "Edit profile" : "Profile") + "</h1><p>Manage your alumni profile with the same add/edit UI style used for profile sections.</p></div>" +
      "<button type=\"button\" class=\"cl-btn primary\" id=\"alumniProfToggle\">" + (editMode ? "View profile" : "Edit profile") + "</button></div>" +
      "<div id=\"alumniProfMsg\" class=\"ap-msg\"></div>" +
      "<div class=\"ap-grid\">" +
      "<section class=\"ap-card\"><div class=\"ap-head\"><strong>Photos</strong></div><div class=\"ap-body\">" +
      "<div class=\"ap-photo-grid\">" +
      "<div class=\"ap-photo-block\"><div class=\"ap-avatar\" id=\"alumniPhotoPreview\">" +
      (photoUrl ? "<img src=\"" + escapeHtml(photoUrl) + "\" alt=\"Profile photo\" />" : escapeHtml(getInitials(data.full_name))) +
      "</div>" +
      (editMode ? "<div class=\"ap-photo-actions\"><input type=\"file\" id=\"alumniPhotoInput\" accept=\".jpg,.jpeg,.png\" style=\"display:none;\" /><button type=\"button\" class=\"cl-btn primary\" id=\"alumniPhotoUploadBtn\">Upload profile photo</button>" + (photoUrl ? "<button type=\"button\" class=\"cl-btn\" id=\"alumniPhotoRemoveBtn\">Remove</button>" : "") + "</div>" : "") +
      "</div>" +
      "<div class=\"ap-photo-block\"><div class=\"ap-cover\" id=\"alumniCoverPreview\" style=\"" + (coverUrl ? "background-image:url('" + escapeHtml(coverUrl) + "');" : "") + "\">" + (coverUrl ? "" : "No cover photo") + "</div>" +
      (editMode ? "<div class=\"ap-photo-actions\"><input type=\"file\" id=\"alumniCoverInput\" accept=\".jpg,.jpeg,.png\" style=\"display:none;\" /><button type=\"button\" class=\"cl-btn primary\" id=\"alumniCoverUploadBtn\">Upload cover photo</button>" + (coverUrl ? "<button type=\"button\" class=\"cl-btn\" id=\"alumniCoverRemoveBtn\">Remove</button>" : "") + "</div>" : "") +
      "</div></div></div></section>" +
      "<section class=\"ap-card\"><div class=\"ap-head\"><strong>Basic information</strong>" + (editMode ? "<button type=\"button\" class=\"cl-btn primary\" data-open=\"basic\">Edit</button>" : "") + "</div><div class=\"ap-body\" id=\"basicSummary\"></div></section>" +
      "<section class=\"ap-card\"><div class=\"ap-head\"><strong>Work profile</strong>" + (editMode ? "<button type=\"button\" class=\"cl-btn primary\" data-open=\"work\">Edit</button>" : "") + "</div><div class=\"ap-body\" id=\"workSummary\"></div></section>" +
      "<section class=\"ap-card\"><div class=\"ap-head\"><strong>About</strong>" + (editMode ? "<button type=\"button\" class=\"cl-btn primary\" data-open=\"about\">Edit</button>" : "") + "</div><div class=\"ap-body\" id=\"aboutSummary\"></div></section>" +
      "<section class=\"ap-card\"><div class=\"ap-head\"><strong>Notes / resources for future student</strong>" + (editMode ? "<button type=\"button\" class=\"cl-btn primary\" data-add=\"resources\">+ Add resource block</button>" : "") + "</div><div class=\"ap-body\" id=\"resourceList\"></div></section>" +
      listCard("Education", "educationList", "education", editMode) +
      listCard("Experience (internships / work)", "experienceList", "experience", editMode) +
      listCard("Projects", "projectsList", "projects", editMode) +
      listCard("Skills", "skillsList", "skills", editMode) +
      listCard("Councils / Extra-curricular", "clubsList", "clubs", editMode) +
      listCard("Certifications", "certificationsList", "certifications", editMode) +
      listCard("Achievements & Awards", "achievementsList", "achievements", editMode) +
      "</div>" +
      "<div class=\"ap-modal-backdrop\" id=\"alumniModalBackdrop\" role=\"dialog\" aria-modal=\"true\"><div class=\"ap-modal\"><div class=\"ap-modal-head\"><strong id=\"alumniModalTitle\">Edit</strong><button type=\"button\" class=\"cl-btn\" id=\"alumniModalClose\">Close</button></div><div class=\"ap-modal-body ap-form\" id=\"alumniModalBody\"></div><div class=\"ap-modal-foot\"><button type=\"button\" class=\"cl-btn\" id=\"alumniModalCancel\">Cancel</button><button type=\"button\" class=\"cl-btn primary\" id=\"alumniModalSave\">Save</button></div></div></div>";
  }

  function renderList(container, section, items, titleField, subtitleBuilder, editMode) {
    if (!container) return;
    if (!items || !items.length) {
      container.innerHTML = "<div class=\"ap-empty\">No records yet.</div>";
      return;
    }
    container.innerHTML = items.map(function (item) {
      var title = item[titleField] || item.school || item.company || item.name || item.role || "Entry";
      var subtitle = subtitleBuilder(item) || [];
      if (!Array.isArray(subtitle)) subtitle = String(subtitle).split(" · ");
      subtitle = subtitle.filter(Boolean);
      return (
        "<div class=\"ap-item\"><div><h4>" + escapeHtml(title) + "</h4>" +
        (subtitle.length ? subtitle.map(function (line) { return "<div class=\"ap-sub\">" + escapeHtml(line) + "</div>"; }).join("") : "<div class=\"ap-sub\">-</div>") +
        "</div>" +
        (editMode ? "<div class=\"ap-actions\"><button type=\"button\" class=\"ap-icon\" data-edit=\"" + section + "\" data-id=\"" + escapeHtml(item.id) + "\" aria-label=\"Edit\">&#9998;</button><button type=\"button\" class=\"ap-icon danger\" data-del=\"" + section + "\" data-id=\"" + escapeHtml(item.id) + "\" aria-label=\"Delete\">&#128465;</button></div>" : "") +
        "</div>"
      );
    }).join("");
  }

  function findItem(state, section, id) {
    var arr = state.data[section] || [];
    for (var i = 0; i < arr.length; i += 1) {
      if (String(arr[i].id) === String(id)) return arr[i];
    }
    return null;
  }

  function openModal(state, root, ctx) {
    state.modalCtx = ctx;
    var backdrop = root.querySelector("#alumniModalBackdrop");
    var title = root.querySelector("#alumniModalTitle");
    var body = root.querySelector("#alumniModalBody");
    if (!backdrop || !body || !title) return;
    backdrop.style.display = "flex";
    body.innerHTML = "";

    var item = ctx.item || {};
    var section = ctx.section;
    var mode = ctx.mode || "edit";

    if (section === "basic") {
      title.textContent = "Edit Basic information";
      body.innerHTML =
        "<div class=\"ap-row\"><div><label>Full name</label><input id=\"f_full_name\" value=\"" + escapeHtml(state.data.full_name || "") + "\" /></div><div><label>Email (read-only)</label><input id=\"f_email\" value=\"" + escapeHtml(state.data.email || "") + "\" readonly /></div></div>" +
        "<div class=\"ap-row\"><div><label>Headline</label><input id=\"f_headline\" value=\"" + escapeHtml(state.data.headline || "") + "\" /></div><div><label>Phone</label><input id=\"f_phone\" value=\"" + escapeHtml(state.data.phone || "") + "\" /></div></div>" +
        "<div class=\"ap-row\"><div><label>Current company</label><input id=\"f_current_company\" value=\"" + escapeHtml(state.data.current_company || "") + "\" /></div><div><label>Current role</label><input id=\"f_designation\" value=\"" + escapeHtml(state.data.designation || "") + "\" /></div></div>" +
        "<div class=\"ap-row\"><div><label>Location</label><input id=\"f_location\" value=\"" + escapeHtml(state.data.location || "") + "\" /></div><div><label>Branch</label><input id=\"f_branch\" value=\"" + escapeHtml(state.data.branch || "") + "\" /></div></div>" +
        "<div class=\"ap-row\"><div><label>Passing year</label><input id=\"f_passing_year\" value=\"" + escapeHtml(state.data.passing_year || "") + "\" /></div><div><label>Degree</label><input id=\"f_degree\" value=\"" + escapeHtml(state.data.degree || "") + "\" /></div></div>";
      return;
    }

    if (section === "work") {
      var wp = state.data.work_profile || {};
      title.textContent = "Edit Work profile";
      body.innerHTML =
        "<div class=\"ap-row\"><div><label>Organization</label><input id=\"f_wp_org\" value=\"" + escapeHtml(wp.organization || "") + "\" /></div><div><label>Department / team</label><input id=\"f_wp_dept\" value=\"" + escapeHtml(wp.department || "") + "\" /></div></div>" +
        "<div><label>Key responsibilities (one per line)</label><textarea id=\"f_wp_resp\">" + escapeHtml((wp.responsibilities || []).join("\n")) + "</textarea></div>" +
        "<div class=\"ap-row\"><div><label>Technologies used</label><input id=\"f_wp_tech\" value=\"" + escapeHtml(wp.technologies_used || "") + "\" /></div><div><label>Work domain</label><select id=\"f_wp_domain\"><option value=\"\">Type your work domain</option>" +
        WORK_DOMAIN_OPTIONS.map(function (opt) { return "<option value=\"" + escapeHtml(opt) + "\"" + (wp.work_domain === opt ? " selected" : "") + ">" + escapeHtml(opt) + "</option>"; }).join("") +
        "</select></div></div>";
      return;
    }

    if (section === "about") {
      title.textContent = "Edit About";
      body.innerHTML =
        "<div><label>Bio</label><textarea id=\"f_bio\">" + escapeHtml(state.data.bio || "") + "</textarea></div>" +
        "<div class=\"ap-row\"><div><label>LinkedIn</label><input id=\"f_linkedin_url\" value=\"" + escapeHtml(state.data.linkedin_url || "") + "\" /></div><div><label>Portfolio</label><input id=\"f_portfolio_url\" value=\"" + escapeHtml(state.data.portfolio_url || "") + "\" /></div></div>";
      return;
    }

    if (section === "resources") {
      title.textContent = (mode === "add" ? "Add" : "Edit") + " resource block";
      body.innerHTML =
        "<div><label>Notes / resource</label><textarea id=\"f_res_desc\" placeholder=\"Add notes, guidance, or useful references for students...\">" + escapeHtml(item.description || "") + "</textarea></div>" +
        "<div><label>Links (one per line)</label><textarea id=\"f_res_links\" placeholder=\"https://...\nhttps://...\">" + escapeHtml(Array.isArray(item.links) ? item.links.join("\n") : "") + "</textarea></div>" +
        "<div><label>Media URLs (one per line)</label><textarea id=\"f_res_media\" placeholder=\"https://...\">" + escapeHtml(Array.isArray(item.media_urls) ? item.media_urls.join("\n") : "") + "</textarea></div>" +
        "<div class=\"ap-row\"><div>" +
        "<label>Upload media (Word/PDF/Images)</label>" +
        "<input id=\"f_res_upload\" type=\"file\" accept=\".pdf,.doc,.docx,.jpg,.jpeg,.png\" />" +
        "<div class=\"ap-help\">Upload adds the returned URL into the Media URLs box.</div>" +
        "</div></div>" +
        "<div class=\"ap-help\">You can also paste existing URLs manually.</div>";
      var resUpload = body.querySelector("#f_res_upload");
      if (resUpload) {
        resUpload.addEventListener("change", function () {
          if (!resUpload.files || !resUpload.files[0]) return;
          AlumniApi.profileNotesMediaUpload(resUpload.files[0])
            .then(function (out) {
              var ta = body.querySelector("#f_res_media");
              var cur = (ta.value || "").trim();
              var next = (cur ? cur + "\n" : "") + (out.url || "");
              ta.value = next.trim() + "\n";
              showMsg(root, "Uploaded. Media URL added.", true);
            })
            .catch(function (e) {
              showMsg(root, (e && e.message) || "Upload failed", false);
            })
            .finally(function () {
              resUpload.value = "";
            });
        });
      }
      return;
    }

    if (section === "education") {
      var eduStartMonth = item.start_month || (item.start_date ? item.start_date.slice(5, 7) : "");
      var eduStartYear = item.start_year || (item.start_date ? item.start_date.slice(0, 4) : "");
      var eduEndMonth = item.end_month || (item.end_date ? item.end_date.slice(5, 7) : "");
      var eduEndYear = item.end_year || (item.end_date ? item.end_date.slice(0, 4) : "");
      var eduCurrent = !!item.current || (!item.end_date && !item.end_year);
      var eduDegree = item.degree || "";
      var eduBoard = item.board || item.field || "";
      var eduField = item.field_of_study || item.field || "";
      title.textContent = (mode === "add" ? "Add " : "Edit ") + "Education";
      body.innerHTML =
        "<div class=\"ap-row\"><div><label>School / College / University Name</label><input id=\"f_school\" value=\"" + escapeHtml(item.school || "") + "\" /></div><div><label>Degree</label><select id=\"f_degree_select\"><option value=\"SSC\"" + (eduDegree === "SSC" ? " selected" : "") + ">Secondary School Certificate (SSC)</option><option value=\"HSC\"" + (eduDegree === "HSC" ? " selected" : "") + ">Higher Secondary Certificate (HSC)</option><option value=\"Intermediate\"" + (eduDegree === "Intermediate" ? " selected" : "") + ">Intermediate</option><option value=\"Diploma\"" + (eduDegree === "Diploma" ? " selected" : "") + ">Diploma</option><option value=\"Btech\"" + (eduDegree === "Btech" ? " selected" : "") + ">Btech</option></select></div></div>" +
        "<div class=\"ap-row\" id=\"eduBoardWrap\" style=\"display:" + (["SSC", "HSC", "Intermediate"].indexOf(eduDegree) >= 0 ? "grid" : "none") + ";\"><div><label>Board</label><input id=\"f_board\" value=\"" + escapeHtml(eduBoard) + "\" /></div></div>" +
        "<div class=\"ap-row\" id=\"eduFieldWrap\" style=\"display:" + (["Diploma", "Btech"].indexOf(eduDegree) >= 0 ? "grid" : "none") + ";\"><div><label>Field of Study</label><input id=\"f_field_of_study\" value=\"" + escapeHtml(eduField) + "\" /></div></div>" +
        "<div class=\"ap-row\"><div><label>CGPA or Percentage</label><input id=\"f_cgpa\" value=\"" + escapeHtml(item.cgpa || "") + "\" /></div><div><label>Duration</label><label class=\"ap-checkbox\"><input id=\"f_edu_current\" type=\"checkbox\"" + (eduCurrent ? " checked" : "") + " />I am currently studying here</label></div></div>" +
        "<div class=\"ap-date-range\"><div class=\"ap-date-pair\"><div><label>Start Month</label><select id=\"f_start_month\">" + renderMonthOptions(eduStartMonth) + "</select></div><div><label>Start Year</label><select id=\"f_start_year\">" + renderYearOptions(eduStartYear) + "</select></div></div><div id=\"eduEndWrap\" class=\"ap-date-end" + (eduCurrent ? " collapsed" : "") + "\"><div class=\"ap-date-pair\"><div><label>End Month</label><select id=\"f_end_month\">" + renderMonthOptions(eduEndMonth) + "</select></div><div><label>End Year</label><select id=\"f_end_year\">" + renderYearOptions(eduEndYear) + "</select></div></div></div></div>";
      var degreeSelect = body.querySelector("#f_degree_select");
      var boardWrap = body.querySelector("#eduBoardWrap");
      var fieldWrap = body.querySelector("#eduFieldWrap");
      var eduCurrentEl = body.querySelector("#f_edu_current");
      var eduEndWrap = body.querySelector("#eduEndWrap");
      degreeSelect.addEventListener("change", function () {
        var d = degreeSelect.value;
        boardWrap.style.display = ["SSC", "HSC", "Intermediate"].indexOf(d) >= 0 ? "grid" : "none";
        fieldWrap.style.display = ["Diploma", "Btech"].indexOf(d) >= 0 ? "grid" : "none";
      });
      eduCurrentEl.addEventListener("change", function () {
        eduEndWrap.classList.toggle("collapsed", eduCurrentEl.checked);
      });
      return;
    }

    if (section === "experience") {
      var expStartMonth = item.start_month || (item.start_date ? item.start_date.slice(5, 7) : "");
      var expStartYear = item.start_year || (item.start_date ? item.start_date.slice(0, 4) : "");
      var expEndMonth = item.end_month || (item.end_date ? item.end_date.slice(5, 7) : "");
      var expEndYear = item.end_year || (item.end_date ? item.end_date.slice(0, 4) : "");
      var expCurrent = !!item.current || (!item.end_date && !item.end_year);
      title.textContent = (mode === "add" ? "Add " : "Edit ") + "Experience";
      body.innerHTML =
        "<div class=\"ap-row\"><div><label>Company Name</label><input id=\"f_company\" value=\"" + escapeHtml(item.company || "") + "\" /></div><div><label>Role / Title</label><input id=\"f_role\" value=\"" + escapeHtml(item.role || "") + "\" /></div></div>" +
        "<div><label class=\"ap-checkbox\"><input id=\"f_current_role\" type=\"checkbox\"" + (expCurrent ? " checked" : "") + " />I am currently working in this role</label></div>" +
        "<div class=\"ap-row\"><div><label>Employment Type</label><select id=\"f_employment_type\"><option value=\"\">Select</option><option value=\"Full-time\"" + (item.employment_type === "Full-time" ? " selected" : "") + ">Full-time</option><option value=\"Part-time\"" + (item.employment_type === "Part-time" ? " selected" : "") + ">Part-time</option><option value=\"Self-employed\"" + (item.employment_type === "Self-employed" ? " selected" : "") + ">Self-employed</option><option value=\"Freelance\"" + (item.employment_type === "Freelance" ? " selected" : "") + ">Freelance</option><option value=\"Internship\"" + (item.employment_type === "Internship" ? " selected" : "") + ">Internship</option><option value=\"Apprenticeship\"" + (item.employment_type === "Apprenticeship" ? " selected" : "") + ">Apprenticeship</option></select></div><div><label>Location Type</label><select id=\"f_location_type\"><option value=\"\">Select</option><option value=\"On-site\"" + (item.location_type === "On-site" ? " selected" : "") + ">On-site</option><option value=\"Hybrid\"" + (item.location_type === "Hybrid" ? " selected" : "") + ">Hybrid</option><option value=\"Remote\"" + (item.location_type === "Remote" ? " selected" : "") + ">Remote</option></select></div></div>" +
        "<div class=\"ap-date-range\"><div class=\"ap-date-pair\"><div><label>Start Month</label><select id=\"f_start_month\">" + renderMonthOptions(expStartMonth) + "</select></div><div><label>Start Year</label><select id=\"f_start_year\">" + renderYearOptions(expStartYear) + "</select></div></div><div id=\"expEndWrap\" class=\"ap-date-end" + (expCurrent ? " collapsed" : "") + "\"><div class=\"ap-date-pair\"><div><label>End Month</label><select id=\"f_end_month\">" + renderMonthOptions(expEndMonth) + "</select></div><div><label>End Year</label><select id=\"f_end_year\">" + renderYearOptions(expEndYear) + "</select></div></div></div></div>" +
        "<div class=\"ap-row\"><div><label>Location</label><input id=\"f_exp_location\" value=\"" + escapeHtml(item.location || "") + "\" /></div><div><label>Skills (comma separated)</label><input id=\"f_exp_skills\" value=\"" + escapeHtml(Array.isArray(item.skills) ? item.skills.join(", ") : (item.skills || "")) + "\" placeholder=\"e.g., Python, React, MongoDB\" /></div></div>" +
        "<div><label>Description (0-1000 characters)</label><textarea id=\"f_exp_description\" maxlength=\"1000\">" + escapeHtml(item.description || "") + "</textarea></div>" +
        "<div style=\"margin-top:10px;\">" +
        "<label>Upload experience proof (image)</label>" +
        (mode === "edit" && item.id ? "<input id=\"f_exp_media\" type=\"file\" accept=\".jpg,.jpeg,.png\" />" : "<div class=\"ap-help\">Save this entry first, then edit to upload media.</div>") +
        (item.media_url ? "<div class=\"ap-help\">Current: <a href=\"" + escapeHtml(item.media_url) + "\" target=\"_blank\" rel=\"noopener\">" + escapeHtml(item.media_url) + "</a></div>" : "") +
        "</div>";
      var expCurrentEl = body.querySelector("#f_current_role");
      var expEndWrap = body.querySelector("#expEndWrap");
      expCurrentEl.addEventListener("change", function () {
        expEndWrap.classList.toggle("collapsed", expCurrentEl.checked);
      });
      var expMedia = body.querySelector("#f_exp_media");
      if (expMedia) {
        expMedia.addEventListener("change", function () {
          if (!expMedia.files || !expMedia.files[0]) return;
          AlumniApi.profileExperienceMediaUpload(item.id, expMedia.files[0])
            .then(function (out) {
              item.media_url = out.url;
              showMsg(root, "Experience proof uploaded.", true);
            })
            .catch(function (e) {
              showMsg(root, (e && e.message) || "Upload failed", false);
            })
            .finally(function () {
              expMedia.value = "";
            });
        });
      }
      return;
    }

    if (section === "projects") {
      title.textContent = (mode === "add" ? "Add " : "Edit ") + "Projects";
      body.innerHTML =
        "<div class=\"ap-row\"><div><label>Project Name</label><input id=\"f_name\" value=\"" + escapeHtml(item.name || "") + "\" /></div><div><label>Tech Stack</label><input id=\"f_tech_stack\" value=\"" + escapeHtml(item.tech_stack || "") + "\" placeholder=\"e.g., Python, React, MongoDB\" /></div></div>" +
        "<div class=\"ap-row\"><div><label>Link</label><input id=\"f_link\" value=\"" + escapeHtml(item.link || "") + "\" placeholder=\"GitHub or live demo URL\" /></div><div><label>Your Role</label><input id=\"f_proj_role\" value=\"" + escapeHtml(item.role || "") + "\" placeholder=\"e.g., Lead Developer\" /></div></div>" +
        "<div><label>Description</label><textarea id=\"f_description\">" + escapeHtml(item.description || "") + "</textarea></div>" +
        "<div style=\"margin-top:10px;\">" +
        "<label>Upload project media (image/video)</label>" +
        (mode === "edit" && item.id ? "<input id=\"f_proj_media\" type=\"file\" accept=\".jpg,.jpeg,.png,.mp4\" />" : "<div class=\"ap-help\">Save this entry first, then edit to upload media.</div>") +
        "</div>" +
        "<div class=\"ap-help\" id=\"projMediaHelp\">" +
        ((item.media_urls && item.media_urls.length) ? ("Images: " + escapeHtml(item.media_urls.join(", "))) : "") +
        (item.project_video_url ? ((item.media_urls && item.media_urls.length) ? "<br>" : "") + "Video: " + escapeHtml(item.project_video_url) : "") +
        "</div>";
      var projMedia = body.querySelector("#f_proj_media");
      if (projMedia) {
        projMedia.addEventListener("change", function () {
          if (!projMedia.files || !projMedia.files[0]) return;
          AlumniApi.profileProjectMediaUpload(item.id, projMedia.files[0])
            .then(function (out) {
              if (out.media_type === "video") {
                item.project_video_url = out.url;
              } else {
                if (!Array.isArray(item.media_urls)) item.media_urls = [];
                item.media_urls.push(out.url);
              }
              showMsg(root, "Project media uploaded.", true);
            })
            .catch(function (e) {
              showMsg(root, (e && e.message) || "Upload failed", false);
            })
            .finally(function () {
              projMedia.value = "";
            });
        });
      }
      return;
    }

    if (section === "skills") {
      title.textContent = (mode === "add" ? "Add " : "Edit ") + "Skills";
      body.innerHTML =
        "<div class=\"ap-row\"><div><label>Skill</label><input id=\"f_name\" value=\"" + escapeHtml(item.name || "") + "\" placeholder=\"e.g., Python, Data Analysis\" /></div><div><label>Level</label><select id=\"f_level\"><option value=\"\">Select level</option><option value=\"Beginner\"" + (item.level === "Beginner" ? " selected" : "") + ">Beginner</option><option value=\"Intermediate\"" + (item.level === "Intermediate" ? " selected" : "") + ">Intermediate</option><option value=\"Advanced\"" + (item.level === "Advanced" ? " selected" : "") + ">Advanced</option></select></div></div>";
      return;
    }

    if (section === "clubs") {
      var clubCurrent = !!item.current || (!item.end_date && !item.end_year);
      var clubStartMonth = item.start_month || (item.start_date ? item.start_date.slice(5, 7) : "");
      var clubStartYear = item.start_year || (item.start_date ? item.start_date.slice(0, 4) : "");
      var clubEndMonth = item.end_month || (item.end_date ? item.end_date.slice(5, 7) : "");
      var clubEndYear = item.end_year || (item.end_date ? item.end_date.slice(0, 4) : "");
      var inferredName = item.name || "";
      var inferredType = item.type || (COUNCILS.indexOf(inferredName) >= 0 ? "Councils" : CLUBS.indexOf(inferredName) >= 0 ? "Clubs" : "Organisation");
      var councilSel = COUNCILS.indexOf(inferredName) >= 0 ? inferredName : "Other";
      var clubSel = CLUBS.indexOf(inferredName) >= 0 ? inferredName : "Writer's Club";
      title.textContent = (mode === "add" ? "Add " : "Edit ") + "Councils / Extra-curricular";
      body.innerHTML =
        "<div class=\"ap-row\"><div><label>Type</label><select id=\"f_club_type\"><option value=\"Clubs\"" + (inferredType === "Clubs" ? " selected" : "") + ">Clubs</option><option value=\"Councils\"" + (inferredType === "Councils" ? " selected" : "") + ">Councils</option><option value=\"Organisation\"" + (inferredType === "Organisation" ? " selected" : "") + ">Organisation</option></select></div><div><label>Role</label><input id=\"f_club_role\" value=\"" + escapeHtml(item.role || "") + "\" placeholder=\"e.g., Core Member, Secretary\" /></div></div>" +
        "<div id=\"f_council_wrap\" class=\"ap-row\" style=\"display:" + (inferredType === "Councils" ? "grid" : "none") + ";\"><div><label>Council</label><select id=\"f_council_option\">" + COUNCILS.map(function (opt) { return "<option value=\"" + escapeHtml(opt) + "\"" + (councilSel === opt ? " selected" : "") + ">" + escapeHtml(opt) + "</option>"; }).join("") + "</select><div id=\"f_council_other_wrap\" style=\"margin-top:10px;display:" + (councilSel === "Other" ? "block" : "none") + ";\"><label>Other council name</label><input id=\"f_council_other_name\" value=\"" + escapeHtml(inferredType === "Councils" && councilSel === "Other" ? inferredName : "") + "\" /></div></div></div>" +
        "<div id=\"f_club_option_wrap\" class=\"ap-row\" style=\"display:" + (inferredType === "Clubs" ? "grid" : "none") + ";\"><div><label>Club</label><select id=\"f_club_option\">" + CLUBS.map(function (opt) { return "<option value=\"" + escapeHtml(opt) + "\"" + (clubSel === opt ? " selected" : "") + ">" + escapeHtml(opt) + "</option>"; }).join("") + "</select><div id=\"f_sport_name_wrap\" style=\"margin-top:10px;display:" + (clubSel === "Sports Club" ? "block" : "none") + ";\"><label>Sport name</label><input id=\"f_sport_name\" value=\"" + escapeHtml(item.sport_name || "") + "\" placeholder=\"e.g., Cricket\" /></div></div></div>" +
        "<div id=\"f_org_wrap\" class=\"ap-row\" style=\"display:" + (inferredType === "Organisation" ? "grid" : "none") + ";\"><div><label>Organisation Name</label><input id=\"f_org_name\" value=\"" + escapeHtml(inferredType === "Organisation" ? inferredName : "") + "\" placeholder=\"e.g., IEEE Student Branch\" /></div></div>" +
        "<div class=\"ap-row\"><div><label>Duration</label><label class=\"ap-checkbox\"><input id=\"f_club_current\" type=\"checkbox\"" + (clubCurrent ? " checked" : "") + " />I am currently in this role</label></div></div>" +
        "<div class=\"ap-date-range\"><div class=\"ap-date-pair\"><div><label>Start Month</label><select id=\"f_club_start_month\">" + renderMonthOptions(clubStartMonth) + "</select></div><div><label>Start Year</label><select id=\"f_club_start_year\">" + renderYearOptions(clubStartYear) + "</select></div></div><div id=\"clubEndWrap\" class=\"ap-date-end" + (clubCurrent ? " collapsed" : "") + "\"><div class=\"ap-date-pair\"><div><label>End Month</label><select id=\"f_club_end_month\">" + renderMonthOptions(clubEndMonth) + "</select></div><div><label>End Year</label><select id=\"f_club_end_year\">" + renderYearOptions(clubEndYear) + "</select></div></div></div></div>" +
        "<div><label>Description</label><textarea id=\"f_club_description\">" + escapeHtml(item.description || "") + "</textarea></div>";
      var typeEl = body.querySelector("#f_club_type");
      var currentEl = body.querySelector("#f_club_current");
      var councilOptEl = body.querySelector("#f_council_option");
      var clubOptEl = body.querySelector("#f_club_option");
      function syncClubVisibility() {
        body.querySelector("#f_council_wrap").style.display = typeEl.value === "Councils" ? "grid" : "none";
        body.querySelector("#f_club_option_wrap").style.display = typeEl.value === "Clubs" ? "grid" : "none";
        body.querySelector("#f_org_wrap").style.display = typeEl.value === "Organisation" ? "grid" : "none";
      }
      function syncCouncilOther() {
        body.querySelector("#f_council_other_wrap").style.display = councilOptEl.value === "Other" ? "block" : "none";
      }
      function syncSportName() {
        body.querySelector("#f_sport_name_wrap").style.display = clubOptEl.value === "Sports Club" ? "block" : "none";
      }
      function syncClubEnd() {
        body.querySelector("#clubEndWrap").classList.toggle("collapsed", currentEl.checked);
      }
      typeEl.addEventListener("change", syncClubVisibility);
      councilOptEl.addEventListener("change", syncCouncilOther);
      clubOptEl.addEventListener("change", syncSportName);
      currentEl.addEventListener("change", syncClubEnd);
      return;
    }

    if (section === "certifications") {
      var issueMonth = item.issue_month || (item.issue_date ? item.issue_date.slice(5, 7) : "");
      var issueYear = item.issue_year || (item.issue_date ? item.issue_date.slice(0, 4) : "");
      var hasExpiry = !!item.expiry_month || !!item.expiry_year || !!item.expiry_date;
      var expiryMonth = item.expiry_month || (item.expiry_date ? item.expiry_date.slice(5, 7) : "");
      var expiryYear = item.expiry_year || (item.expiry_date ? item.expiry_date.slice(0, 4) : "");
      title.textContent = (mode === "add" ? "Add " : "Edit ") + "Certifications";
      body.innerHTML =
        "<div class=\"ap-row\"><div><label>Certification Name</label><input id=\"f_name\" value=\"" + escapeHtml(item.name || "") + "\" /></div><div><label>Issuing Organization</label><input id=\"f_issuer\" value=\"" + escapeHtml(item.issuer || "") + "\" placeholder=\"e.g., Coursera, Microsoft\" /></div></div>" +
        "<div class=\"ap-row\"><div><label>Issue Month</label><select id=\"f_issue_month\">" + renderMonthOptions(issueMonth) + "</select></div><div><label>Issue Year</label><select id=\"f_issue_year\">" + renderYearOptions(issueYear) + "</select></div></div>" +
        "<div><label class=\"ap-checkbox\"><input id=\"f_has_expiry\" type=\"checkbox\"" + (hasExpiry ? " checked" : "") + " />Expiry Date (optional)</label></div>" +
        "<div id=\"expiryWrap\" style=\"display:" + (hasExpiry ? "block" : "none") + ";\"><div class=\"ap-row\"><div><label>Expiry Month</label><select id=\"f_expiry_month\">" + renderMonthOptions(expiryMonth) + "</select></div><div><label>Expiry Year</label><select id=\"f_expiry_year\">" + renderYearOptions(expiryYear) + "</select></div></div></div>" +
        "<div><label>Credential URL (optional)</label><input id=\"f_credential_url\" value=\"" + escapeHtml(item.credential_url || "") + "\" placeholder=\"Link to verify credential\" /></div>" +
        "<div><label>Description</label><textarea id=\"f_cert_description\">" + escapeHtml(item.description || "") + "</textarea></div>" +
        "<div style=\"margin-top:10px;\">" +
        "<label>Upload certificate (image)</label>" +
        (mode === "edit" && item.id ? "<input id=\"f_cert_media\" type=\"file\" accept=\".jpg,.jpeg,.png\" />" : "<div class=\"ap-help\">Save this entry first, then edit to upload media.</div>") +
        (item.media_url ? "<div class=\"ap-help\">Current: <a href=\"" + escapeHtml(item.media_url) + "\" target=\"_blank\" rel=\"noopener\">" + escapeHtml(item.media_url) + "</a></div>" : "") +
        "</div>";
      body.querySelector("#f_has_expiry").addEventListener("change", function () {
        body.querySelector("#expiryWrap").style.display = this.checked ? "block" : "none";
      });
      var certMedia = body.querySelector("#f_cert_media");
      if (certMedia) {
        certMedia.addEventListener("change", function () {
          if (!certMedia.files || !certMedia.files[0]) return;
          AlumniApi.profileCertificationMediaUpload(item.id, certMedia.files[0])
            .then(function (out) {
              item.media_url = out.url;
              showMsg(root, "Certificate uploaded.", true);
            })
            .catch(function (e) {
              showMsg(root, (e && e.message) || "Upload failed", false);
            })
            .finally(function () {
              certMedia.value = "";
            });
        });
      }
      return;
    }

    if (section === "achievements") {
      var issueMonthAch = item.issue_month || (item.date ? item.date.slice(5, 7) : "");
      var issueYearAch = item.issue_year || (item.date ? item.date.slice(0, 4) : "");
      var assocOptions = []
        .concat((state.data.education || []).map(function (x) { return x.school; }))
        .concat((state.data.experience || []).map(function (x) { return x.company; }))
        .concat((state.data.clubs || []).map(function (x) { return x.name; }))
        .filter(Boolean);
      var seen = {};
      assocOptions = assocOptions.filter(function (x) {
        if (seen[x]) return false;
        seen[x] = true;
        return true;
      });
      if (!assocOptions.length) assocOptions = ["Other"];
      var selectedAssoc = item.associated_with || item.issuer || assocOptions[0];
      title.textContent = (mode === "add" ? "Add " : "Edit ") + "Achievements & Awards";
      body.innerHTML =
        "<div class=\"ap-row\"><div><label>Achievement Title</label><input id=\"f_title\" value=\"" + escapeHtml(item.title || "") + "\" placeholder=\"e.g., Winner of Hackathon 2025\" /></div><div><label>Associated With</label><select id=\"f_associated_with\">" +
        assocOptions.map(function (opt) { return "<option value=\"" + escapeHtml(opt) + "\"" + (selectedAssoc === opt ? " selected" : "") + ">" + escapeHtml(opt) + "</option>"; }).join("") +
        (assocOptions.indexOf("Other") < 0 ? "<option value=\"Other\"" + (selectedAssoc === "Other" ? " selected" : "") + ">Other</option>" : "") +
        "</select></div></div>" +
        "<div class=\"ap-row\"><div><label>Issue Month</label><select id=\"f_issue_month\">" + renderMonthOptions(issueMonthAch) + "</select></div><div><label>Issue Year</label><select id=\"f_issue_year\">" + renderYearOptions(issueYearAch) + "</select></div></div>" +
        "<div><label>Description</label><textarea id=\"f_description\">" + escapeHtml(item.description || "") + "</textarea></div>" +
        "<div style=\"margin-top:10px;\">" +
        "<label>Upload achievement proof (image)</label>" +
        (mode === "edit" && item.id ? "<input id=\"f_ach_media\" type=\"file\" accept=\".jpg,.jpeg,.png\" />" : "<div class=\"ap-help\">Save this entry first, then edit to upload media.</div>") +
        (item.media_url ? "<div class=\"ap-help\">Current: <a href=\"" + escapeHtml(item.media_url) + "\" target=\"_blank\" rel=\"noopener\">" + escapeHtml(item.media_url) + "</a></div>" : "") +
        "</div>";
      var achMedia = body.querySelector("#f_ach_media");
      if (achMedia) {
        achMedia.addEventListener("change", function () {
          if (!achMedia.files || !achMedia.files[0]) return;
          AlumniApi.profileAchievementMediaUpload(item.id, achMedia.files[0])
            .then(function (out) {
              item.media_url = out.url;
              showMsg(root, "Achievement proof uploaded.", true);
            })
            .catch(function (e) {
              showMsg(root, (e && e.message) || "Upload failed", false);
            })
            .finally(function () {
              achMedia.value = "";
            });
        });
      }
    }
  }

  function closeModal(root, state) {
    var backdrop = root.querySelector("#alumniModalBackdrop");
    if (backdrop) backdrop.style.display = "none";
    state.modalCtx = null;
  }

  function readLines(text) {
    return String(text || "")
      .split(/\r?\n/)
      .map(function (s) { return s.trim(); })
      .filter(Boolean);
  }

  function buildModalItem(root, state) {
    var section = state.modalCtx.section;
    if (section === "basic") {
      state.data.full_name = root.querySelector("#f_full_name").value.trim();
      state.data.headline = root.querySelector("#f_headline").value.trim();
      state.data.phone = root.querySelector("#f_phone").value.trim();
      state.data.current_company = root.querySelector("#f_current_company").value.trim();
      state.data.designation = root.querySelector("#f_designation").value.trim();
      state.data.location = root.querySelector("#f_location").value.trim();
      state.data.branch = root.querySelector("#f_branch").value.trim();
      state.data.passing_year = root.querySelector("#f_passing_year").value.trim();
      state.data.degree = root.querySelector("#f_degree").value.trim();
      return null;
    }
    if (section === "work") {
      state.data.work_profile = {
        organization: root.querySelector("#f_wp_org").value.trim(),
        department: root.querySelector("#f_wp_dept").value.trim(),
        responsibilities: readLines(root.querySelector("#f_wp_resp").value),
        technologies_used: root.querySelector("#f_wp_tech").value.trim(),
        work_domain: root.querySelector("#f_wp_domain").value.trim()
      };
      return null;
    }
    if (section === "about") {
      state.data.bio = root.querySelector("#f_bio").value.trim();
      state.data.linkedin_url = root.querySelector("#f_linkedin_url").value.trim();
      state.data.portfolio_url = root.querySelector("#f_portfolio_url").value.trim();
      return null;
    }
    if (section === "resources") {
      return {
        id: state.modalCtx.item && state.modalCtx.item.id ? state.modalCtx.item.id : ("res_" + Date.now()),
        description: root.querySelector("#f_res_desc").value.trim(),
        links: readLines(root.querySelector("#f_res_links").value),
        media_urls: readLines(root.querySelector("#f_res_media").value)
      };
    }
    if (section === "education") {
      var degree = root.querySelector("#f_degree_select").value.trim();
      var current = !!root.querySelector("#f_edu_current").checked;
      var startMonth = root.querySelector("#f_start_month").value;
      var startYear = root.querySelector("#f_start_year").value;
      var endMonth = current ? null : root.querySelector("#f_end_month").value;
      var endYear = current ? null : root.querySelector("#f_end_year").value;
      var isBoard = ["SSC", "HSC", "Intermediate"].indexOf(degree) >= 0;
      var board = isBoard ? (root.querySelector("#f_board") ? root.querySelector("#f_board").value.trim() : "") : null;
      var field = !isBoard ? (root.querySelector("#f_field_of_study") ? root.querySelector("#f_field_of_study").value.trim() : "") : null;
      return {
        id: state.modalCtx.item && state.modalCtx.item.id ? state.modalCtx.item.id : ("edu_" + Date.now()),
        school: root.querySelector("#f_school").value.trim(),
        degree: degree,
        board: board,
        field_of_study: field,
        field: isBoard ? board : field,
        cgpa: root.querySelector("#f_cgpa").value.trim(),
        current: current,
        start_month: startMonth,
        start_year: startYear,
        start_date: ymToISO(startMonth, startYear),
        end_month: endMonth,
        end_year: endYear,
        end_date: current ? null : ymToISO(endMonth, endYear)
      };
    }
    if (section === "experience") {
      var currentRole = !!root.querySelector("#f_current_role").checked;
      var expStartMonth = root.querySelector("#f_start_month").value;
      var expStartYear = root.querySelector("#f_start_year").value;
      var expEndMonth = currentRole ? null : root.querySelector("#f_end_month").value;
      var expEndYear = currentRole ? null : root.querySelector("#f_end_year").value;
      return {
        id: state.modalCtx.item && state.modalCtx.item.id ? state.modalCtx.item.id : ("exp_" + Date.now()),
        company: root.querySelector("#f_company").value.trim(),
        role: root.querySelector("#f_role").value.trim(),
        employment_type: root.querySelector("#f_employment_type").value,
        current: currentRole,
        start_month: expStartMonth,
        start_year: expStartYear,
        start_date: ymToISO(expStartMonth, expStartYear),
        end_month: expEndMonth,
        end_year: expEndYear,
        end_date: currentRole ? null : ymToISO(expEndMonth, expEndYear),
        location: root.querySelector("#f_exp_location").value.trim(),
        location_type: root.querySelector("#f_location_type").value,
        skills: root.querySelector("#f_exp_skills").value.split(",").map(function (s) { return s.trim(); }).filter(Boolean),
        description: root.querySelector("#f_exp_description").value.trim(),
        media_url: (state.modalCtx.item || {}).media_url || null,
        offer_letter_url: (state.modalCtx.item || {}).offer_letter_url || null,
        completion_certificate_url: (state.modalCtx.item || {}).completion_certificate_url || null
      };
    }
    if (section === "projects") {
      return {
        id: state.modalCtx.item && state.modalCtx.item.id ? state.modalCtx.item.id : ("proj_" + Date.now()),
        name: root.querySelector("#f_name").value.trim(),
        tech_stack: root.querySelector("#f_tech_stack").value.trim(),
        link: root.querySelector("#f_link").value.trim(),
        role: root.querySelector("#f_proj_role").value.trim(),
        description: root.querySelector("#f_description").value.trim(),
        media_urls: Array.isArray((state.modalCtx.item || {}).media_urls) ? state.modalCtx.item.media_urls : [],
        project_video_url: (state.modalCtx.item || {}).project_video_url || null
      };
    }
    if (section === "skills") {
      return {
        id: state.modalCtx.item && state.modalCtx.item.id ? state.modalCtx.item.id : ("skill_" + Date.now()),
        name: root.querySelector("#f_name").value.trim(),
        level: root.querySelector("#f_level").value.trim()
      };
    }
    if (section === "clubs") {
      var type = root.querySelector("#f_club_type").value;
      var name = "";
      var sportName = null;
      if (type === "Councils") {
        name = root.querySelector("#f_council_option").value === "Other" ? root.querySelector("#f_council_other_name").value.trim() : root.querySelector("#f_council_option").value;
      } else if (type === "Clubs") {
        name = root.querySelector("#f_club_option").value;
        if (name === "Sports Club") sportName = root.querySelector("#f_sport_name").value.trim();
      } else {
        name = root.querySelector("#f_org_name").value.trim();
      }
      var currentClub = !!root.querySelector("#f_club_current").checked;
      var clubStartMonth = root.querySelector("#f_club_start_month").value;
      var clubStartYear = root.querySelector("#f_club_start_year").value;
      var clubEndMonth = currentClub ? null : root.querySelector("#f_club_end_month").value;
      var clubEndYear = currentClub ? null : root.querySelector("#f_club_end_year").value;
      return {
        id: state.modalCtx.item && state.modalCtx.item.id ? state.modalCtx.item.id : ("club_" + Date.now()),
        type: type,
        name: name,
        role: root.querySelector("#f_club_role").value.trim(),
        sport_name: sportName,
        current: currentClub,
        start_month: clubStartMonth,
        start_year: clubStartYear,
        start_date: ymToISO(clubStartMonth, clubStartYear),
        end_month: clubEndMonth,
        end_year: clubEndYear,
        end_date: currentClub ? null : ymToISO(clubEndMonth, clubEndYear),
        description: root.querySelector("#f_club_description").value.trim()
      };
    }
    if (section === "certifications") {
      var issueMonth = root.querySelector("#f_issue_month").value;
      var issueYear = root.querySelector("#f_issue_year").value;
      var hasExpiry = !!root.querySelector("#f_has_expiry").checked;
      var expiryMonth = hasExpiry ? root.querySelector("#f_expiry_month").value : "";
      var expiryYear = hasExpiry ? root.querySelector("#f_expiry_year").value : "";
      return {
        id: state.modalCtx.item && state.modalCtx.item.id ? state.modalCtx.item.id : ("cert_" + Date.now()),
        name: root.querySelector("#f_name").value.trim(),
        issuer: root.querySelector("#f_issuer").value.trim(),
        issue_month: issueMonth,
        issue_year: issueYear,
        issue_date: ymToISO(issueMonth, issueYear),
        expiry_month: expiryMonth,
        expiry_year: expiryYear,
        expiry_date: hasExpiry ? ymToISO(expiryMonth, expiryYear) : "",
        credential_url: root.querySelector("#f_credential_url").value.trim(),
        description: root.querySelector("#f_cert_description").value.trim(),
        media_url: (state.modalCtx.item || {}).media_url || null
      };
    }
    if (section === "achievements") {
      var achMonth = root.querySelector("#f_issue_month").value;
      var achYear = root.querySelector("#f_issue_year").value;
      var assoc = root.querySelector("#f_associated_with").value;
      return {
        id: state.modalCtx.item && state.modalCtx.item.id ? state.modalCtx.item.id : ("ach_" + Date.now()),
        title: root.querySelector("#f_title").value.trim(),
        associated_with: assoc,
        issuer: assoc,
        issue_month: achMonth,
        issue_year: achYear,
        date: ymToISO(achMonth, achYear),
        description: root.querySelector("#f_description").value.trim(),
        media_url: (state.modalCtx.item || {}).media_url || null
      };
    }
    return null;
  }

  function renderAll(root, state) {
    renderLayout(root, state.data, state.editMode);

    root.querySelector("#basicSummary").innerHTML = summaryLines([
      state.data.full_name,
      state.data.email ? "Email: " + state.data.email : null,
      state.data.headline ? "Headline: " + state.data.headline : null,
      state.data.phone ? "Phone: " + state.data.phone : null,
      state.data.current_company ? "Current company: " + state.data.current_company : null,
      state.data.designation ? "Current role: " + state.data.designation : null,
      state.data.location ? "Location: " + state.data.location : null,
      state.data.branch ? "Branch: " + state.data.branch : null,
      state.data.passing_year ? "Passing year: " + state.data.passing_year : null,
      state.data.degree ? "Degree: " + state.data.degree : null
    ]);

    var wp = state.data.work_profile || {};
    root.querySelector("#workSummary").innerHTML = summaryLines([
      wp.organization ? "Organization: " + wp.organization : null,
      wp.department ? "Department / team: " + wp.department : null,
      Array.isArray(wp.responsibilities) && wp.responsibilities.length ? "Key responsibilities: " + wp.responsibilities.join(" | ") : null,
      wp.technologies_used ? "Technologies used: " + wp.technologies_used : null,
      wp.work_domain ? "Work domain: " + wp.work_domain : null
    ]);

    root.querySelector("#aboutSummary").innerHTML = summaryLines([
      state.data.bio || null,
      state.data.linkedin_url ? "LinkedIn: " + state.data.linkedin_url : null,
      state.data.portfolio_url ? "Portfolio: " + state.data.portfolio_url : null
    ]);

    renderList(root.querySelector("#resourceList"), "resources", state.data.student_resources, "description", function (item) {
      var parts = [];
      if (item.links && item.links.length) parts.push("Links: " + item.links.join(", "));
      if (item.media_urls && item.media_urls.length) parts.push("Media: " + item.media_urls.join(", "));
      return parts.length ? parts : [item.description || "-"];
    }, state.editMode);

    renderList(root.querySelector("#educationList"), "education", state.data.education, "degree", function (it) {
      var secondary = ["SSC", "HSC", "Intermediate"].indexOf(it.degree) >= 0 ? (it.board || it.field) : (it.field_of_study || it.field);
      return [it.school, secondary, formatRange(it.start_month, it.start_year, it.end_month, it.end_year, !!it.current), it.cgpa ? "CGPA: " + it.cgpa : ""].filter(Boolean);
    }, state.editMode);

    renderList(root.querySelector("#experienceList"), "experience", state.data.experience, "role", function (it) {
      return [it.company, it.employment_type, [it.location_type, it.location].filter(Boolean).join(" "), formatRange(it.start_month, it.start_year, it.end_month, it.end_year, !!it.current), it.description].filter(Boolean);
    }, state.editMode);

    renderList(root.querySelector("#projectsList"), "projects", state.data.projects, "name", function (it) {
      return [it.tech_stack, it.link, it.role, it.description].filter(Boolean);
    }, state.editMode);

    renderList(root.querySelector("#skillsList"), "skills", state.data.skills, "name", function (it) {
      return [it.level].filter(Boolean);
    }, state.editMode);

    renderList(root.querySelector("#clubsList"), "clubs", state.data.clubs, "role", function (it) {
      return [it.name, it.type, it.sport_name ? "Sport: " + it.sport_name : "", formatRange(it.start_month, it.start_year, it.end_month, it.end_year, !!it.current), it.description].filter(Boolean);
    }, state.editMode);

    renderList(root.querySelector("#certificationsList"), "certifications", state.data.certifications, "name", function (it) {
      var issue = formatMonthYear(it.issue_month, it.issue_year) || it.issue_date;
      var expiry = formatMonthYear(it.expiry_month, it.expiry_year);
      return [it.issuer, issue, expiry ? "Expiry: " + expiry : "", it.credential_url].filter(Boolean);
    }, state.editMode);

    renderList(root.querySelector("#achievementsList"), "achievements", state.data.achievements, "title", function (it) {
      return [it.associated_with || it.issuer, formatMonthYear(it.issue_month, it.issue_year) || it.date, it.description].filter(Boolean);
    }, state.editMode);

    root.querySelector("#alumniProfToggle").addEventListener("click", function () {
      state.editMode = !state.editMode;
      renderAll(root, state);
    });

    root.querySelector("#alumniModalClose").addEventListener("click", function () { closeModal(root, state); });
    root.querySelector("#alumniModalCancel").addEventListener("click", function () { closeModal(root, state); });
    root.querySelector("#alumniModalBackdrop").addEventListener("click", function (e) {
      if (e.target === this) closeModal(root, state);
    });
    root.querySelector("#alumniModalSave").addEventListener("click", function () {
      try {
        var built = buildModalItem(root, state);
        var ctx = state.modalCtx || {};
        if (ctx.section && built) {
          var targetKey = ctx.section === "resources" ? "student_resources" : ctx.section;
          var arr = state.data[targetKey] || [];
          if (ctx.mode === "edit") {
            state.data[targetKey] = arr.map(function (entry) {
              return String(entry.id) === String(built.id) ? built : entry;
            });
          } else {
            state.data[targetKey] = arr.concat([built]);
          }
        }
        saveProfile(state, root).then(function () {
          closeModal(root, state);
          renderAll(root, state);
        });
      } catch (err) {
        showMsg(root, err.message || "Save failed", false);
      }
    });

    if (state.editMode) {
      var photoBtn = root.querySelector("#alumniPhotoUploadBtn");
      var photoInput = root.querySelector("#alumniPhotoInput");
      if (photoBtn && photoInput) {
        photoBtn.addEventListener("click", function () { photoInput.click(); });
        photoInput.addEventListener("change", function () {
          if (!photoInput.files || !photoInput.files[0]) return;
          var fd = new FormData();
          fd.append("file", photoInput.files[0]);
          requestJson("/api/student/profile/photo", { method: "POST", body: fd, headers: authHeaders(), isFormData: true })
            .then(function () { return AlumniApi.profileGet(); })
            .then(function (data) { state.data = normalizeData(data); renderAll(root, state); showMsg(root, "Profile photo updated.", true); })
            .catch(function (err) { showMsg(root, err.message || "Photo upload failed", false); });
        });
      }
      var coverBtn = root.querySelector("#alumniCoverUploadBtn");
      var coverInput = root.querySelector("#alumniCoverInput");
      if (coverBtn && coverInput) {
        coverBtn.addEventListener("click", function () { coverInput.click(); });
        coverInput.addEventListener("change", function () {
          if (!coverInput.files || !coverInput.files[0]) return;
          var fd = new FormData();
          fd.append("file", coverInput.files[0]);
          requestJson("/api/student/profile/cover-photo", { method: "POST", body: fd, headers: authHeaders(), isFormData: true })
            .then(function () { return AlumniApi.profileGet(); })
            .then(function (data) { state.data = normalizeData(data); renderAll(root, state); showMsg(root, "Cover photo updated.", true); })
            .catch(function (err) { showMsg(root, err.message || "Cover upload failed", false); });
        });
      }
      var photoRemove = root.querySelector("#alumniPhotoRemoveBtn");
      if (photoRemove) {
        photoRemove.addEventListener("click", function () {
          requestJson("/api/student/profile/photo", { method: "DELETE" })
            .then(function () { return AlumniApi.profileGet(); })
            .then(function (data) { state.data = normalizeData(data); renderAll(root, state); showMsg(root, "Profile photo removed.", true); })
            .catch(function (err) { showMsg(root, err.message || "Remove failed", false); });
        });
      }
      var coverRemove = root.querySelector("#alumniCoverRemoveBtn");
      if (coverRemove) {
        coverRemove.addEventListener("click", function () {
          requestJson("/api/student/profile/cover-photo", { method: "DELETE" })
            .then(function () { return AlumniApi.profileGet(); })
            .then(function (data) { state.data = normalizeData(data); renderAll(root, state); showMsg(root, "Cover photo removed.", true); })
            .catch(function (err) { showMsg(root, err.message || "Remove failed", false); });
        });
      }
    }

    root.onclick = function (e) {
      var add = e.target.getAttribute("data-add");
      var open = e.target.getAttribute("data-open");
      var edit = e.target.getAttribute("data-edit");
      var del = e.target.getAttribute("data-del");
      var id = e.target.getAttribute("data-id");

      if (open) {
        openModal(state, root, { section: open, mode: "edit", item: {} });
        return;
      }
      if (add) {
        openModal(state, root, { section: add, mode: "add", item: {} });
        return;
      }
      if (edit) {
        var key = edit === "resources" ? "student_resources" : edit;
        openModal(state, root, { section: edit, mode: "edit", item: cloneStateData(findItem(state, key, id) || {}) });
        return;
      }
      if (del) {
        var targetKey = del === "resources" ? "student_resources" : del;
        state.data[targetKey] = (state.data[targetKey] || []).filter(function (entry) { return String(entry.id) !== String(id); });
        saveProfile(state, root).then(function () { renderAll(root, state); });
      }
    };
  }

  function render(root, opts) {
    ensureStyles();
    opts = opts || {};
    var state = {
      data: null,
      editMode: opts.startInEditMode === true,
      modalCtx: null
    };

    root.innerHTML = "<div class=\"cl-state\">Loading profile...</div>";
    AlumniApi.profileGet()
      .then(function (data) {
        state.data = normalizeData(data || {});
        renderAll(root, state);
      })
      .catch(function (err) {
        root.innerHTML = "<div class=\"cl-state cl-error\">" + escapeHtml((err && err.message) || "Failed to load profile") + "</div>";
      });
  }

  return { render: render };
})();
