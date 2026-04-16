/* Alumni Settings – Account, Privacy, Notifications, Mentorship */

window.AlumniPages = window.AlumniPages || {};

window.AlumniPages.Settings = (function () {
  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function showMessage(el, msg, ok) {
    if (!el) return;
    el.textContent = msg || "";
    el.className = "cl-settings-msg" + (ok ? " success" : " error");
    el.style.display = msg ? "block" : "none";
  }

  function getCheckbox(id) {
    var el = document.getElementById(id);
    return !!(el && el.checked);
  }

  function render(root) {
    root.innerHTML =
      "<div class=\"cl-page-head\"><div><h1>Settings</h1><p>Manage your account, privacy, notifications, and mentorship preferences.</p></div></div>" +
      "<div class=\"cl-profile-grid\">" +
        "<section class=\"cl-section-card\">" +
          "<div class=\"cl-section-head\"><strong>Account Settings</strong></div>" +
          "<div class=\"cl-section-body\">" +
            "<div id=\"accountMsg\" class=\"cl-settings-msg\" style=\"display:none;\"></div>" +
            "<div class=\"cl-form-group\"><label>Current Email</label><input type=\"email\" id=\"settingCurrentEmail\" readonly /></div>" +
            "<div class=\"cl-form-group\"><label>Update Email Address</label><input type=\"email\" id=\"settingNewEmail\" placeholder=\"Enter new email\" /></div>" +
            "<div class=\"cl-form-group\"><label>Current Password (required for email update)</label><input type=\"password\" id=\"settingEmailPassword\" placeholder=\"Current password\" /></div>" +
            "<button class=\"cl-btn primary\" id=\"btnSaveEmail\" type=\"button\">Save Changes</button>" +
            "<hr class=\"cl-settings-divider\" />" +
            "<div class=\"cl-form-group\"><label>Current Password</label><input type=\"password\" id=\"settingCurrentPassword\" placeholder=\"Current password\" /></div>" +
            "<div class=\"cl-form-group\"><label>New Password</label><input type=\"password\" id=\"settingNewPassword\" placeholder=\"Minimum 8 characters\" /></div>" +
            "<button class=\"cl-btn primary\" id=\"btnChangePassword\" type=\"button\">Save Changes</button>" +
            "<hr class=\"cl-settings-divider\" />" +
            "<button class=\"cl-btn danger\" id=\"btnLogoutAll\" type=\"button\">Logout from All Devices</button>" +
          "</div>" +
        "</section>" +
        "<section class=\"cl-section-card\">" +
          "<div class=\"cl-section-head\"><strong>Privacy Settings</strong></div>" +
          "<div class=\"cl-section-body\">" +
            "<div class=\"cl-form-group\"><label>Profile Visibility</label><select id=\"privacyProfileVisibility\"><option value=\"public\">Public</option><option value=\"students\">Only Students</option><option value=\"alumni\">Only Alumni</option></select></div>" +
            "<div class=\"cl-toggle-row\"><span>Show Current Company</span><label class=\"cl-toggle\"><input type=\"checkbox\" id=\"privacyShowCompany\" /><span class=\"cl-toggle-slider\"></span></label></div>" +
            "<div class=\"cl-toggle-row\"><span>Show Job Role</span><label class=\"cl-toggle\"><input type=\"checkbox\" id=\"privacyShowJobRole\" /><span class=\"cl-toggle-slider\"></span></label></div>" +
            "<div class=\"cl-toggle-row\"><span>Show Contact Information</span><label class=\"cl-toggle\"><input type=\"checkbox\" id=\"privacyShowContact\" /><span class=\"cl-toggle-slider\"></span></label></div>" +
          "</div>" +
        "</section>" +
        "<section class=\"cl-section-card\">" +
          "<div class=\"cl-section-head\"><strong>Notification Settings</strong></div>" +
          "<div class=\"cl-section-body\">" +
            "<div class=\"cl-toggle-row\"><span>Job related notifications</span><label class=\"cl-toggle\"><input type=\"checkbox\" id=\"notifJob\" /><span class=\"cl-toggle-slider\"></span></label></div>" +
            "<div class=\"cl-toggle-row\"><span>Student connection requests</span><label class=\"cl-toggle\"><input type=\"checkbox\" id=\"notifConnections\" /><span class=\"cl-toggle-slider\"></span></label></div>" +
            "<div class=\"cl-toggle-row\"><span>Platform announcements</span><label class=\"cl-toggle\"><input type=\"checkbox\" id=\"notifAnnouncements\" /><span class=\"cl-toggle-slider\"></span></label></div>" +
            "<div class=\"cl-toggle-row\"><span>Email notifications</span><label class=\"cl-toggle\"><input type=\"checkbox\" id=\"notifEmail\" /><span class=\"cl-toggle-slider\"></span></label></div>" +
          "</div>" +
        "</section>" +
        "<section class=\"cl-section-card\">" +
          "<div class=\"cl-section-head\"><strong>Mentorship Settings</strong></div>" +
          "<div class=\"cl-section-body\">" +
            "<div class=\"cl-toggle-row\"><span>Allow students to contact you for guidance</span><label class=\"cl-toggle\"><input type=\"checkbox\" id=\"mentorAllowContact\" /><span class=\"cl-toggle-slider\"></span></label></div>" +
            "<div class=\"cl-toggle-row\"><span>Allow mentorship requests</span><label class=\"cl-toggle\"><input type=\"checkbox\" id=\"mentorAllowRequests\" /><span class=\"cl-toggle-slider\"></span></label></div>" +
            "<div class=\"cl-toggle-row\"><span>Allow students to view your professional profile</span><label class=\"cl-toggle\"><input type=\"checkbox\" id=\"mentorAllowProfileView\" /><span class=\"cl-toggle-slider\"></span></label></div>" +
          "</div>" +
        "</section>" +
      "</div>" +
      "<div class=\"cl-settings-save-wrap\"><div id=\"settingsMsg\" class=\"cl-settings-msg\" style=\"display:none;\"></div><button class=\"cl-btn primary\" id=\"btnSaveSettings\" type=\"button\">Save Changes</button></div>";

    var accountMsg = document.getElementById("accountMsg");
    var settingsMsg = document.getElementById("settingsMsg");

    AlumniApi.settingsGet()
      .then(function (res) {
        var settings = (res && res.settings) || {};
        var privacy = settings.privacy || {};
        var notifications = settings.notifications || {};
        var mentorship = settings.mentorship || {};
        document.getElementById("settingCurrentEmail").value = (res && res.email) || "";
        document.getElementById("privacyProfileVisibility").value = privacy.profile_visibility || "public";
        document.getElementById("privacyShowCompany").checked = privacy.show_current_company !== false;
        document.getElementById("privacyShowJobRole").checked = privacy.show_job_role !== false;
        document.getElementById("privacyShowContact").checked = privacy.show_contact !== false;
        document.getElementById("notifJob").checked = notifications.job_notifications !== false;
        document.getElementById("notifConnections").checked = notifications.connection_requests !== false;
        document.getElementById("notifAnnouncements").checked = notifications.announcements !== false;
        document.getElementById("notifEmail").checked = notifications.email_notifications !== false;
        document.getElementById("mentorAllowContact").checked = mentorship.allow_contact_for_guidance !== false;
        document.getElementById("mentorAllowRequests").checked = mentorship.allow_mentorship_requests !== false;
        document.getElementById("mentorAllowProfileView").checked = mentorship.allow_profile_view !== false;
      })
      .catch(function (e) {
        showMessage(settingsMsg, (e && e.message) || "Failed to load settings.", false);
      });

    document.getElementById("btnSaveEmail").addEventListener("click", function () {
      showMessage(accountMsg, "", false);
      var newEmail = (document.getElementById("settingNewEmail").value || "").trim();
      var currentPassword = document.getElementById("settingEmailPassword").value || "";
      if (!newEmail) {
        showMessage(accountMsg, "Please enter a new email address.", false);
        return;
      }
      AlumniApi.updateEmail({ new_email: newEmail, current_password: currentPassword })
        .then(function (res) {
          document.getElementById("settingCurrentEmail").value = res.email || newEmail;
          document.getElementById("settingNewEmail").value = "";
          document.getElementById("settingEmailPassword").value = "";
          showMessage(accountMsg, res.message || "Email updated successfully.", true);
        })
        .catch(function (e) {
          showMessage(accountMsg, (e && e.message) || "Failed to update email.", false);
        });
    });

    document.getElementById("btnChangePassword").addEventListener("click", function () {
      showMessage(accountMsg, "", false);
      var currentPassword = document.getElementById("settingCurrentPassword").value || "";
      var newPassword = document.getElementById("settingNewPassword").value || "";
      AlumniApi.changePassword({ current_password: currentPassword, new_password: newPassword })
        .then(function (res) {
          document.getElementById("settingCurrentPassword").value = "";
          document.getElementById("settingNewPassword").value = "";
          showMessage(accountMsg, res.message || "Password updated successfully.", true);
        })
        .catch(function (e) {
          showMessage(accountMsg, (e && e.message) || "Failed to update password.", false);
        });
    });

    document.getElementById("btnLogoutAll").addEventListener("click", function () {
      AlumniApi.logoutAll()
        .then(function (res) {
          showMessage(accountMsg, res.message || "Logged out from all devices.", true);
          setTimeout(function () {
            if (window.CampusLinkAuthSync && window.CampusLinkAuthSync.logoutEverywhere) {
              window.CampusLinkAuthSync.logoutEverywhere();
            } else {
              window.location.href = "/logout";
            }
          }, 700);
        })
        .catch(function (e) {
          showMessage(accountMsg, (e && e.message) || "Failed to logout from all devices.", false);
        });
    });

    document.getElementById("btnSaveSettings").addEventListener("click", function () {
      showMessage(settingsMsg, "", false);
      var payload = {
        privacy: {
          profile_visibility: document.getElementById("privacyProfileVisibility").value,
          show_current_company: getCheckbox("privacyShowCompany"),
          show_job_role: getCheckbox("privacyShowJobRole"),
          show_contact: getCheckbox("privacyShowContact"),
        },
        notifications: {
          job_notifications: getCheckbox("notifJob"),
          connection_requests: getCheckbox("notifConnections"),
          announcements: getCheckbox("notifAnnouncements"),
          email_notifications: getCheckbox("notifEmail"),
        },
        mentorship: {
          allow_contact_for_guidance: getCheckbox("mentorAllowContact"),
          allow_mentorship_requests: getCheckbox("mentorAllowRequests"),
          allow_profile_view: getCheckbox("mentorAllowProfileView"),
        },
      };
      AlumniApi.settingsPut(payload)
        .then(function (res) {
          showMessage(settingsMsg, res.message || "Settings saved successfully.", true);
        })
        .catch(function (e) {
          showMessage(settingsMsg, (e && e.message) || "Failed to save settings.", false);
        });
    });
  }

  return { render: render };
})();

