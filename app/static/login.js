"use strict";
const form = document.querySelector("#login-form");
const error = document.querySelector("#login-error");
document.querySelector("#show-password").addEventListener("click", (event) => {
  const field = document.querySelector("#password");
  const visible = field.type === "password";
  field.type = visible ? "text" : "password";
  event.currentTarget.setAttribute("aria-label", visible ? "Hide password" : "Show password");
  event.currentTarget.setAttribute("aria-pressed", String(visible));
});
if (new URLSearchParams(location.search).has("expired")) {
  error.textContent = "Your session has expired. Please sign in again.";
  error.hidden = false;
}
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector('[type="submit"]');
  button.disabled = true;
  button.querySelector("span").textContent = "Signing in…";
  error.hidden = true;
  try {
    const response = await fetch("/api/auth/login", {
      method: "POST", headers: {"Content-Type": "application/json", "X-Requested-With": "telemetry-ui"},
      body: JSON.stringify({username: form.username.value.trim(), password: form.password.value}),
    });
    if (!response.ok) throw new Error(response.status === 401 ? "That username or password isn't correct. Please try again." : "Unable to sign in right now. Please try again.");
    location.assign("/data");
  } catch (err) {
    error.textContent = err instanceof TypeError ? "Can't reach the server. Check your connection and try again." : err.message;
    error.hidden = false;
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "Sign in to workspace";
  }
});
