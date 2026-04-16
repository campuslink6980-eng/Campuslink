/**
 * CampusLink SOS / Support tickets — shared UI for student, alumni, faculty, coordinator.
 * Opens from elements with [data-campuslink-sos-open].
 */
(function () {
  var ISSUE_TYPES = [
    { v: "technical", l: "Technical Issue" },
    { v: "account", l: "Account Problem" },
    { v: "bug", l: "Bug Report" },
    { v: "feature", l: "Feature Request" },
    { v: "other", l: "Other" },
  ];

  function authHeaders() {
    var h = {};
    var t = localStorage.getItem("campuslink_token");
    if (t) h.Authorization = "Bearer " + t;
    return h;
  }

  function esc(s) {
    if (s == null) return "";
    var d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function statusClass(st) {
    var x = (st || "").replace(/\s+/g, "_").toLowerCase();
    return "st-" + x;
  }

  function buildShell() {
    var overlay = document.createElement("div");
    overlay.className = "cl-sos-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", "Support tickets");
    overlay.innerHTML =
      '<div class="cl-sos-panel">' +
      '<div class="cl-sos-head"><h2>🆘 Raise Issue / Help</h2><button type="button" class="cl-sos-close" aria-label="Close">×</button></div>' +
      '<div class="cl-sos-body">' +
      '<div class="cl-sos-actions">' +
      '<button type="button" class="cl-sos-primary" data-sos-tab="new">New ticket</button>' +
      '<button type="button" data-sos-tab="list">My tickets</button>' +
      "</div>" +
      '<div data-sos-view="list"></div>' +
      '<div data-sos-view="new" style="display:none;"></div>' +
      '<div data-sos-view="detail" style="display:none;"></div>' +
      "</div>" +
      "</div>";
    document.body.appendChild(overlay);

    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) close();
    });
    overlay.querySelector(".cl-sos-close").addEventListener("click", close);
    document.addEventListener("keydown", function onKey(e) {
      if (e.key === "Escape" && overlay.classList.contains("cl-sos-open")) close();
    });

    overlay.querySelectorAll("[data-sos-tab]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var tab = btn.getAttribute("data-sos-tab");
        if (tab === "new") showNewForm(overlay);
        else showList(overlay);
      });
    });

    return overlay;
  }

  var overlayRef = null;

  function ensureOverlay() {
    if (!overlayRef) overlayRef = buildShell();
    return overlayRef;
  }

  function open() {
    var o = ensureOverlay();
    o.classList.add("cl-sos-open");
    showList(o);
  }

  function close() {
    if (overlayRef) overlayRef.classList.remove("cl-sos-open");
  }

  function view(o, name) {
    o.querySelectorAll("[data-sos-view]").forEach(function (el) {
      el.style.display = el.getAttribute("data-sos-view") === name ? "block" : "none";
    });
    if (name === "detail") o.querySelector(".cl-sos-panel").classList.add("cl-sos-wide");
    else o.querySelector(".cl-sos-panel").classList.remove("cl-sos-wide");
  }

  function showNewForm(o) {
    view(o, "new");
    var wrap = o.querySelector('[data-sos-view="new"]');
    var opts = ISSUE_TYPES.map(function (it) {
      return '<option value="' + esc(it.v) + '">' + esc(it.l) + "</option>";
    }).join("");
    wrap.innerHTML =
      '<form class="cl-sos-form" id="clSosCreateForm">' +
      "<label>Issue type</label><select name=\"issue_type\" required>" +
      opts +
      "</select>" +
      "<label>Title</label><input type=\"text\" name=\"title\" required maxlength=\"200\" placeholder=\"Short summary\" />" +
      "<label>Description</label><textarea name=\"description\" required minlength=\"10\" placeholder=\"What happened? What do you need?\"></textarea>" +
      "<label>Priority</label><select name=\"priority\"><option value=\"low\">Low</option><option value=\"medium\" selected>Medium</option><option value=\"high\">High 🚨</option></select>" +
      "<label>Screenshot (optional, jpg/png)</label><input type=\"file\" name=\"screenshot\" accept=\"image/jpeg,image/png,image/jpg\" />" +
      '<p class="cl-sos-err" id="clSosFormErr" style="display:none;"></p>' +
      '<button type="submit" class="cl-sos-submit">Submit ticket</button>' +
      "</form>";

    wrap.querySelector("#clSosCreateForm").addEventListener("submit", function (ev) {
      ev.preventDefault();
      var form = ev.target;
      var errEl = form.querySelector("#clSosFormErr");
      errEl.style.display = "none";
      var fd = new FormData(form);
      var btn = form.querySelector(".cl-sos-submit");
      btn.disabled = true;
      fetch("/api/support/tickets", {
        method: "POST",
        credentials: "same-origin",
        headers: authHeaders(),
        body: fd,
      })
        .then(function (r) {
          return r.json().then(function (j) {
            if (!r.ok) throw new Error((j && j.error) || "Failed");
            return j;
          });
        })
        .then(function (data) {
          form.reset();
          if (data.ticket && data.ticket.id) showDetail(o, data.ticket.id);
          else showList(o);
        })
        .catch(function (e) {
          errEl.textContent = e.message || "Submit failed";
          errEl.style.display = "block";
        })
        .then(function () {
          btn.disabled = false;
        });
    });
  }

  function renderTicketList(o, tickets) {
    var wrap = o.querySelector('[data-sos-view="list"]');
    if (!tickets || !tickets.length) {
      wrap.innerHTML = '<div class="cl-sos-empty">No tickets yet. Create one if you need help.</div>';
      return;
    }
    wrap.innerHTML = tickets
      .map(function (t) {
        return (
          '<div class="cl-sos-ticket-card" data-sos-ticket-id="' +
          esc(t.id) +
          '">' +
          "<strong>" +
          esc(t.ticket_number) +
          "</strong> · " +
          esc(t.title) +
          '<div class="t-meta">' +
          '<span class="cl-sos-badge ' +
          statusClass(t.status) +
          '">' +
          esc((t.status || "").replace(/_/g, " ")) +
          "</span>" +
          '<span class="cl-sos-badge pr-' +
          esc((t.priority || "low").toLowerCase()) +
          '">' +
          esc(t.priority) +
          "</span>" +
          "<span>Updated " +
          esc(t.updated_at || "") +
          "</span>" +
          "</div></div>"
        );
      })
      .join("");
    wrap.querySelectorAll(".cl-sos-ticket-card").forEach(function (card) {
      card.addEventListener("click", function () {
        showDetail(o, card.getAttribute("data-sos-ticket-id"));
      });
    });
  }

  function showList(o) {
    view(o, "list");
    var wrap = o.querySelector('[data-sos-view="list"]');
    wrap.innerHTML = '<div class="cl-sos-empty">Loading…</div>';
    fetch("/api/support/tickets", { credentials: "same-origin", headers: authHeaders() })
      .then(function (r) {
        return r.json().then(function (j) {
          if (!r.ok) throw new Error((j && j.error) || "Failed to load");
          return j;
        });
      })
      .then(function (data) {
        renderTicketList(o, data.tickets || []);
      })
      .catch(function () {
        wrap.innerHTML = '<div class="cl-sos-empty">Could not load tickets. Please sign in again.</div>';
      });
  }

  function showDetail(o, ticketId) {
    view(o, "detail");
    var wrap = o.querySelector('[data-sos-view="detail"]');
    wrap.innerHTML = '<div class="cl-sos-empty">Loading…</div>';
    fetch("/api/support/tickets/" + encodeURIComponent(ticketId), {
      credentials: "same-origin",
      headers: authHeaders(),
    })
      .then(function (r) {
        return r.json().then(function (j) {
          if (!r.ok) throw new Error((j && j.error) || "Failed");
          return j;
        });
      })
      .then(function (data) {
        var t = data.ticket;
        var msgs = (t.messages || [])
          .map(function (m) {
            var side = m.is_staff ? "staff" : "user";
            return (
              '<div class="cl-sos-bubble ' +
              side +
              '"><div class="who">' +
              esc(m.sender_name || "") +
              "</div>" +
              esc(m.message) +
              '<div style="font-size:11px;color:#94a3b8;margin-top:6px;">' +
              esc(m.created_at || "") +
              "</div></div>"
            );
          })
          .join("");
        var shot = t.screenshot_url
          ? '<p><a href="' + esc(t.screenshot_url) + '" target="_blank" rel="noopener">Open screenshot</a></p><img class="cl-sos-shot" src="' + esc(t.screenshot_url) + '" alt="Screenshot" />'
          : "";
        var closed = (t.status || "").toLowerCase() === "closed";
        var replyBlock = closed
          ? "<p class=\"cl-sos-empty\">This ticket is closed.</p>"
          : '<div class="cl-sos-reply"><textarea id="clSosReplyTa" placeholder="Your message…"></textarea><button type="button" id="clSosReplyBtn">Send reply</button><p class="cl-sos-err" id="clSosReplyErr" style="display:none;"></p></div>';

        wrap.innerHTML =
          '<div class="cl-sos-actions"><button type="button" data-sos-back>← Back to list</button></div>' +
          "<h3 style=\"margin:0 0 8px;font-size:16px;\">" +
          esc(t.ticket_number) +
          " — " +
          esc(t.title) +
          "</h3>" +
          '<div class="t-meta" style="margin-bottom:10px;">' +
          '<span class="cl-sos-badge ' +
          statusClass(t.status) +
          '">' +
          esc((t.status || "").replace(/_/g, " ")) +
          "</span>" +
          '<span class="cl-sos-badge pr-' +
          esc((t.priority || "").toLowerCase()) +
          '">' +
          esc(t.priority) +
          "</span></div>" +
          "<p style=\"font-size:14px;color:#334155;white-space:pre-wrap;\">" +
          esc(t.description || "") +
          "</p>" +
          shot +
          '<div class="cl-sos-chat">' +
          msgs +
          "</div>" +
          replyBlock;

        wrap.querySelector("[data-sos-back]").addEventListener("click", function () {
          showList(o);
        });
        var btn = wrap.querySelector("#clSosReplyBtn");
        if (btn) {
          btn.addEventListener("click", function () {
            var ta = wrap.querySelector("#clSosReplyTa");
            var err = wrap.querySelector("#clSosReplyErr");
            err.style.display = "none";
            var text = (ta && ta.value) || "";
            if (!text.trim()) return;
            btn.disabled = true;
            fetch("/api/support/tickets/" + encodeURIComponent(ticketId) + "/messages", {
              method: "POST",
              credentials: "same-origin",
              headers: Object.assign({ "Content-Type": "application/json" }, authHeaders()),
              body: JSON.stringify({ message: text }),
            })
              .then(function (r) {
                return r.json().then(function (j) {
                  if (!r.ok) throw new Error((j && j.error) || "Failed");
                  return j;
                });
              })
              .then(function () {
                ta.value = "";
                showDetail(o, ticketId);
              })
              .catch(function (e) {
                err.textContent = e.message || "Failed";
                err.style.display = "block";
              })
              .then(function () {
                btn.disabled = false;
              });
          });
        }
      })
      .catch(function (e) {
        wrap.innerHTML =
          '<div class="cl-sos-empty">' +
          esc(e.message || "Error") +
          '</div><div class="cl-sos-actions"><button type="button" data-sos-back>← Back</button></div>';
        wrap.querySelector("[data-sos-back]").addEventListener("click", function () {
          showList(o);
        });
      });
  }

  function bindTriggers() {
    document.addEventListener("click", function (e) {
      var t = e.target.closest && e.target.closest("[data-campuslink-sos-open]");
      if (!t) return;
      e.preventDefault();
      open();
    });
  }

  window.CampusLinkSOS = {
    open: open,
    close: close,
    init: function () {},
  };

  bindTriggers();
})();
