import { api } from "/js/api.js";
import { animateNumber, escapeHtml, renderGauge, requireAuth, setNavActive, toast, withButtonLoading } from "/js/ui.js";

setNavActive();
let user = await requireAuth(api);

const headEl = document.querySelector("[data-profile-head]");
const gaugeEl = document.querySelector("[data-gauge]");
const statsEl = document.querySelector("[data-stats]");
const interestsEl = document.querySelector("[data-interests]");
const interestForm = document.querySelector("[data-interest-form]");
const nameForm = document.querySelector("[data-name-form]");
const orgForm = document.querySelector("[data-org-form]");
const orgConfirmForm = document.querySelector("[data-org-confirm-form]");
const orgPanel = document.querySelector("[data-org-panel]");
const orgStatus = document.querySelector("[data-org-status]");

function initials(name) {
  return (name || "?").split(/\s+/).filter(Boolean).map((p) => p[0].toUpperCase()).slice(0, 2).join("");
}

function renderHead() {
  headEl.innerHTML = `
    <div class="avatar" aria-hidden="true">${escapeHtml(initials(user.full_name))}</div>
    <div>
      <div class="profile-name">${escapeHtml(user.full_name)}</div>
      <div class="profile-handle mono">@${escapeHtml(user.username)} · ${escapeHtml(user.email)}</div>
    </div>
  `;
}

function renderStats() {
  const verified = user.is_face_verified ? "Face verified" : "Face not verified";
  const orgLabel = user.verified_domain ? user.verified_domain : "—";
  statsEl.innerHTML = `
    <div class="stat">
      <div class="stat-label">Trust score</div>
      <div class="stat-value" data-trust>0.00</div>
      <div class="stat-hint">Range 0.00–5.00</div>
    </div>
    <div class="stat">
      <div class="stat-label">Face verification</div>
      <div class="stat-value" style="font-size:1.1rem;">${verified}</div>
      <div class="stat-hint">${user.is_face_verified ? "Anti-spoofing passed." : "Run verify to unlock proximity groups."}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Organization</div>
      <div class="stat-value mono" style="font-size:1.1rem;">${escapeHtml(orgLabel)}</div>
      <div class="stat-hint">${user.verified_domain ? "Bypasses proximity for matching groups." : "Verify your org email to unlock global trust."}</div>
    </div>
  `;
  animateNumber(statsEl.querySelector("[data-trust]"), user.trust_score, { decimals: 2 });
}

function renderInterests() {
  if (!user.interests.length) {
    interestsEl.innerHTML = `<span class="dim">No interests yet — add some below.</span>`;
    return;
  }
  interestsEl.innerHTML = user.interests.map((it) => `
    <span class="chip">
      ${escapeHtml(it)}
      <button class="chip-remove" data-remove="${escapeHtml(it)}" aria-label="Remove ${escapeHtml(it)}">×</button>
    </span>
  `).join("");
  interestsEl.querySelectorAll("[data-remove]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const value = btn.dataset.remove;
      const updated = (user.interests || []).filter((x) => x !== value);
      await updateProfile({ interests: updated });
    });
  });
}

async function updateProfile(payload) {
  try {
    user = await api.updateProfile(payload);
    renderAll();
    toast("Saved.", { kind: "ok" });
  } catch (e) {
    toast(e.message, { kind: "err" });
  }
}

function renderAll() {
  renderHead();
  renderGauge(gaugeEl, user.trust_score);
  renderStats();
  renderInterests();
  renderOrgStatus();
}

function renderOrgStatus() {
  if (user.verified_domain) {
    orgStatus.innerHTML = `
      <div class="alert alert-ok">
        Verified for <strong>${escapeHtml(user.verified_domain)}</strong>. You can join groups requiring this domain.
      </div>
    `;
  } else {
    orgStatus.innerHTML = `
      <div class="alert alert-info">
        Verify with an organization email to unlock domain-restricted groups (eg, alumni networks).
      </div>
    `;
  }
}

interestForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const value = interestForm.interest.value.trim();
  if (!value) return;
  const list = [...(user.interests || []), value].slice(0, 20);
  interestForm.interest.value = "";
  await updateProfile({ interests: list });
});

nameForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const v = nameForm.full_name.value.trim();
  if (!v) return;
  await updateProfile({ full_name: v });
});

orgForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const submit = orgForm.querySelector("button[type=submit]");
  const restore = withButtonLoading(submit, "Sending...");
  try {
    const res = await api.requestOrgOtp({
      email: orgForm.email.value.trim(),
      domain: orgForm.domain.value.trim().toLowerCase(),
    });
    orgConfirmForm.email.value = orgForm.email.value.trim();
    orgConfirmForm.classList.remove("hidden");
    toast(res.message + " Check the server console for the code.", { kind: "info", duration: 8000 });
  } catch (e) {
    toast(e.message, { kind: "err" });
  } finally {
    restore();
  }
});

orgConfirmForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const submit = orgConfirmForm.querySelector("button[type=submit]");
  const restore = withButtonLoading(submit, "Verifying...");
  try {
    const res = await api.confirmOrgOtp({
      email: orgConfirmForm.email.value.trim(),
      code: orgConfirmForm.code.value.trim(),
    });
    toast(res.message, { kind: "ok" });
    orgConfirmForm.classList.add("hidden");
    user = await api.profile();
    renderAll();
  } catch (e) {
    toast(e.message, { kind: "err" });
  } finally {
    restore();
  }
});

// (Logout button is wired centrally in ui.js setNavActive.)

nameForm.full_name.value = user.full_name;
renderAll();

const greet = document.querySelector("[data-greet]");
if (greet) greet.textContent = (user.full_name || user.username).split(" ")[0];
