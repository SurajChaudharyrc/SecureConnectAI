// Shared UI primitives: toasts, nav active state, button loading, gauge animation.

let toastStack = null;
function ensureToastStack() {
  if (toastStack) return toastStack;
  toastStack = document.createElement("div");
  toastStack.className = "toast-stack";
  toastStack.setAttribute("aria-live", "polite");
  toastStack.setAttribute("aria-atomic", "false");
  document.body.appendChild(toastStack);
  return toastStack;
}

export function toast(message, { kind = "ok", duration = 4200 } = {}) {
  const stack = ensureToastStack();
  const el = document.createElement("div");
  el.className = `toast toast-${kind}`;
  el.setAttribute("role", "status");
  el.textContent = message;
  stack.appendChild(el);
  setTimeout(() => {
    el.style.transition = "opacity 220ms, transform 220ms";
    el.style.opacity = "0";
    el.style.transform = "translateY(6px)";
    setTimeout(() => el.remove(), 260);
  }, duration);
}

export function setNavActive() {
  const path = window.location.pathname.replace(/\/$/, "") || "/";
  document.querySelectorAll(".nav-link").forEach((link) => {
    const href = link.getAttribute("href");
    if (!href) return;
    const normalized = href.replace(/\/$/, "") || "/";
    if (normalized === path) {
      link.classList.add("active");
      link.setAttribute("aria-current", "page");
    }
  });
  wireLogout();
}

// Wire the shared "Sign out" button. Every page calls setNavActive(), so this
// guarantees logout works app-wide (previously only auth.js/profile.js wired it,
// leaving Discover/Chat/Verify with a dead button). Self-contained (no api
// import) and guarded so it binds at most once per button.
export function wireLogout() {
  const btn = document.querySelector("[data-logout]");
  if (!btn || btn.dataset.wired) return;
  btn.dataset.wired = "1";
  btn.addEventListener("click", async () => {
    const m = document.cookie.match(/(?:^|;\s*)sc_csrf=([^;]+)/);
    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: m ? { "X-CSRF-Token": decodeURIComponent(m[1]) } : {},
      });
    } catch (_) {
      /* ignore network/CSRF errors — still redirect to a clean state */
    }
    window.location.href = "/login";
  });
}

export function withButtonLoading(button, label) {
  if (!button) return () => {};
  const original = button.innerHTML;
  const wasDisabled = button.disabled;
  button.disabled = true;
  button.innerHTML = `<span class="spinner" aria-hidden="true"></span><span>${label || "Working..."}</span>`;
  return () => {
    button.disabled = wasDisabled;
    button.innerHTML = original;
  };
}

export function animateNumber(el, to, { duration = 800, decimals = 2 } = {}) {
  if (!el) return;
  const start = parseFloat(el.dataset.value || "0") || 0;
  const startTime = performance.now();
  function tick(now) {
    const t = Math.min(1, (now - startTime) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    const v = start + (to - start) * eased;
    el.textContent = v.toFixed(decimals);
    if (t < 1) requestAnimationFrame(tick);
    else el.dataset.value = String(to);
  }
  requestAnimationFrame(tick);
}

export function renderGauge(container, score, { max = 5 } = {}) {
  if (!container) return;
  const ratio = Math.max(0, Math.min(1, score / max));
  const radius = 70;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - ratio);
  container.innerHTML = `
    <svg width="160" height="160" viewBox="0 0 160 160" aria-hidden="true">
      <circle class="gauge-bg" cx="80" cy="80" r="${radius}" />
      <circle class="gauge-fg" cx="80" cy="80" r="${radius}"
              stroke="#5cf2e0"
              stroke-dasharray="${circumference}"
              stroke-dashoffset="${circumference}" />
    </svg>
    <div class="gauge-value">${score.toFixed(2)}</div>
    <div class="gauge-label">Trust</div>
  `;
  requestAnimationFrame(() => {
    const fg = container.querySelector(".gauge-fg");
    if (fg) fg.style.strokeDashoffset = String(offset);
  });
}

export function navigateGuarded(path) {
  window.location.href = path;
}

export function initials(name) {
  return (name || "?")
    .split(/\s+/)
    .filter(Boolean)
    .map((p) => p[0].toUpperCase())
    .slice(0, 2)
    .join("");
}

// Deterministic hue (0-359) from a string, for stable per-user avatar colors.
export function avatarHue(key) {
  const s = String(key || "");
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
  return h;
}

export function escapeHtml(s) {
  if (s === undefined || s === null) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export async function requireAuth(api) {
  try {
    return await api.me();
  } catch (e) {
    if (e.status === 401) {
      const here = encodeURIComponent(window.location.pathname);
      window.location.href = `/login?next=${here}`;
      return null;
    }
    throw e;
  }
}
