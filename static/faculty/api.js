/* CampusLink Faculty API (session auth, department-scoped) */

window.FacultyApi = (function () {
  function request(path, opts) {
    opts = opts || {};
    var method = opts.method || "GET";
    var body = opts.body;
    var headers = opts.headers || {};
    if (body != null && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
    return fetch(path, {
      method: method,
      headers: headers,
      credentials: "same-origin",
      body: body != null ? JSON.stringify(body) : undefined,
    }).then(function (res) {
      var ct = res.headers.get("content-type") || "";
      var data = ct.indexOf("application/json") !== -1 ? res.json().catch(function () { return null; }) : res.text().then(function () { return null; });
      return data.then(function (d) {
        if (!res.ok) throw { status: res.status, message: (d && d.error) || "Request failed", data: d };
        return d;
      });
    });
  }
  return {
    get: function (path) { return request(path); },
    post: function (path, body) { return request(path, { method: "POST", body: body }); },
    listStudents: function (status) {
      var path = "/api/faculty/students";
      if (status) path += "?status=" + encodeURIComponent(status);
      return request(path);
    },
    verifyStudent: function (id, status, remark) {
      return request("/api/faculty/students/" + encodeURIComponent(id) + "/verify", { method: "POST", body: { status: status, remark: remark || undefined } });
    },
    unverifyStudent: function (id) {
      return request("/api/faculty/students/" + encodeURIComponent(id) + "/unverify", { method: "POST", body: {} });
    },
    sendCorrectionMessage: function (id, message) {
      return request("/api/faculty/students/" + encodeURIComponent(id) + "/correction-message", { method: "POST", body: { message: message } });
    },
    listApplications: function () { return request("/api/faculty/applications"); },
    listHelpThreads: function () { return request("/api/faculty/help/threads"); },
    getHelpThread: function (threadId) { return request("/api/faculty/help/threads/" + encodeURIComponent(threadId)); },
    sendHelpReply: function (threadId, content) { return request("/api/faculty/help/threads/" + encodeURIComponent(threadId) + "/messages", { method: "POST", body: { content: content } }); },
  };
})();
