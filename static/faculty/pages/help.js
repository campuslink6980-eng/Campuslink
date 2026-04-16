window.FacultyPages = window.FacultyPages || {};
window.FacultyPages.Help = (function () {
  function esc(s) { return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function formatTimeAgo(dateStr) {
    if (!dateStr) return "";
    var d = new Date(dateStr);
    var now = new Date();
    var diffMs = now - d;
    var diffMins = Math.floor(diffMs / 60000);
    var diffHours = Math.floor(diffMs / 3600000);
    var diffDays = Math.floor(diffMs / 86400000);
    if (diffMins < 1) return "now";
    if (diffMins < 60) return diffMins + "m";
    if (diffHours < 24) return diffHours + "h";
    if (diffDays < 7) return diffDays + "d";
    return d.toLocaleDateString();
  }
  function formatMessageTime(dateStr) {
    if (!dateStr) return "";
    return new Date(dateStr).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function renderList(root, threads) {
    var tableBody = "";
    if (threads.length) {
      tableBody = threads.map(function (t) {
        var unread = (t.unread_count || 0) > 0 ? " <span class=\"cl-badge\" style=\"background:#3b82f6;color:#fff;\">" + t.unread_count + "</span>" : "";
        return "<tr class=\"cl-clickable\" data-thread-id=\"" + esc(t.thread_id) + "\"><td>" + esc(t.student_name || "—") + "</td><td>" + esc(t.roll_number || t.email || "—") + "</td><td style=\"max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;\">" + esc((t.last_message || "").slice(0, 80)) + "</td><td>" + formatTimeAgo(t.last_message_at) + unread + "</td></tr>";
      }).join("");
    }
    root.innerHTML =
      "<div class=\"cl-page-head\"><div><h1>Help Messages</h1><p>Students in your department can contact you via Help. Click a row to view and reply.</p></div></div>" +
      "<div id=\"helpListWrap\">" + (threads.length ? "<table class=\"cl-table\"><thead><tr><th>Student</th><th>Roll / Email</th><th>Last message</th><th>Time</th></tr></thead><tbody>" + tableBody + "</tbody></table>" : "<div class=\"cl-state\">No help requests yet.</div>") + "</div>" +
      "<div id=\"helpThreadWrap\" style=\"display:none;\"><div class=\"cl-page-head\" style=\"flex-direction:row;align-items:center;gap:12px;\"><button type=\"button\" class=\"cl-btn sm\" id=\"helpBackBtn\">← Back</button><h2 id=\"helpThreadTitle\">Conversation</h2></div><div id=\"helpThreadMessages\" style=\"min-height:200px;max-height:400px;overflow-y:auto;border:1px solid var(--border, #e2e8f0);border-radius:8px;padding:12px;margin-bottom:12px;background:#f9fafb;\"></div><div><textarea id=\"helpReplyInput\" placeholder=\"Type your reply...\" rows=\"3\" style=\"width:100%;max-width:500px;padding:10px;border-radius:8px;border:1px solid var(--border);\"></textarea><button type=\"button\" class=\"cl-btn\" id=\"helpSendBtn\" style=\"margin-top:8px;\">Send reply</button></div></div>";
    root.querySelectorAll(".cl-clickable[data-thread-id]").forEach(function (tr) {
      tr.addEventListener("click", function () { openThread(root, tr.getAttribute("data-thread-id")); });
    });
    var backBtn = root.querySelector("#helpBackBtn");
    if (backBtn) backBtn.addEventListener("click", function () { showList(root); loadThreads(root); });
    var sendBtn = root.querySelector("#helpSendBtn");
    if (sendBtn) sendBtn.addEventListener("click", function () { sendReply(root); });
  }

  function showList(root) {
    var listWrap = root.querySelector("#helpListWrap");
    var threadWrap = root.querySelector("#helpThreadWrap");
    if (listWrap) listWrap.style.display = "block";
    if (threadWrap) threadWrap.style.display = "none";
  }
  function showThread(root) {
    var listWrap = root.querySelector("#helpListWrap");
    var threadWrap = root.querySelector("#helpThreadWrap");
    if (listWrap) listWrap.style.display = "none";
    if (threadWrap) threadWrap.style.display = "block";
  }

  async function loadThreads(root) {
    var wrap = root.querySelector("#helpListWrap");
    if (!wrap) return;
    var stateEl = root.querySelector(".cl-state");
    try {
      var data = await window.FacultyApi.listHelpThreads();
      var threads = (data && data.threads) || [];
      renderList(root, threads);
    } catch (e) {
      if (stateEl) stateEl.textContent = (e && e.message) || "Failed to load.";
    }
  }

  async function openThread(root, threadId) {
    var titleEl = root.querySelector("#helpThreadTitle");
    var messagesEl = root.querySelector("#helpThreadMessages");
    var inputEl = root.querySelector("#helpReplyInput");
    if (titleEl) titleEl.textContent = "Loading…";
    if (messagesEl) messagesEl.innerHTML = "Loading…";
    try {
      var data = await window.FacultyApi.getHelpThread(threadId);
      var student = (data && data.student) || {};
      var messages = (data && data.messages) || [];
      if (titleEl) titleEl.textContent = (student.name || "Student") + (student.roll_number ? " (" + student.roll_number + ")" : "");
      if (messagesEl) {
        if (!messages.length) {
          messagesEl.innerHTML = "<p style=\"color:var(--muted,#6b7280);\">No messages yet.</p>";
        } else {
          messagesEl.innerHTML = messages.map(function (m) {
            var cls = m.is_mine ? "background:#e0e7ff;margin-left:auto;" : "background:#f3f4f6;";
            return "<div style=\"margin-bottom:8px;padding:8px 12px;border-radius:8px;max-width:85%;" + cls + "\"><div>" + esc(m.content) + "</div><div style=\"font-size:11px;color:var(--muted);margin-top:4px;\">" + formatMessageTime(m.created_at) + "</div></div>";
          }).join("");
          messagesEl.scrollTop = messagesEl.scrollHeight;
        }
      }
      if (inputEl) { inputEl.value = ""; inputEl.dataset.threadId = threadId; }
      showThread(root);
    } catch (e) {
      if (messagesEl) messagesEl.innerHTML = "<p class=\"cl-error\">" + esc((e && e.message) || "Failed to load.") + "</p>";
    }
  }

  async function sendReply(root) {
    var inputEl = root.querySelector("#helpReplyInput");
    var threadId = inputEl && inputEl.dataset.threadId;
    var content = (inputEl && inputEl.value || "").trim();
    if (!threadId || !content) return;
    var btn = root.querySelector("#helpSendBtn");
    if (btn) btn.disabled = true;
    try {
      await window.FacultyApi.sendHelpReply(threadId, content);
      inputEl.value = "";
      await openThread(root, threadId);
    } catch (e) {
      alert((e && e.message) || "Failed to send.");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function render(root) {
    root.innerHTML = "<div class=\"cl-state\">Loading help threads…</div>";
    try {
      var data = await window.FacultyApi.listHelpThreads();
      var threads = (data && data.threads) || [];
      renderList(root, threads);
    } catch (e) {
      root.innerHTML = "<div class=\"cl-page-head\"><h1>Help Messages</h1></div><div class=\"cl-state cl-error\">" + esc((e && e.message) || "Failed to load.") + "</div>";
    }
  }
  return { render: render };
})();
