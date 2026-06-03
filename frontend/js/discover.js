import { api } from "/js/api.js";
import { escapeHtml, requireAuth, setNavActive, toast, withButtonLoading } from "/js/ui.js";

setNavActive();
const user = await requireAuth(api);
// On the 401 path requireAuth navigates to /login and returns null; stop here
// rather than dereferencing a null user below.
if (!user) {
  throw new Error("not authenticated — redirecting to login");
}

const grid = document.querySelector("[data-groups]");
const statusEl = document.querySelector("[data-status]");
const coordsEl = document.querySelector("[data-coords]");
const useLocBtn = document.querySelector("[data-use-loc]");
const manualBtn = document.querySelector("[data-manual]");
const manualForm = document.querySelector("[data-manual-form]");
const refreshBtn = document.querySelector("[data-refresh]");

let currentLat = user.current_lat;
let currentLon = user.current_lon;

if (currentLat !== null && currentLon !== null) {
  showCoords(currentLat, currentLon);
  loadGroups();
} else {
  showStatus("Share your location to discover nearby groups.");
}

useLocBtn.addEventListener("click", async () => {
  if (!("geolocation" in navigator)) {
    toast("Geolocation is unsupported in this browser.", { kind: "err" });
    return;
  }
  const restore = withButtonLoading(useLocBtn, "Locating...");
  try {
    const pos = await new Promise((resolve, reject) => {
      navigator.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: true,
        timeout: 8000,
      });
    });
    currentLat = pos.coords.latitude;
    currentLon = pos.coords.longitude;
    showCoords(currentLat, currentLon);
    await api.updateProfile({ current_lat: currentLat, current_lon: currentLon });
    await loadGroups();
  } catch (e) {
    toast("Could not get location. Enter manually or check permissions.", { kind: "warn" });
  } finally {
    restore();
  }
});

manualBtn.addEventListener("click", () => {
  manualForm.classList.toggle("hidden");
});

manualForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const lat = parseFloat(manualForm.lat.value);
  const lon = parseFloat(manualForm.lon.value);
  if (Number.isNaN(lat) || Number.isNaN(lon)) {
    toast("Enter valid lat/lon.", { kind: "err" });
    return;
  }
  currentLat = lat; currentLon = lon;
  showCoords(lat, lon);
  manualForm.classList.add("hidden");
  await api.updateProfile({ current_lat: lat, current_lon: lon });
  await loadGroups();
});

refreshBtn.addEventListener("click", loadGroups);

function showStatus(msg) {
  statusEl.textContent = msg;
  statusEl.classList.remove("hidden");
}

function hideStatus() { statusEl.classList.add("hidden"); }

function showCoords(lat, lon) {
  coordsEl.textContent = `${lat.toFixed(4)}°, ${lon.toFixed(4)}°`;
}

async function loadGroups() {
  if (currentLat === null || currentLat === undefined) return;
  grid.innerHTML = skeletonCards(3);
  hideStatus();
  try {
    const groups = await api.discover(currentLat, currentLon);
    renderGroups(groups);
  } catch (e) {
    grid.innerHTML = "";
    showStatus(e.message);
    toast(e.message, { kind: "err" });
  }
}

function skeletonCards(n) {
  return Array.from({ length: n }, () => `
    <div class="group-card">
      <div class="skeleton" style="height:18px;width:60%;"></div>
      <div class="skeleton" style="height:14px;width:80%;"></div>
      <div class="skeleton" style="height:14px;width:40%;"></div>
    </div>
  `).join("");
}

function renderGroups(groups) {
  if (!groups.length) {
    grid.innerHTML = "";
    grid.insertAdjacentHTML("afterend", `
      <div class="empty-state" data-empty>
        <h3>No groups in range</h3>
        <p>Try a different location, or verify an organization to unlock domain-based groups.</p>
      </div>
    `);
    return;
  }
  // Clean any stale empty-state
  const existingEmpty = document.querySelector("[data-empty]");
  if (existingEmpty) existingEmpty.remove();

  grid.innerHTML = groups.map(renderCard).join("");

  grid.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const action = btn.dataset.action;
      const id = Number(btn.dataset.id);
      const restore = withButtonLoading(btn, action === "join" ? "Joining..." : "Leaving...");
      try {
        if (action === "join") {
          const r = await api.joinGroup(id);
          toast(r.message, { kind: "ok" });
        } else {
          const r = await api.leaveGroup(id);
          toast(r.message, { kind: "ok" });
        }
        await loadGroups();
      } catch (e) {
        toast(e.message, { kind: "err" });
        restore();
      }
    });
  });
}

function renderCard(g) {
  const isDomain = g.domain_match;
  const distanceLabel = `${g.distance_km.toFixed(2)} km`;
  const memberLabel = g.member_count === 1 ? "1 member" : `${g.member_count} members`;
  const action = g.is_member
    ? `<button class="btn btn-ghost btn-sm" data-action="leave" data-id="${g.id}">Leave</button>`
    : `<button class="btn btn-primary btn-sm" data-action="join" data-id="${g.id}">Join</button>`;
  // For members, the primary action is opening the chat; Leave is secondary.
  const chatLink = g.is_member
    ? `<a class="btn btn-primary btn-sm" href="/chat?group=${g.id}">Open chat</a>`
    : "";
  // One clear primary read (the name). Distance + a single status badge only;
  // niche becomes a small kicker above the title, not a competing badge.
  const statusBadge = g.is_member
    ? `<span class="badge badge-ok badge-dot">Member</span>`
    : isDomain
      ? `<span class="badge badge-violet">Domain match</span>`
      : "";
  const badges = [
    `<span class="badge badge-cyan">${distanceLabel}</span>`,
    statusBadge,
  ].filter(Boolean).join("");

  return `
    <article class="group-card" data-domain="${isDomain}" data-joined="${g.is_member}">
      <div class="group-head">
        <div>
          <span class="group-kicker">${escapeHtml(g.niche_type)}</span>
          <div class="group-name">${escapeHtml(g.name)}</div>
          <div class="group-meta" style="margin-top:6px;">${badges}</div>
        </div>
      </div>
      <p class="group-desc">${escapeHtml(g.description || "")}</p>
      <div class="group-foot">
        <span class="mono dim" style="font-size:0.85rem;">${memberLabel} · radius ${g.radius_km} km</span>
        <span class="group-actions">${chatLink}${action}</span>
      </div>
    </article>
  `;
}

// Live the nav greeting
const greet = document.querySelector("[data-greet]");
if (greet) greet.textContent = (user.full_name || user.username).split(" ")[0];
