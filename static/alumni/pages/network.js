/* My Network: connections + mentorship */

window.AlumniPages = window.AlumniPages || {};

window.AlumniPages.Network = (function () {
  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function renderConnections(root) {
    var wrap = document.createElement("div");
    wrap.innerHTML =
      "<h2 style=\"margin-top:0;\">Connections</h2>" +
      "<div class=\"ln-tabs\"><button type=\"button\" class=\"cl-btn sm\" data-cx=\"accepted\">Accepted</button>" +
      "<button type=\"button\" class=\"cl-btn sm\" data-cx=\"PENDING\">Pending</button></div>" +
      "<div id=\"cxList\" class=\"ln-conn-list\"></div>";
    root.appendChild(wrap);

    function load(status) {
      var list = wrap.querySelector("#cxList");
      list.textContent = "Loading…";
      AlumniApi.connections(status === "accepted" ? "ACCEPTED" : status)
        .then(function (data) {
          var rows = (data && data.connections) || [];
          list.innerHTML = "";
          if (!rows.length) {
            list.innerHTML = "<div class=\"cl-state\">No connections in this tab.</div>";
            return;
          }
          rows.forEach(function (c) {
            var card = document.createElement("div");
            card.className = "ln-conn-card";
            card.innerHTML =
              "<div class=\"ln-conn-av\"></div><div><strong>" +
              escapeHtml(c.name || "User") +
              "</strong><div class=\"muted\">" +
              escapeHtml(c.status || "") +
              "</div></div>";
            card.querySelector(".ln-conn-av").textContent = (c.name || "U").charAt(0).toUpperCase();
            if (c.status === "PENDING" && !c.is_requester) {
              var act = document.createElement("div");
              act.className = "ln-conn-actions";
              var acc = document.createElement("button");
              acc.type = "button";
              acc.className = "cl-btn sm primary";
              acc.textContent = "Accept";
              var rej = document.createElement("button");
              rej.type = "button";
              rej.className = "cl-btn sm";
              rej.textContent = "Ignore";
              acc.addEventListener("click", function () {
                AlumniApi.connectionRespond(c.id, "accept").then(function () {
                  load(status);
                }).catch(function (e) {
                  alert((e && e.message) || "Failed");
                });
              });
              rej.addEventListener("click", function () {
                AlumniApi.connectionRespond(c.id, "reject").then(function () {
                  load(status);
                }).catch(function (e) {
                  alert((e && e.message) || "Failed");
                });
              });
              act.appendChild(acc);
              act.appendChild(rej);
              card.appendChild(act);
            }
            list.appendChild(card);
          });
        })
        .catch(function () {
          list.innerHTML = "<div class=\"cl-error cl-state\">Failed to load connections.</div>";
        });
    }

    wrap.querySelector("[data-cx=accepted]").addEventListener("click", function () {
      load("accepted");
    });
    wrap.querySelector("[data-cx=PENDING]").addEventListener("click", function () {
      load("PENDING");
    });
    load("accepted");
  }

  function renderMentorshipPanel(root) {
    var slot = document.createElement("div");
    slot.id = "lnMentorSlotBanner";
    root.appendChild(slot);

    AlumniApi.dashboard()
      .then(function (d) {
        if (d.mentee_slots_full) {
          slot.className = "ln-banner ln-banner-warn";
          slot.textContent = "Mentee slots full (max " + (d.max_mentees || 5) + " active mentees).";
        } else {
          slot.className = "ln-banner ln-banner-ok";
          slot.textContent =
            "Mentoring: " +
            (d.active_mentees != null ? d.active_mentees : 0) +
            " / " +
            (d.max_mentees || 5) +
            " mentee slots in use.";
        }
      })
      .catch(function () {
        slot.innerHTML = "";
      });

    var mount = document.createElement("div");
    mount.id = "lnMentorshipMount";
    root.appendChild(mount);
    window.AlumniPages.Mentorship.render(mount);
  }

  function render(root) {
    root.innerHTML =
      "<div class=\"cl-page-head\"><div><h1>My Network</h1><p>Connections with students and alumni, plus mentorship requests.</p></div></div>" +
      "<div class=\"ln-network-grid\">" +
        "<section class=\"cl-section-card\"><div class=\"cl-section-head\"><strong>Connections</strong></div><div class=\"cl-section-body\" id=\"lnConnRoot\"></div></section>" +
        "<section class=\"cl-section-card\"><div class=\"cl-section-head\"><strong>Mentorship</strong></div><div class=\"cl-section-body\" id=\"lnMentorRoot\"></div></section>" +
      "</div>";
    renderConnections(root.querySelector("#lnConnRoot"));
    renderMentorshipPanel(root.querySelector("#lnMentorRoot"));
  }

  return { render: render };
})();
