/* CampusLink Coordinator API client (JWT) */

class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

window.CampusLinkApi = (() => {
  const TOKEN_KEY = "campuslink_token";

  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }

  function clearToken() {
    localStorage.removeItem(TOKEN_KEY);
  }

  async function request(path, opts = {}) {
    const {
      method = "GET",
      body,
      headers = {},
      signal,
    } = opts;

    const token = getToken();
    const mergedHeaders = {
      ...headers,
    };

    if (body != null && !mergedHeaders["Content-Type"]) {
      mergedHeaders["Content-Type"] = "application/json";
    }
    if (token) {
      mergedHeaders["Authorization"] = `Bearer ${token}`;
    }

    const res = await fetch(path, {
      method,
      headers: mergedHeaders,
      body: body != null ? JSON.stringify(body) : undefined,
      signal,
    });

    const contentType = res.headers.get("content-type") || "";
    const isJson = contentType.includes("application/json");
    const data = isJson ? await res.json().catch(() => null) : await res.text().catch(() => null);

    if (res.status === 401) {
      clearToken();
      throw new ApiError((data && data.error) || "Unauthorized", 401, data);
    }
    if (!res.ok) {
      throw new ApiError((data && data.error) || "Request failed", res.status, data);
    }

    return data;
  }

  return {
    request,
    get: (path) => request(path),
    post: (path, body) => request(path, { method: "POST", body }),
    put: (path, body) => request(path, { method: "PUT", body }),
    del: (path) => request(path, { method: "DELETE" }),
    me: () => request("/api/auth/me"),
    overview: () => request("/api/coordinator/overview"),
    alumniRequests: (status) =>
      request(`/api/coordinator/alumni-requests${status ? "?status=" + encodeURIComponent(status) : ""}`),
    approveAlumniRequest: (id) =>
      request(`/api/coordinator/alumni-requests/${encodeURIComponent(id)}/approve`, { method: "POST" }),
    rejectAlumniRequest: (id) =>
      request(`/api/coordinator/alumni-requests/${encodeURIComponent(id)}/reject`, { method: "POST" }),
  };
})();

