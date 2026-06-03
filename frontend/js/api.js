// Lightweight fetch wrapper. Auto-attaches the CSRF header for state-changing requests.

function getCookie(name) {
  const match = document.cookie.match(new RegExp("(?:^|; )" + name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "=([^;]*)"));
  return match ? decodeURIComponent(match[1]) : null;
}

async function request(path, { method = "GET", body, headers = {}, raw = false } = {}) {
  const init = {
    method,
    credentials: "same-origin",
    headers: { ...headers },
  };
  if (body !== undefined) {
    if (body instanceof FormData) {
      init.body = body; // browser sets multipart boundary
    } else {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
  }
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = getCookie("sc_csrf");
    if (csrf) init.headers["X-CSRF-Token"] = csrf;
  }

  const res = await fetch(path, init);
  if (raw) return res;

  let data = null;
  const text = await res.text();
  if (text) {
    try { data = JSON.parse(text); } catch { data = { detail: text }; }
  }

  if (!res.ok) {
    const message = (data && data.detail) || `Request failed (${res.status})`;
    const err = new Error(message);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

export const api = {
  // Auth
  register: (payload) => request("/api/auth/register", { method: "POST", body: payload }),
  login:    (payload) => request("/api/auth/login",    { method: "POST", body: payload }),
  logout:   ()         => request("/api/auth/logout",   { method: "POST" }),
  me:       ()         => request("/api/auth/me"),
  refreshCsrf: ()      => request("/api/auth/csrf"),

  // Verify
  verifyFace: (formData) => request("/api/verify/face", { method: "POST", body: formData }),
  requestOrgOtp: (payload) => request("/api/verify/org/request", { method: "POST", body: payload }),
  confirmOrgOtp: (payload) => request("/api/verify/org/confirm", { method: "POST", body: payload }),

  // Groups
  discover: (lat, lon) => request(`/api/groups/discover?lat=${encodeURIComponent(lat)}&lon=${encodeURIComponent(lon)}`),
  joinGroup:  (id) => request(`/api/groups/${id}/join`, { method: "POST" }),
  leaveGroup: (id) => request(`/api/groups/${id}/leave`, { method: "POST" }),

  // Group chat
  messages: (id, { before = null, limit = 50 } = {}) => {
    const p = new URLSearchParams({ limit: String(limit) });
    if (before != null) p.set("before", String(before));
    return request(`/api/groups/${id}/messages?${p}`);
  },
  editMessage: (id, msgId, body) =>
    request(`/api/groups/${id}/messages/${msgId}`, { method: "PATCH", body: { body } }),
  deleteMessage: (id, msgId) =>
    request(`/api/groups/${id}/messages/${msgId}`, { method: "DELETE" }),

  // Profile
  profile: () => request("/api/profile"),
  updateProfile: (payload) => request("/api/profile", { method: "PATCH", body: payload }),

  // Misc
  health: () => request("/api/health"),
};
