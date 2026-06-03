import { api } from "/js/api.js";
import { setNavActive, toast, withButtonLoading } from "/js/ui.js";

setNavActive();

const params = new URLSearchParams(window.location.search);
const nextUrl = params.get("next") || "/discover";

function setError(form, msg) {
  const slot = form.querySelector("[data-error]");
  if (slot) {
    slot.textContent = msg || "";
    slot.classList.toggle("hidden", !msg);
  }
}

async function handleLogin(form) {
  const username = form.username.value.trim();
  const password = form.password.value;
  const submit = form.querySelector("button[type=submit]");
  const restore = withButtonLoading(submit, "Signing in...");
  setError(form, "");
  try {
    await api.login({ username, password });
    toast("Welcome back.", { kind: "ok" });
    setTimeout(() => { window.location.href = nextUrl; }, 380);
  } catch (e) {
    setError(form, e.message);
    restore();
  }
}

async function handleRegister(form) {
  const payload = {
    username: form.username.value.trim(),
    email: form.email.value.trim(),
    password: form.password.value,
    full_name: form.full_name.value.trim(),
  };
  const submit = form.querySelector("button[type=submit]");
  const restore = withButtonLoading(submit, "Creating account...");
  setError(form, "");
  try {
    await api.register(payload);
    toast("Account created. Let's verify you.", { kind: "ok" });
    setTimeout(() => { window.location.href = "/verify"; }, 380);
  } catch (e) {
    if (e.data && Array.isArray(e.data.errors) && e.data.errors.length) {
      const first = e.data.errors[0];
      setError(form, `${first.field}: ${first.issue}`);
    } else {
      setError(form, e.message);
    }
    restore();
  }
}

const loginForm = document.querySelector("[data-form=login]");
if (loginForm) {
  loginForm.addEventListener("submit", (ev) => {
    ev.preventDefault();
    handleLogin(loginForm);
  });
}

const registerForm = document.querySelector("[data-form=register]");
if (registerForm) {
  registerForm.addEventListener("submit", (ev) => {
    ev.preventDefault();
    handleRegister(registerForm);
  });
}

// (Logout button is wired centrally in ui.js setNavActive.)

// Hide auth-only nav links when logged out, and vice versa.
api.me().then((user) => {
  document.documentElement.dataset.authed = "true";
  const greet = document.querySelector("[data-greet]");
  if (greet) greet.textContent = user.full_name.split(" ")[0] || user.username;
}).catch(() => {
  document.documentElement.dataset.authed = "false";
});
