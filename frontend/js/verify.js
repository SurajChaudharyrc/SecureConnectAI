import { api } from "/js/api.js";
import { renderGauge, requireAuth, setNavActive, toast, withButtonLoading } from "/js/ui.js";

setNavActive();
await requireAuth(api);

const dz = document.querySelector("[data-dz-id]");
const dzInput = document.querySelector("[data-input-id]");
const dzThumb = document.querySelector("[data-dz-id-thumb]");
const selfieVideo = document.querySelector("[data-video]");
const selfieCanvas = document.querySelector("[data-canvas]");
const captureBtn = document.querySelector("[data-capture]");
const startCamBtn = document.querySelector("[data-start-cam]");
const stopCamBtn = document.querySelector("[data-stop-cam]");
const selfieUpload = document.querySelector("[data-input-selfie]");
const selfieFileBtn = document.querySelector("[data-pick-selfie]");
const selfiePreview = document.querySelector("[data-selfie-thumb]");
const submitBtn = document.querySelector("[data-submit]");
const resultPane = document.querySelector("[data-result]");
const stepEls = document.querySelectorAll("[data-step]");

let idFile = null;
let selfieBlob = null;
let camStream = null;

function setStep(active) {
  stepEls.forEach((el) => {
    const n = Number(el.dataset.step);
    el.classList.toggle("is-active", n === active);
    el.classList.toggle("is-done", n < active);
  });
}

function reflectReadiness() {
  submitBtn.disabled = !(idFile && selfieBlob);
}

// ID drop / pick
function acceptIdFile(file) {
  if (!file) return;
  if (!/^image\/(jpeg|png|webp)$/.test(file.type)) {
    toast("Use a JPG, PNG, or WEBP image.", { kind: "err" });
    return;
  }
  if (file.size > 8 * 1024 * 1024) {
    toast("File is over 8 MB.", { kind: "err" });
    return;
  }
  idFile = file;
  const url = URL.createObjectURL(file);
  dzThumb.src = url;
  dzThumb.classList.remove("hidden");
  dz.classList.add("has-file");
  const meta = document.querySelector("[data-id-meta]");
  if (meta) meta.textContent = `${file.name} · ${(file.size / 1024).toFixed(0)} KB`;
  setStep(2);
  reflectReadiness();
}

dz.addEventListener("click", () => dzInput.click());
dz.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); dzInput.click(); } });
dz.addEventListener("dragover", (ev) => { ev.preventDefault(); dz.classList.add("is-drag"); });
dz.addEventListener("dragleave", () => dz.classList.remove("is-drag"));
dz.addEventListener("drop", (ev) => {
  ev.preventDefault();
  dz.classList.remove("is-drag");
  if (ev.dataTransfer.files.length) acceptIdFile(ev.dataTransfer.files[0]);
});
dzInput.addEventListener("change", () => {
  if (dzInput.files.length) acceptIdFile(dzInput.files[0]);
});

// Webcam selfie
async function startCam() {
  if (camStream) return;
  try {
    camStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 1024 }, height: { ideal: 768 } },
      audio: false,
    });
    selfieVideo.srcObject = camStream;
    selfieVideo.play();
    startCamBtn.classList.add("hidden");
    stopCamBtn.classList.remove("hidden");
    captureBtn.classList.remove("hidden");
  } catch (e) {
    toast("Camera unavailable. Use upload instead.", { kind: "warn" });
  }
}

function stopCam() {
  if (camStream) {
    camStream.getTracks().forEach((t) => t.stop());
    camStream = null;
  }
  startCamBtn.classList.remove("hidden");
  stopCamBtn.classList.add("hidden");
  captureBtn.classList.add("hidden");
}

function captureSelfieFromCam() {
  if (!camStream) return;
  const v = selfieVideo;
  const c = selfieCanvas;
  const w = v.videoWidth, h = v.videoHeight;
  c.width = w; c.height = h;
  c.getContext("2d").drawImage(v, 0, 0, w, h);
  c.toBlob((blob) => {
    selfieBlob = blob;
    selfiePreview.src = URL.createObjectURL(blob);
    selfiePreview.classList.remove("hidden");
    setStep(3);
    reflectReadiness();
    stopCam();
    toast("Captured. You can retake before submitting.", { kind: "ok" });
  }, "image/jpeg", 0.92);
}

function pickSelfieFile() {
  selfieUpload.click();
}

selfieUpload.addEventListener("change", () => {
  if (!selfieUpload.files.length) return;
  const file = selfieUpload.files[0];
  if (!/^image\/(jpeg|png|webp)$/.test(file.type)) {
    toast("Use a JPG, PNG, or WEBP image.", { kind: "err" });
    return;
  }
  selfieBlob = file;
  selfiePreview.src = URL.createObjectURL(file);
  selfiePreview.classList.remove("hidden");
  setStep(3);
  reflectReadiness();
});

startCamBtn.addEventListener("click", startCam);
stopCamBtn.addEventListener("click", stopCam);
captureBtn.addEventListener("click", captureSelfieFromCam);
selfieFileBtn.addEventListener("click", pickSelfieFile);

// Submit
async function submit() {
  if (!idFile || !selfieBlob) return;
  const restore = withButtonLoading(submitBtn, "Verifying...");
  resultPane.innerHTML = "";
  try {
    const form = new FormData();
    form.append("id_image", idFile);
    form.append("selfie", selfieBlob, "selfie.jpg");
    const result = await api.verifyFace(form);
    renderResult(result);
    if (result.verified) toast("Verified.", { kind: "ok" });
    else toast("Could not verify. Try better lighting.", { kind: "warn" });
  } catch (e) {
    renderError(e.message);
    toast(e.message, { kind: "err" });
  } finally {
    restore();
  }
}

submitBtn.addEventListener("click", submit);

function renderResult(result) {
  const kind = result.verified ? "ok" : "err";
  const icon = result.verified
    ? `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>`
    : `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><circle cx="12" cy="16" r="0.5" fill="currentColor" /></svg>`;
  const confidence = result.confidence !== null ? `<div class="muted">Confidence ${result.confidence.toFixed(1)}%</div>` : "";

  resultPane.innerHTML = `
    <div class="result result-${kind}">
      <div class="result-icon" style="color: ${result.verified ? "var(--ok)" : "var(--err)"}">${icon}</div>
      <div class="grow">
        <div style="font-weight:700; font-size:1.05rem; margin-bottom:4px;">
          ${result.verified ? "Identity verified" : "Verification failed"}
        </div>
        <div class="muted">${result.detail || (result.verified ? "Your trust score has been increased." : "")}</div>
        ${confidence}
      </div>
      <div class="gauge" data-gauge></div>
    </div>
  `;
  renderGauge(resultPane.querySelector("[data-gauge]"), result.trust_score);
}

function renderError(msg) {
  resultPane.innerHTML = `
    <div class="result result-err">
      <div class="result-icon" style="color: var(--err)">!</div>
      <div class="grow"><div style="font-weight:700; margin-bottom:4px;">Something went wrong</div><div class="muted">${msg}</div></div>
    </div>
  `;
}

setStep(1);
reflectReadiness();
