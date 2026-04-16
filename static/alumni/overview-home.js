/* Alumni home: same layout, composer, modal, and feed cards as student dashboard */

window.AlumniOverviewHome = (function () {
  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function getInitials(name) {
    if (!name) return "AL";
    var parts = String(name).trim().split(/\s+/);
    var a = (parts[0] && parts[0][0]) || "";
    var b = (parts[1] && parts[1][0]) || "";
    return (a + b).toUpperCase() || "AL";
  }

  function formatTimeAgo(dateStr) {
    if (!dateStr) return "";
    var utcStr = dateStr;
    if (!dateStr.endsWith("Z") && dateStr.indexOf("+", 10) < 0 && dateStr.indexOf("-", 10) < 0) {
      utcStr = dateStr + "Z";
    }
    var date = new Date(utcStr);
    var now = new Date();
    var diffMs = now - date;
    var diffMins = Math.floor(diffMs / 60000);
    var diffHours = Math.floor(diffMs / 3600000);
    var diffDays = Math.floor(diffMs / 86400000);
    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return diffMins + "m ago";
    if (diffHours < 24) return diffHours + "h ago";
    if (diffDays < 7) return diffDays + "d ago";
    return date.toLocaleDateString();
  }

  function authFetch(url, options) {
    options = options || {};
    var h = Object.assign({}, options.headers || {});
    var t = localStorage.getItem("campuslink_token");
    if (t) h["Authorization"] = "Bearer " + t;
    return fetch(url, Object.assign({}, options, { credentials: "same-origin", headers: h }));
  }

  var feedSkip = 0;
  var feedHasMore = true;
  var feedLoading = false;
  var currentUserId = "";
  var currentUserName = "Alumni";
  var currentUserRole = "Alumni";
  var editingPostId = null;
  var selectedTaggedUsers = [];
  var mentionSearchToken = "";
  var mentionDebounce = null;
  var selectedPostFiles = [];
  var selectedPostPreviewUrl = null;
  var shareTargetPostId = null;
  var domReady = false;

  function getEl(id) {
    return document.getElementById(id);
  }

  function ensureOverlays() {
    if (domReady) return;
    if (getEl("alumni-post-photo-input")) {
      domReady = true;
      return;
    }
    var wrap = document.createElement("div");
    wrap.innerHTML =
      "<div class=\"post-modal-overlay\" id=\"alumni-post-modal-overlay\" aria-hidden=\"true\">" +
        "<div class=\"post-modal\" role=\"dialog\" aria-modal=\"true\" aria-label=\"Create post\">" +
          "<div class=\"post-modal-head\">" +
            "<div class=\"post-modal-user\">" +
              "<div class=\"composer-avatar\" id=\"alumni-post-modal-avatar\">AL</div>" +
              "<div><div id=\"alumni-post-modal-name\" style=\"font-weight:700;\">Alumni</div>" +
              "<div id=\"alumni-post-modal-role\" class=\"post-meta\">Alumni</div></div></div>" +
            "<button class=\"post-modal-close\" id=\"alumni-post-modal-close\" type=\"button\" aria-label=\"Close\">×</button>" +
          "</div>" +
          "<div class=\"post-modal-body\">" +
            "<textarea id=\"alumni-post-modal-text\" class=\"post-modal-text\" placeholder=\"What do you want to talk about?\"></textarea>" +
            "<div class=\"mention-suggestions\" id=\"alumni-mention-suggestions\"></div>" +
            "<div class=\"post-media-actions\">" +
              "<button class=\"ghost\" type=\"button\" id=\"alumni-modal-photo-btn\">🖼️ Add photo</button>" +
              "<button class=\"ghost\" type=\"button\" id=\"alumni-modal-video-btn\">🎥 Add video</button>" +
            "</div>" +
            "<div class=\"post-media-preview\" id=\"alumni-post-media-preview\">" +
              "<button type=\"button\" class=\"post-media-remove\" id=\"alumni-post-media-remove\" aria-label=\"Remove media\">×</button>" +
              "<div id=\"alumni-post-preview-summary\" style=\"display:none;font-size:12px;color:#475569;padding:8px 0 0;\"></div>" +
              "<img id=\"alumni-post-preview-image\" alt=\"\" style=\"display:none;\" />" +
              "<video id=\"alumni-post-preview-video\" controls style=\"display:none;\"></video>" +
            "</div>" +
          "</div>" +
          "<div class=\"post-modal-foot\">" +
            "<input type=\"file\" id=\"alumni-post-photo-input\" accept=\"image/*\" multiple style=\"display:none\" />" +
            "<input type=\"file\" id=\"alumni-post-video-input\" accept=\"video/mp4,video/webm\" style=\"display:none\" />" +
            "<button class=\"post-submit-btn\" id=\"alumni-post-submit-btn\" type=\"button\" disabled>Post</button>" +
          "</div>" +
        "</div>" +
      "</div>" +
      "<div class=\"share-post-overlay\" id=\"alumni-share-post-overlay\" aria-hidden=\"true\">" +
        "<div class=\"share-post-modal\" role=\"dialog\" aria-modal=\"true\">" +
          "<div class=\"share-post-head\"><span>Share post</span>" +
            "<button class=\"post-modal-close\" id=\"alumni-share-post-close\" type=\"button\">×</button></div>" +
          "<div class=\"share-post-body\">" +
            "<button class=\"ghost\" type=\"button\" id=\"alumni-share-copy-link-btn\">Copy post link</button>" +
            "<div style=\"font-size:12px;color:#64748b;\">Share with your accepted connections</div>" +
            "<div class=\"share-connections-list\" id=\"alumni-share-connections-list\"></div>" +
            "<div style=\"display:flex;justify-content:flex-end;\">" +
              "<button class=\"post-submit-btn\" id=\"alumni-share-send-btn\" type=\"button\">Share to selected</button>" +
            "</div></div></div></div>";
    document.body.appendChild(wrap);
    wireModalEvents();
    domReady = true;
  }

  function updatePostSubmitState() {
    var btn = getEl("alumni-post-submit-btn");
    if (btn) btn.disabled = true;
  }

  function clearPostMediaSelection() {
    selectedPostFiles = [];
    if (selectedPostPreviewUrl) {
      URL.revokeObjectURL(selectedPostPreviewUrl);
      selectedPostPreviewUrl = null;
    }
    var pi = getEl("alumni-post-photo-input");
    var vi = getEl("alumni-post-video-input");
    if (pi) pi.value = "";
    if (vi) vi.value = "";
    var img = getEl("alumni-post-preview-image");
    var vid = getEl("alumni-post-preview-video");
    var sum = getEl("alumni-post-preview-summary");
    var prev = getEl("alumni-post-media-preview");
    if (img) {
      img.style.display = "none";
      img.removeAttribute("src");
    }
    if (vid) {
      vid.style.display = "none";
      vid.pause();
      vid.removeAttribute("src");
    }
    if (sum) {
      sum.style.display = "none";
      sum.textContent = "";
    }
    if (prev) prev.classList.remove("show");
    updatePostSubmitState();
  }

  function setPostFiles(files, type) {
    var valid = Array.prototype.slice.call(files || []).filter(Boolean);
    if (!valid.length) return;
    if (type === "image") {
      var existingImages = selectedPostFiles.filter(function (f) {
        return f.type === "image";
      }).length;
      var allowed = Math.max(0, 5 - existingImages);
      if (allowed <= 0) {
        alert("Maximum 5 images allowed.");
        return;
      }
      var toAdd = valid.slice(0, allowed).map(function (f) {
        return { file: f, type: "image" };
      });
      selectedPostFiles = selectedPostFiles.concat(toAdd);
    } else {
      var hasVideo = selectedPostFiles.some(function (f) {
        return f.type === "video";
      });
      if (hasVideo) {
        alert("Only one video is allowed.");
        return;
      }
      selectedPostFiles.push({ file: valid[0], type: "video" });
    }
    if (selectedPostPreviewUrl) {
      URL.revokeObjectURL(selectedPostPreviewUrl);
      selectedPostPreviewUrl = null;
    }
    var first = selectedPostFiles[0];
    var postPreviewImage = getEl("alumni-post-preview-image");
    var postPreviewVideo = getEl("alumni-post-preview-video");
    if (first) {
      selectedPostPreviewUrl = URL.createObjectURL(first.file || first);
      if (first.type === "image") {
        postPreviewImage.src = selectedPostPreviewUrl;
        postPreviewImage.style.display = "block";
        postPreviewVideo.style.display = "none";
        postPreviewVideo.pause();
        postPreviewVideo.removeAttribute("src");
      } else {
        postPreviewVideo.src = selectedPostPreviewUrl;
        postPreviewVideo.style.display = "block";
        postPreviewImage.style.display = "none";
        postPreviewImage.removeAttribute("src");
      }
    }
    var imgCount = selectedPostFiles.filter(function (f) {
      return f.type === "image";
    }).length;
    var vidCount = selectedPostFiles.filter(function (f) {
      return f.type === "video";
    }).length;
    var postPreviewSummary = getEl("alumni-post-preview-summary");
    if (postPreviewSummary) {
      postPreviewSummary.style.display = "block";
      postPreviewSummary.textContent =
        imgCount + " image" + (imgCount !== 1 ? "s" : "") + (vidCount ? " + 1 video" : "") + " selected";
    }
    getEl("alumni-post-media-preview").classList.add("show");
    updatePostSubmitState();
    openPostModal();
  }

  function openPostModal(opts) {
    opts = opts || {};
    ensureOverlays();
    var overlay = getEl("alumni-post-modal-overlay");
    overlay.classList.add("open");
    overlay.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    getEl("alumni-post-modal-name").textContent = currentUserName || "Alumni";
    getEl("alumni-post-modal-role").textContent = currentUserRole || "Alumni";
    var modalAvatar = getEl("alumni-post-modal-avatar");
    if (modalAvatar) modalAvatar.textContent = getInitials(currentUserName || "Alumni");
    var postSubmitBtn = getEl("alumni-post-submit-btn");
    postSubmitBtn.textContent = editingPostId ? "Save" : "Post";
    if (opts.focusText) setTimeout(function () {
      getEl("alumni-post-modal-text").focus();
    }, 80);
  }

  function closePostModal() {
    var overlay = getEl("alumni-post-modal-overlay");
    if (!overlay) return;
    overlay.classList.remove("open");
    overlay.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    getEl("alumni-post-modal-text").value = "";
    selectedTaggedUsers = [];
    var ms = getEl("alumni-mention-suggestions");
    if (ms) ms.classList.remove("show");
    editingPostId = null;
    getEl("alumni-post-submit-btn").textContent = "Post";
    clearPostMediaSelection();
  }

  function setMentionSuggestions(items) {
    var mentionSuggestionsEl = getEl("alumni-mention-suggestions");
    if (!mentionSuggestionsEl) return;
    mentionSuggestionsEl.innerHTML = "";
    if (!items || !items.length) {
      mentionSuggestionsEl.classList.remove("show");
      return;
    }
    items.forEach(function (u) {
      var row = document.createElement("div");
      row.className = "mention-item";
      row.innerHTML =
        "<span>" + escapeHtml(u.name) + "</span><span style=\"color:var(--muted);\">" +
        escapeHtml((u.role || "").toLowerCase()) + "</span>";
      row.addEventListener("click", function () {
        applyMention(u);
      });
      mentionSuggestionsEl.appendChild(row);
    });
    mentionSuggestionsEl.classList.add("show");
  }

  function applyMention(user) {
    var postModalText = getEl("alumni-post-modal-text");
    if (!postModalText) return;
    var text = postModalText.value || "";
    var m = text.match(/(^|\s)@([A-Za-z0-9_ ]*)$/);
    if (!m) return;
    var prefix = text.slice(0, text.length - m[2].length - 1);
    var mentionText = "@" + user.name;
    postModalText.value = prefix + mentionText + " ";
    postModalText.focus();
    getEl("alumni-mention-suggestions").classList.remove("show");
    if (!selectedTaggedUsers.some(function (x) {
      return x.id === user.id;
    })) {
      selectedTaggedUsers.push({ id: user.id, name: user.name });
    }
  }

  function fetchMentionSuggestions(q) {
    return authFetch("/api/posts/mentions?q=" + encodeURIComponent(q))
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        return data.users || [];
      })
      .catch(function () {
        return [];
      });
  }

  function parseTaggedUsersFromCaption(caption, taggedInfo) {
    var names = {};
    (taggedInfo || []).forEach(function (x) {
      if (x && x.name && x.id) names[String(x.name).toLowerCase()] = x.id;
    });
    var out = [];
    var seen = new Set();
    var matches = caption.match(/@([A-Za-z][A-Za-z0-9_ ]{0,49})/g) || [];
    matches.forEach(function (tok) {
      var n = tok.slice(1).trim().toLowerCase();
      var id = names[n];
      if (id && !seen.has(id)) {
        seen.add(id);
        out.push(id);
      }
    });
    return out;
  }

  function wireModalEvents() {
    var overlay = getEl("alumni-post-modal-overlay");
    var postModalCloseBtn = getEl("alumni-post-modal-close");
    var postModalText = getEl("alumni-post-modal-text");
    var postSubmitBtn = getEl("alumni-post-submit-btn");
    var postPhotoInput = getEl("alumni-post-photo-input");
    var postVideoInput = getEl("alumni-post-video-input");
    var mentionSuggestionsEl = getEl("alumni-mention-suggestions");
    var postMediaRemove = getEl("alumni-post-media-remove");

    postModalCloseBtn.addEventListener("click", closePostModal);
    overlay.addEventListener("click", function (e) {
      if (e.target === overlay) closePostModal();
    });
    postMediaRemove.addEventListener("click", function () {
      if (editingPostId) return;
      clearPostMediaSelection();
    });
    getEl("alumni-modal-photo-btn").addEventListener("click", function () {
      postPhotoInput.click();
    });
    getEl("alumni-modal-video-btn").addEventListener("click", function () {
      postVideoInput.click();
    });
    postPhotoInput.addEventListener("change", function (e) {
      var files = e.target.files;
      if (!files || !files.length) return;
      setPostFiles(files, "image");
    });
    postVideoInput.addEventListener("change", function (e) {
      var files = e.target.files;
      if (!files || !files.length) return;
      setPostFiles(files, "video");
    });
    postModalText.addEventListener("input", function () {
      var text = postModalText.value || "";
      var m = text.match(/(^|\s)@([A-Za-z0-9_ ]*)$/);
      if (!m) {
        if (mentionSuggestionsEl) mentionSuggestionsEl.classList.remove("show");
        return;
      }
      var q = (m[2] || "").trim();
      if (!q) {
        if (mentionSuggestionsEl) mentionSuggestionsEl.classList.remove("show");
        return;
      }
      mentionSearchToken = q;
      if (mentionDebounce) clearTimeout(mentionDebounce);
      mentionDebounce = setTimeout(function () {
        fetchMentionSuggestions(q).then(function (users) {
          if (mentionSearchToken !== q) return;
          setMentionSuggestions(users);
        });
      }, 180);
    });
    postSubmitBtn.addEventListener("click", function () {
      alert("Media post uploads are temporarily disabled.");
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && overlay.classList.contains("open")) closePostModal();
    });
    document.addEventListener("click", function (e) {
      if (!mentionSuggestionsEl || !mentionSuggestionsEl.classList.contains("show")) return;
      if (e.target === postModalText) return;
      if (mentionSuggestionsEl.contains(e.target)) return;
      mentionSuggestionsEl.classList.remove("show");
    });

    var shareOverlay = getEl("alumni-share-post-overlay");
    getEl("alumni-share-post-close").addEventListener("click", closeSharePostModal);
    shareOverlay.addEventListener("click", function (e) {
      if (e.target === shareOverlay) closeSharePostModal();
    });
    getEl("alumni-share-copy-link-btn").addEventListener("click", function () {
      if (!shareTargetPostId) return;
      var link = window.location.origin + "/post/" + encodeURIComponent(shareTargetPostId);
      navigator.clipboard.writeText(link).then(function () {
        alert("Post link copied.");
      }).catch(function () {
        alert(link);
      });
    });
    getEl("alumni-share-send-btn").addEventListener("click", function () {
      var list = getEl("alumni-share-connections-list");
      if (!shareTargetPostId || !list) return;
      var ids = Array.prototype.slice
        .call(list.querySelectorAll("input[type='checkbox']:checked"))
        .map(function (el) {
          return el.value;
        });
      if (!ids.length) return;
      authFetch("/share-post/" + encodeURIComponent(shareTargetPostId), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ connection_user_ids: ids }),
      }).then(function (res) {
        if (!res.ok) return;
        closeSharePostModal();
      });
    });
  }

  function openSharePostModal(postId) {
    ensureOverlays();
    shareTargetPostId = postId;
    var sharePostOverlay = getEl("alumni-share-post-overlay");
    var shareConnectionsList = getEl("alumni-share-connections-list");
    sharePostOverlay.classList.add("open");
    sharePostOverlay.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    shareConnectionsList.innerHTML = "<div class='share-conn-item'>Loading connections...</div>";
    authFetch("/api/connections?status=accepted")
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        var items = data.connections || [];
        if (!items.length) {
          shareConnectionsList.innerHTML = "<div class='share-conn-item'>No accepted connections found.</div>";
          return;
        }
        shareConnectionsList.innerHTML = "";
        items.forEach(function (c) {
          var row = document.createElement("label");
          row.className = "share-conn-item";
          row.innerHTML =
            "<input type=\"checkbox\" value=\"" +
            escapeHtml(c.user_id) +
            "\"><span>" +
            escapeHtml(c.name || "Connection") +
            "</span>";
          shareConnectionsList.appendChild(row);
        });
      })
      .catch(function () {
        shareConnectionsList.innerHTML = "<div class='share-conn-item'>Failed to load connections.</div>";
      });
  }

  function closeSharePostModal() {
    var sharePostOverlay = getEl("alumni-share-post-overlay");
    if (!sharePostOverlay) return;
    sharePostOverlay.classList.remove("open");
    sharePostOverlay.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    shareTargetPostId = null;
  }

  function renderPostContentHtml(item) {
    var text = String(item.body || item.content || item.description || "");
    var html = escapeHtml(text);
    html = html.replace(/(^|\s)#([A-Za-z0-9_]{1,40})/g, function (m, p1, p2) {
      return p1 + '<a class="hashtag-link" href="#" data-hashtag="' + encodeURIComponent(p2.toLowerCase()) + '">#' + p2 + "</a>";
    });
    var mentionMap = {};
    (item.tagged_user_info || []).forEach(function (u) {
      if (u && u.name && u.id) mentionMap[String(u.name).toLowerCase()] = u.id;
    });
    html = html.replace(/(^|\s)@([A-Za-z][A-Za-z0-9_ ]{0,49})/g, function (m, p1, p2) {
      var name = p2.trim();
      var uid = mentionMap[name.toLowerCase()];
      if (!uid) return m;
      return (
        p1 +
        '<a class="mention-link" href="/profile/' +
        encodeURIComponent(uid) +
        '" target="_blank">@' +
        escapeHtml(name) +
        "</a>"
      );
    });
    return html;
  }

  function renderCommentNode(c, ctx) {
    var wrap = document.createElement("div");
    wrap.className = "post-comment-item";
    wrap.dataset.commentId = c.id || "";
    var avatar = document.createElement("div");
    avatar.className = "comment-avatar";
    avatar.textContent = getInitials(c.author_name || "U");
    var bubble = document.createElement("div");
    bubble.className = "comment-bubble";
    var author = document.createElement("div");
    author.className = "comment-author";
    author.textContent = c.author_name || "User";
    var text = document.createElement("div");
    text.className = "comment-text";
    text.textContent = c.text || "";
    var tm = document.createElement("div");
    tm.className = "comment-time";
    tm.textContent = c.timestamp ? formatTimeAgo(c.timestamp) : "";
    bubble.appendChild(author);
    bubble.appendChild(text);
    if (tm.textContent) bubble.appendChild(tm);

    var actions = document.createElement("div");
    actions.className = "comment-actions";
    var likeBtn = document.createElement("button");
    likeBtn.type = "button";
    likeBtn.className = "comment-action-btn comment-like-btn" + (c.liked ? " liked" : "");
    likeBtn.textContent = (c.liked ? "❤️" : "🤍") + " " + (c.likes_count || 0);
    likeBtn.addEventListener("click", function () {
      if (!c.id) return;
      authFetch("/toggle-comment-like/" + encodeURIComponent(c.id), { method: "POST", headers: { "Content-Type": "application/json" } })
        .then(function (res) {
          return res.json();
        })
        .then(function (data) {
          c.liked = !!data.liked;
          c.likes_count = data.likes_count || 0;
          likeBtn.classList.toggle("liked", c.liked);
          likeBtn.textContent = (c.liked ? "❤️" : "🤍") + " " + c.likes_count;
        })
        .catch(function () {});
    });
    actions.appendChild(likeBtn);

    if (!c.parent_id) {
      var replyBtn = document.createElement("button");
      replyBtn.type = "button";
      replyBtn.className = "comment-action-btn";
      replyBtn.textContent = "Reply";
      var replyWrap = document.createElement("div");
      replyWrap.className = "reply-input-wrap";
      replyWrap.style.display = "none";
      var replyInput = document.createElement("input");
      replyInput.type = "text";
      replyInput.placeholder = "Write a reply...";
      var replySubmit = document.createElement("button");
      replySubmit.type = "button";
      replySubmit.className = "ghost";
      replySubmit.textContent = "Reply";
      replySubmit.addEventListener("click", function () {
        var replyText = (replyInput.value || "").trim();
        if (!replyText || !c.id) return;
        authFetch("/add-reply/" + encodeURIComponent(c.id), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: replyText }),
        })
          .then(function (res) {
            return res.json();
          })
          .then(function (data) {
            c.replies = c.replies || [];
            if (data.reply) c.replies.push(data.reply);
            c.reply_count = (c.reply_count || 0) + 1;
            replyInput.value = "";
            replyWrap.style.display = "none";
            if (ctx.reloadComments) return ctx.reloadComments(true);
          })
          .catch(function () {});
      });
      replyWrap.appendChild(replyInput);
      replyWrap.appendChild(replySubmit);
      replyBtn.addEventListener("click", function () {
        replyWrap.style.display = replyWrap.style.display === "none" ? "flex" : "none";
        if (replyWrap.style.display === "flex") replyInput.focus();
      });
      actions.appendChild(replyBtn);
      bubble.appendChild(replyWrap);
    }

    bubble.appendChild(actions);

    if (Array.isArray(c.replies) && c.replies.length) {
      var replies = document.createElement("div");
      replies.className = "comment-replies";
      c.replies.forEach(function (r) {
        replies.appendChild(renderCommentNode(r, ctx));
      });
      bubble.appendChild(replies);
    }
    wrap.appendChild(avatar);
    wrap.appendChild(bubble);
    return wrap;
  }

  function createPostElement(item) {
    var article = document.createElement("article");
    article.className = "post";
    if (item.id) article.dataset.postId = item.id;

    var head = document.createElement("div");
    head.className = "post-head";

    var userDiv = document.createElement("div");
    userDiv.className = "post-user";

    var miniAvatar = document.createElement("div");
    miniAvatar.className = "mini-avatar";
    miniAvatar.textContent = getInitials(
      (item.author && item.author.name) || item.student_name || item.title || "CL"
    );

    var userMeta = document.createElement("div");
    var titleEl = document.createElement("div");
    titleEl.style.fontWeight = "700";
    titleEl.textContent = (item.author && item.author.name) || item.student_name || item.title || "Post";
    var metaEl = document.createElement("div");
    metaEl.className = "post-meta";
    var roleText = (item.author && item.author.role) || "";
    var roleLabel = roleText ? (String(roleText).toUpperCase() === "ALUMNI" ? "Alumni" : "Student") : "";
    metaEl.textContent = [roleLabel, item.branch, item.created_at ? formatTimeAgo(item.created_at) : ""]
      .filter(Boolean)
      .join(" · ");
    userMeta.appendChild(titleEl);
    if (metaEl.textContent) userMeta.appendChild(metaEl);
    userDiv.appendChild(miniAvatar);
    userDiv.appendChild(userMeta);
    head.appendChild(userDiv);

    var isOwner = currentUserId && item.author_id && String(currentUserId) === String(item.author_id);
    if (isOwner) {
      var ownerMenu = document.createElement("div");
      ownerMenu.className = "post-owner-menu";
      var dots = document.createElement("button");
      dots.type = "button";
      dots.className = "post-owner-dots";
      dots.textContent = "⋯";
      var dd = document.createElement("div");
      dd.className = "post-owner-dropdown";
      var delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.textContent = "Delete Post";
      delBtn.addEventListener("click", function () {
        dd.classList.remove("show");
        if (!confirm("Delete this post?")) return;
        authFetch("/delete-post/" + encodeURIComponent(item.id), { method: "POST" }).then(function (res) {
          if (res.status === 401) {
            window.location.href = "/login";
            return;
          }
          if (!res.ok) return;
          article.remove();
        });
      });
      dd.appendChild(delBtn);
      dots.addEventListener("click", function (e) {
        e.stopPropagation();
        dd.classList.toggle("show");
      });
      ownerMenu.appendChild(dots);
      ownerMenu.appendChild(dd);
      head.appendChild(ownerMenu);
    }

    var body = document.createElement("div");
    body.className = "post-body";
    body.innerHTML = renderPostContentHtml(item);

    article.appendChild(head);
    article.appendChild(body);

    var mediaList = [];
    var slides = [];
    mediaList.forEach(function (m) {
      if (!m || !m.url) return;
      var t = (m.type || "").toLowerCase();
      if (t === "video") slides.push({ type: "video", url: m.url });
      else slides.push({ type: "image", url: m.url });
    });
    if (slides.length) {
      var mediaWrap = document.createElement("div");
      mediaWrap.className = "post-media post-media-carousel";
      mediaWrap.style.maxWidth = "100%";
      if (slides.length > 1) mediaWrap.classList.add("post-media-carousel--multi");

      var viewport = document.createElement("div");
      viewport.className = "post-media-viewport";

      var slideIndex = 0;
      function renderSlide() {
        viewport.innerHTML = "";
        var s = slides[slideIndex];
        if (s.type === "video") {
          var vid = document.createElement("video");
          vid.className = "post-media-slide-el";
          vid.src = s.url;
          vid.controls = true;
          vid.setAttribute("playsinline", "");
          viewport.appendChild(vid);
        } else {
          var img = document.createElement("img");
          img.className = "post-media-slide-el";
          img.src = s.url;
          img.alt = "";
          img.loading = "lazy";
          viewport.appendChild(img);
        }
      }
      renderSlide();

      if (slides.length > 1) {
        var prevBtn = document.createElement("button");
        prevBtn.type = "button";
        prevBtn.className = "post-media-nav post-media-nav-prev";
        prevBtn.setAttribute("aria-label", "Previous photo or video");
        prevBtn.textContent = "<";
        prevBtn.addEventListener("click", function (e) {
          e.stopPropagation();
          slideIndex = (slideIndex - 1 + slides.length) % slides.length;
          renderSlide();
        });
        var nextBtn = document.createElement("button");
        nextBtn.type = "button";
        nextBtn.className = "post-media-nav post-media-nav-next";
        nextBtn.setAttribute("aria-label", "Next photo or video");
        nextBtn.textContent = ">";
        nextBtn.addEventListener("click", function (e) {
          e.stopPropagation();
          slideIndex = (slideIndex + 1) % slides.length;
          renderSlide();
        });
        mediaWrap.appendChild(prevBtn);
        mediaWrap.appendChild(viewport);
        mediaWrap.appendChild(nextBtn);
      } else {
        mediaWrap.appendChild(viewport);
      }
      article.appendChild(mediaWrap);
    }

    if (item.id) {
      var statsRow = document.createElement("div");
      statsRow.className = "post-stats";
      var likeStat = document.createElement("div");
      likeStat.className = "post-stat-like";
      likeStat.textContent = "❤ " + (item.likes_count || 0) + " Likes";
      var commentStat = document.createElement("div");
      commentStat.textContent =
        (item.comments_count || 0) + " Comment" + ((item.comments_count || 0) !== 1 ? "s" : "");
      statsRow.appendChild(likeStat);
      statsRow.appendChild(commentStat);
      article.appendChild(statsRow);

      var footer = document.createElement("div");
      footer.className = "post-actions";
      footer.style.display = "flex";
      footer.style.gap = "8px";
      footer.style.marginTop = "4px";
      footer.style.paddingTop = "6px";
      footer.style.borderTop = "1px solid var(--border)";

      var likeBtn = document.createElement("button");
      likeBtn.type = "button";
      likeBtn.className = "post-action-btn";
      likeBtn.style.color = item.liked ? "#0A66C2" : "inherit";
      likeBtn.textContent = "👍 Like";

      var commentBtn = document.createElement("button");
      commentBtn.type = "button";
      commentBtn.className = "post-action-btn";
      commentBtn.textContent = "💬 Comment";

      var shareBtn = document.createElement("button");
      shareBtn.type = "button";
      shareBtn.className = "post-action-btn";
      shareBtn.textContent = "↪ Share";

      likeBtn.addEventListener("click", function () {
        authFetch("/toggle-like/" + encodeURIComponent(item.id), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        })
          .then(function (res) {
            if (res.status === 401) {
              window.location.href = "/login";
              return;
            }
            return res.json();
          })
          .then(function (data) {
            if (!data) return;
            item.liked = data.liked;
            item.likes_count = data.likes_count;
            likeBtn.style.color = item.liked ? "#0A66C2" : "inherit";
            likeStat.textContent = "❤ " + (item.likes_count || 0) + " Likes";
          })
          .catch(function () {});
      });

      var commentsList = document.createElement("div");
      commentsList.className = "post-comments";
      var viewAllBtn = document.createElement("button");
      viewAllBtn.type = "button";
      viewAllBtn.className = "view-all-comments-btn";
      viewAllBtn.textContent = "View all comments";
      viewAllBtn.style.display = "none";
      var commentsExpanded = false;
      var commentsCache = [];

      var renderCommentsUi = function (arr) {
        commentsList.innerHTML = "";
        if (!Array.isArray(arr) || !arr.length) return;
        var renderArr = commentsExpanded ? arr : arr.slice(0, 2);
        renderArr.forEach(function (c) {
          commentsList.appendChild(
            renderCommentNode(c, {
              reloadComments: function (all) {
                return loadComments(all);
              },
              showAllReplies: commentsExpanded,
            })
          );
        });
        viewAllBtn.style.display = arr.length > 2 ? "inline-block" : "none";
        viewAllBtn.textContent = commentsExpanded ? "Show less comments" : "View all comments";
      };

      var loadComments = function (all) {
        var q = all ? "all=1" : "limit=2";
        return authFetch("/comments/" + encodeURIComponent(item.id) + "?" + q)
          .then(function (res) {
            return res.json();
          })
          .then(function (data) {
            commentsCache = data.comments || [];
            item.comments_count = data.count || item.comments_count || 0;
            commentStat.textContent =
              item.comments_count + " Comment" + (item.comments_count !== 1 ? "s" : "");
            renderCommentsUi(commentsCache);
          })
          .catch(function () {});
      };

      viewAllBtn.addEventListener("click", function () {
        commentsExpanded = !commentsExpanded;
        if (commentsExpanded) {
          loadComments(true);
        } else {
          renderCommentsUi(commentsCache);
        }
      });

      var commentWrap = document.createElement("div");
      commentWrap.style.display = "flex";
      commentWrap.style.alignItems = "center";
      commentWrap.style.gap = "8px";
      commentWrap.style.flexWrap = "wrap";
      var commentInput = document.createElement("input");
      commentInput.type = "text";
      commentInput.placeholder = "Write a comment...";
      commentInput.style.flex = "1";
      commentInput.style.minWidth = "120px";
      commentInput.style.padding = "6px 10px";
      commentInput.style.borderRadius = "6px";
      commentInput.style.border = "1px solid var(--border)";
      commentInput.style.background = "#fff";
      commentInput.style.color = "var(--text)";
      commentInput.style.fontSize = "13px";
      var commentSubmit = document.createElement("button");
      commentSubmit.type = "button";
      commentSubmit.className = "ghost";
      commentSubmit.textContent = "Comment";
      commentSubmit.style.cursor = "pointer";
      commentSubmit.style.fontSize = "12px";
      commentSubmit.addEventListener("click", function () {
        var txt = (commentInput.value || "").trim();
        if (!txt) return;
        authFetch("/add-comment/" + encodeURIComponent(item.id), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: txt }),
        })
          .then(function (res) {
            if (res.status === 401) {
              window.location.href = "/login";
              return;
            }
            return res.json();
          })
          .then(function (data) {
            if (!data) return;
            item.comments_count = data.comments_count;
            commentStat.textContent =
              data.comments_count + " Comment" + (data.comments_count !== 1 ? "s" : "");
            if (data.comment) {
              commentsCache = [data.comment].concat(commentsCache || []);
              if (!commentsExpanded) commentsCache = commentsCache.slice(0, 2);
              renderCommentsUi(commentsCache);
            } else {
              loadComments(commentsExpanded);
            }
            commentInput.value = "";
          })
          .catch(function () {});
      });

      commentBtn.addEventListener("click", function () {
        commentsExpanded = true;
        loadComments(true).then(function () {
          commentInput.focus();
        });
      });
      shareBtn.addEventListener("click", function () {
        openSharePostModal(item.id);
      });

      footer.appendChild(likeBtn);
      footer.appendChild(commentBtn);
      footer.appendChild(shareBtn);
      article.appendChild(footer);
      article.appendChild(commentsList);
      article.appendChild(viewAllBtn);
      var commentRow = document.createElement("div");
      commentRow.className = "post-comment-row";
      commentRow.style.marginTop = "8px";
      commentRow.style.paddingTop = "8px";
      commentRow.style.borderTop = "1px solid var(--border)";
      commentWrap.appendChild(commentInput);
      commentWrap.appendChild(commentSubmit);
      commentRow.appendChild(commentWrap);
      article.appendChild(commentRow);
      loadComments(false);
    }

    return article;
  }

  function loadFeed(container, feedLoadingEl, reset) {
    if (feedLoading) return;
    if (!feedHasMore && !reset) return;
    feedLoading = true;
    if (feedLoadingEl) feedLoadingEl.style.display = "block";
    if (reset) {
      feedSkip = 0;
      feedHasMore = true;
      container.innerHTML = "";
    }
    AlumniApi.dashboardFeed(10, feedSkip)
      .then(function (data) {
        var posts = (data && data.posts) || [];
        if (data && data.current_user_id) currentUserId = data.current_user_id;
        if (!posts.length && reset) {
          var empty = document.createElement("div");
          empty.className = "post";
          empty.id = "unified-feed-empty";
          empty.innerHTML =
            "<div class=\"post-body\">No media posts yet. Posts with image/video from students and alumni will appear here.</div>";
          container.appendChild(empty);
          feedHasMore = false;
          return;
        }
        var emptyEl = container.querySelector("#unified-feed-empty");
        if (emptyEl) emptyEl.remove();
        posts.forEach(function (p) {
          container.appendChild(createPostElement(p));
        });
        feedSkip += posts.length;
        feedHasMore = Boolean(data && data.has_more);
      })
      .catch(function () {
        if (reset) {
          container.innerHTML =
            "<div class=\"post\"><div class=\"post-body\">Could not load feed.</div></div>";
        }
      })
      .then(function () {
        feedLoading = false;
        if (feedLoadingEl) feedLoadingEl.style.display = "none";
      });
  }

  function loadAnnouncements(feedEl) {
    AlumniApi.announcementsFeed()
      .then(function (data) {
        var items = (data && data.items) || [];
        feedEl.innerHTML = "";
        if (!items.length) {
          var empty = document.createElement("p");
          empty.className = "card-sub";
          empty.style.margin = "0";
          empty.style.padding = "0 4px";
          empty.textContent = "No announcements yet.";
          feedEl.appendChild(empty);
          return;
        }
        items.forEach(function (n) {
          var card = document.createElement("article");
          card.className = "alumni-announcement-card";
          var title = document.createElement("h3");
          title.className = "alumni-announcement-title";
          title.textContent = n.title || "Announcement";
          var desc = document.createElement("div");
          desc.className = "alumni-announcement-desc";
          desc.textContent = n.description || n.body || "";
          card.appendChild(title);
          if (desc.textContent) card.appendChild(desc);
          var meta = document.createElement("div");
          meta.className = "alumni-announcement-meta";
          var posted = (n.posted_by || n.created_by || "").trim();
          var when = n.created_at ? new Date(n.created_at).toLocaleString() : "";
          meta.textContent = [posted && "Posted by " + posted, when].filter(Boolean).join(" · ");
          if (meta.textContent) card.appendChild(meta);
          if (window.CampusLinkAnnouncementMediaUI) {
            window.CampusLinkAnnouncementMediaUI.appendItems(card, n);
          }
          feedEl.appendChild(card);
        });
      })
      .catch(function () {
        feedEl.innerHTML = "<p class=\"card-sub\" style=\"margin:0;padding:0 4px;\">No announcements yet.</p>";
      });
  }

  function render(root) {
    ensureOverlays();
    root.innerHTML = "";

    var layout = document.createElement("main");
    layout.className = "layout alumni-feed-layout";

    var left = document.createElement("section");
    left.className = "left";

    var composerCard = document.createElement("div");
    composerCard.className = "card";
    var composerInner = document.createElement("div");
    composerInner.className = "composer-card";
    composerInner.innerHTML =
      "<div class=\"composer-top\">" +
        "<div class=\"composer-avatar\" id=\"alumni-composer-avatar\">AL</div>" +
        "<button type=\"button\" class=\"composer-start-btn\" id=\"alumni-start-post-trigger\">Start a post...</button>" +
      "</div>" +
      "<div class=\"composer-actions\">" +
        "<button class=\"ghost\" type=\"button\" id=\"alumni-post-video-trigger\">🎥 Video</button>" +
        "<button class=\"ghost\" type=\"button\" id=\"alumni-post-photo-trigger\">🖼️ Photo</button>" +
        "<button class=\"ghost\" type=\"button\" id=\"alumni-post-article-trigger\">✍️ Write article</button>" +
      "</div>";
    composerCard.appendChild(composerInner);

    var feedCard = document.createElement("div");
    feedCard.className = "card";
    var feedHeader = document.createElement("div");
    feedHeader.className = "card-header";
    feedHeader.textContent = "Feed";
    var feed = document.createElement("div");
    feed.className = "feed";
    feed.id = "alumni-unified-feed";
    var feedLoadingEl = document.createElement("div");
    feedLoadingEl.className = "feed-loading";
    feedLoadingEl.id = "alumni-feed-loading";
    feedLoadingEl.style.display = "none";
    feedLoadingEl.textContent = "Loading more posts...";
    feedCard.appendChild(feedHeader);
    feedCard.appendChild(feed);
    feedCard.appendChild(feedLoadingEl);

    left.appendChild(composerCard);
    left.appendChild(feedCard);

    var aside = document.createElement("aside");
    aside.className = "right";
    var noticeCard = document.createElement("div");
    noticeCard.className = "card";
    noticeCard.id = "campuslink-announcements-panel";
    var nh = document.createElement("div");
    nh.className = "card-header";
    nh.textContent = "Announcements";
    var announcementsFeedEl = document.createElement("div");
    announcementsFeedEl.className = "alumni-announcements-feed";
    announcementsFeedEl.id = "alumni-announcements-feed";
    var loading = document.createElement("p");
    loading.className = "card-sub";
    loading.style.margin = "0";
    loading.style.padding = "0 4px";
    loading.textContent = "Loading…";
    announcementsFeedEl.appendChild(loading);
    noticeCard.appendChild(nh);
    noticeCard.appendChild(announcementsFeedEl);
    aside.appendChild(noticeCard);

    var jobsCard = document.createElement("div");
    jobsCard.className = "card";
    jobsCard.innerHTML =
      "<div class=\"card-header\">💼 Job postings</div>" +
      "<p class=\"card-sub\" style=\"padding:0 14px 12px;margin:0;font-size:12px;color:var(--muted);\">Manage roles you post for students.</p>" +
      "<div style=\"padding:0 14px 14px;\"><a class=\"ghost\" href=\"#/jobs\" style=\"text-decoration:none;display:inline-flex;\">Open job dashboard →</a></div>";
    aside.appendChild(jobsCard);

    layout.appendChild(left);
    layout.appendChild(aside);
    root.appendChild(layout);

    document.getElementById("alumni-start-post-trigger").addEventListener("click", function () {
      openPostModal();
    });
    document.getElementById("alumni-post-article-trigger").addEventListener("click", function () {
      openPostModal({ focusText: true });
    });
    document.getElementById("alumni-post-photo-trigger").addEventListener("click", function () {
      getEl("alumni-post-photo-input").click();
    });
    document.getElementById("alumni-post-video-trigger").addEventListener("click", function () {
      getEl("alumni-post-video-input").click();
    });

    window.__alumniFeedReload = function (reset) {
      loadFeed(feed, feedLoadingEl, reset);
    };
    loadFeed(feed, feedLoadingEl, true);
    loadAnnouncements(document.getElementById("alumni-announcements-feed"));
    setTimeout(function () {
      try {
        if (sessionStorage.getItem("campuslink_scroll_announcements")) {
          sessionStorage.removeItem("campuslink_scroll_announcements");
          var ann = document.getElementById("campuslink-announcements-panel");
          if (ann) ann.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
      } catch (e) {}
    }, 450);

    AlumniApi.me()
      .then(function (me) {
        currentUserName = (me && me.name) || "Alumni";
        currentUserRole = "Alumni";
        var av = document.getElementById("alumni-composer-avatar");
        if (av) av.textContent = getInitials(currentUserName);
      })
      .catch(function () {});

    var io = new IntersectionObserver(
      function (ents) {
        ents.forEach(function (en) {
          if (en.isIntersecting && feedHasMore && !feedLoading) loadFeed(feed, feedLoadingEl, false);
        });
      },
      { rootMargin: "120px" }
    );
    var sentinel = document.createElement("div");
    sentinel.style.height = "1px";
    feed.appendChild(sentinel);
    io.observe(sentinel);

    document.addEventListener("click", function (e) {
      var a = e.target.closest && e.target.closest("a.hashtag-link[data-hashtag]");
      if (!a) return;
      e.preventDefault();
    });
  }

  return { render: render };
})();
