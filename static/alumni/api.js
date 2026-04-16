/* CampusLink Alumni API client (session + optional JWT) */

(function () {
  function ApiError(message, status, data) {
    this.name = "ApiError";
    this.message = message;
    this.status = status;
    this.data = data;
  }
  ApiError.prototype = Object.create(Error.prototype);

  var TOKEN_KEY = "campuslink_token";

  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }

  function request(path, opts) {
    opts = opts || {};
    var method = opts.method || "GET";
    var body = opts.body;
    var headers = opts.headers || {};
    if (body != null && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    var token = getToken();
    if (token) {
      headers["Authorization"] = "Bearer " + token;
    }
    var fetchOpts = {
      method: method,
      headers: headers,
      credentials: "same-origin",
    };
    if (body != null) {
      fetchOpts.body = typeof body === "string" ? body : JSON.stringify(body);
    }

    return fetch(path, fetchOpts).then(function (res) {
      var contentType = res.headers.get("content-type") || "";
      var isJson = contentType.indexOf("application/json") !== -1;
      var dataPromise = isJson ? res.json().catch(function () { return null; }) : res.text().then(function () { return null; });
      return dataPromise.then(function (data) {
        if (res.status === 401) {
          localStorage.removeItem(TOKEN_KEY);
          throw new ApiError((data && data.error) || "Unauthorized", 401, data);
        }
        if (!res.ok) {
          throw new ApiError((data && data.error) || "Request failed", res.status, data);
        }
        return data;
      });
    });
  }

  window.AlumniApi = {
    get: function (path) { return request(path); },
    post: function (path, body) { return request(path, { method: "POST", body: body }); },
    put: function (path, body) { return request(path, { method: "PUT", body: body }); },
    patch: function (path, body) { return request(path, { method: "PATCH", body: body }); },
    del: function (path) { return request(path, { method: "DELETE" }); },
    me: function () { return request("/api/auth/me"); },
    dashboard: function () { return request("/api/alumni/dashboard"); },
    profileGet: function () { return request("/api/alumni/profile"); },
    profilePut: function (body) { return request("/api/alumni/profile", { method: "PUT", body: body }); },
    profileNotesMediaUpload: function (file) {
      var token = getToken();
      var headers = {};
      if (token) headers["Authorization"] = "Bearer " + token;
      var fd = new FormData();
      fd.append("file", file);
      return fetch("/api/alumni/profile/notes-media", {
        method: "POST",
        credentials: "same-origin",
        headers: headers,
        body: fd,
      }).then(function (res) {
        return res.json().then(function (data) {
          if (!res.ok) throw new ApiError((data && data.error) || "Upload failed", res.status, data);
          return data;
        });
      });
    },
    profileExperienceMediaUpload: function (itemId, file) {
      var token = getToken();
      var headers = {};
      if (token) headers["Authorization"] = "Bearer " + token;
      var fd = new FormData();
      fd.append("file", file);
      return fetch("/api/alumni/profile/experience/" + encodeURIComponent(itemId) + "/media", {
        method: "POST",
        credentials: "same-origin",
        headers: headers,
        body: fd,
      }).then(function (res) {
        return res.json().then(function (data) {
          if (!res.ok) throw new ApiError((data && data.error) || "Upload failed", res.status, data);
          return data;
        });
      });
    },
    profileProjectMediaUpload: function (itemId, file) {
      var token = getToken();
      var headers = {};
      if (token) headers["Authorization"] = "Bearer " + token;
      var fd = new FormData();
      fd.append("file", file);
      return fetch("/api/alumni/profile/projects/" + encodeURIComponent(itemId) + "/media", {
        method: "POST",
        credentials: "same-origin",
        headers: headers,
        body: fd,
      }).then(function (res) {
        return res.json().then(function (data) {
          if (!res.ok) throw new ApiError((data && data.error) || "Upload failed", res.status, data);
          return data;
        });
      });
    },
    profileCertificationMediaUpload: function (itemId, file) {
      var token = getToken();
      var headers = {};
      if (token) headers["Authorization"] = "Bearer " + token;
      var fd = new FormData();
      fd.append("file", file);
      return fetch("/api/alumni/profile/certifications/" + encodeURIComponent(itemId) + "/media", {
        method: "POST",
        credentials: "same-origin",
        headers: headers,
        body: fd,
      }).then(function (res) {
        return res.json().then(function (data) {
          if (!res.ok) throw new ApiError((data && data.error) || "Upload failed", res.status, data);
          return data;
        });
      });
    },
    profileAchievementMediaUpload: function (itemId, file) {
      var token = getToken();
      var headers = {};
      if (token) headers["Authorization"] = "Bearer " + token;
      var fd = new FormData();
      fd.append("file", file);
      return fetch("/api/alumni/profile/achievements/" + encodeURIComponent(itemId) + "/media", {
        method: "POST",
        credentials: "same-origin",
        headers: headers,
        body: fd,
      }).then(function (res) {
        return res.json().then(function (data) {
          if (!res.ok) throw new ApiError((data && data.error) || "Upload failed", res.status, data);
          return data;
        });
      });
    },
    mentorshipList: function (status) {
      var path = "/api/alumni/mentorship";
      if (status) path += "?status=" + encodeURIComponent(status);
      return request(path);
    },
    mentorshipPatch: function (id, body) { return request("/api/alumni/mentorship/" + encodeURIComponent(id), { method: "PATCH", body: body }); },
    mentorshipMentee: function (id) { return request("/api/alumni/mentorship/" + encodeURIComponent(id) + "/mentee"); },
    referralsList: function (status) {
      var path = "/api/alumni/referrals";
      if (status) path += "?status=" + encodeURIComponent(status);
      return request(path);
    },
    referralsPatch: function (id, body) { return request("/api/alumni/referrals/" + encodeURIComponent(id), { method: "PATCH", body: body }); },
    referralStudent: function (id) { return request("/api/alumni/referrals/" + encodeURIComponent(id) + "/student"); },
    jobsList: function () { return request("/api/alumni/jobs"); },
    jobsPost: function (body) { return request("/api/alumni/jobs", { method: "POST", body: body }); },
    jobGet: function (id) { return request("/api/alumni/jobs/" + encodeURIComponent(id)); },
    jobPut: function (id, body) { return request("/api/alumni/jobs/" + encodeURIComponent(id), { method: "PUT", body: body }); },
    jobDelete: function (id) { return request("/api/alumni/jobs/" + encodeURIComponent(id), { method: "DELETE" }); },
    jobApplicants: function (id) { return request("/api/alumni/jobs/" + encodeURIComponent(id) + "/applicants"); },
    settingsGet: function () { return request("/api/alumni/settings"); },
    settingsPut: function (body) { return request("/api/alumni/settings", { method: "PUT", body: body }); },
    changePassword: function (body) { return request("/api/alumni/change-password", { method: "POST", body: body }); },
    updateEmail: function (body) { return request("/api/alumni/update-email", { method: "PUT", body: body }); },
    logoutAll: function () { return request("/api/alumni/logout-all", { method: "POST" }); },
    searchUsers: function (q, type) {
      var qs = "?q=" + encodeURIComponent(q || "");
      if (type && type !== "all") qs += "&type=" + encodeURIComponent(type);
      return request("/api/search/users" + qs);
    },
    connections: function (status) {
      var path = "/api/connections";
      if (status) path += "?status=" + encodeURIComponent(status);
      return request(path);
    },
    connectionRequest: function (userId) {
      return request("/api/connections/request", { method: "POST", body: { user_id: userId } });
    },
    connectionRespond: function (connectionId, action) {
      return request("/api/connections/" + encodeURIComponent(connectionId) + "/respond", {
        method: "POST",
        body: { action: action },
      });
    },
    dashboardFeed: function (limit, skip) {
      var l = limit != null ? limit : 10;
      var s = skip != null ? skip : 0;
      return request("/api/dashboard/student-posts?limit=" + encodeURIComponent(l) + "&skip=" + encodeURIComponent(s));
    },
    announcementsFeed: function () {
      return request("/api/dashboard/important-notices");
    },
    importantNotices: function () {
      return request("/api/dashboard/important-notices");
    },
    postMedia: function (formData) {
      var token = getToken();
      var headers = {};
      if (token) headers["Authorization"] = "Bearer " + token;
      return fetch("/api/posts/media", {
        method: "POST",
        credentials: "same-origin",
        headers: headers,
        body: formData,
      }).then(function (res) {
        return res.json().then(function (data) {
          if (!res.ok) throw new ApiError((data && data.error) || "Upload failed", res.status, data);
          return data;
        });
      });
    },
    postLike: function (postId) {
      return request("/api/posts/" + encodeURIComponent(postId) + "/like", { method: "POST" });
    },
    postUnlike: function (postId) {
      return request("/api/posts/" + encodeURIComponent(postId) + "/like", { method: "DELETE" });
    },
    // Back-compat alias (older pages)
    notesMediaUpload: function (file) { return window.AlumniApi.profileNotesMediaUpload(file); },
  };
})();
