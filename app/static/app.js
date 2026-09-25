"use strict";
const main = document.querySelector("#main");
const dialog = document.querySelector("#form-dialog");
const route = location.pathname.slice(1) || "data";
const pageNames = {data: "Stored data", devices: "Devices", parameters: "Allowed parameters", export: "CSV export"};
const state = {user: null, summary: null, devices: [], parameters: [], cursor: null, history: [], nextCursor: null};
const icon = (name, css = "") => `<svg class="${css}" aria-hidden="true"><use href="/static/icons.svg#${name}"/></svg>`;
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
const number = (value) => Number(value).toLocaleString("en-US");
const utcDate = (value, time = true) => value ? new Date(value).toLocaleString("en-GB", {timeZone: "UTC", day: "2-digit", month: "short", year: "numeric", ...(time ? {hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false} : {})}) : "—";
let toastTimer;

async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {"Content-Type": "application/json", "X-Requested-With": "telemetry-ui", ...options.headers}});
  if (response.status === 401) { location.replace("/login?expired=1"); throw new Error("Your session has expired."); }
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    const detail = typeof error.detail === "string" ? error.detail : Array.isArray(error.detail) ? error.detail.map((item) => item.msg.replace(/^Value error, /, "")).join(". ") : "The request couldn't be completed. Please try again.";
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}
function toast(message, error = false) {
  const element = document.querySelector("#toast");
  clearTimeout(toastTimer);
  element.textContent = message;
  element.className = `toast${error ? " error" : ""}`;
  element.hidden = false;
  toastTimer = setTimeout(() => { element.hidden = true; }, 4500);
}
function heading(kicker, title, description, actions = "") {
  return `<div class="page-heading"><div><span class="eyebrow">${kicker}</span><h1>${title}</h1><p>${description}</p></div>${actions ? `<div class="heading-actions">${actions}</div>` : ""}</div>`;
}
function stat(label, value, foot, symbol, color = "", suffix = "") {
  return `<div class="stat-card"><div class="stat-icon ${color}">${icon(symbol)}</div><span class="stat-label">${label}</span><div class="stat-value">${value}${suffix ? `<span>${suffix}</span>` : ""}</div><p class="stat-foot">${foot}</p></div>`;
}
function stats() {
  const s = state.summary;
  return `<section class="stats-grid" aria-label="Workspace overview">${stat("Registered devices", number(s.devices), `<span class="green">${s.enabled_devices} enabled</span> to receive data`, "chip", "", `/ ${state.user.max_devices}`)}${stat("Allowed parameters", number(s.enabled_parameters), "Enabled in your global whitelist", "sliders", "blue")}${stat("Stored readings", number(s.records), "Approved values, safely collected", "database", "purple")}</section>`;
}
function empty(symbol, title, description, action = "") {
  return `<div class="empty-state"><div class="empty-icon">${icon(symbol)}</div><h3>${title}</h3><p>${description}</p>${action}</div>`;
}
function panelTop(symbol, title, description, meta = "") {
  return `<div class="panel-top"><div class="panel-title">${icon(symbol)}<div><h2>${title}</h2>${description ? `<p>${description}</p>` : ""}</div></div>${meta ? `<span class="meta">${meta}</span>` : ""}</div>`;
}
function status(enabled) {
  return `<span class="badge ${enabled ? "badge-green" : "badge-gray"}"><span class="small-dot"></span>${enabled ? "Enabled" : "Disabled"}</span>`;
}
function info(text) { return `<div class="info-strip">${icon("info")}<p>${text}</p></div>`; }
function showPageError(error) {
  main.innerHTML = `${heading("WORKSPACE", pageNames[route], "Let's get you back to your data.")}<section class="panel">${empty("refresh", "We couldn't load this page", esc(error.message), '<button class="button button-dark" id="retry">Try again</button>')}</section>`;
  document.querySelector("#retry").onclick = loadPage;
}
async function loadPage() {
  try {
    state.summary = await api("/api/summary");
    document.querySelector("#nav-device-count").textContent = state.summary.devices;
    if (route === "data") await renderData();
    else if (route === "devices") await renderDevices();
    else if (route === "parameters") await renderParameters();
    else renderExport();
  } catch (error) { showPageError(error); }
}

async function renderData() {
  const params = new URLSearchParams({limit: "13"});
  if (state.cursor) params.set("before_id", state.cursor);
  const result = await api(`/api/telemetry/records?${params}`);
  const records = result.records.slice(0, 12);
  state.nextCursor = result.next_cursor;
  const columns = result.columns.filter((c) => c !== "systemTemp");
  const rule = result.health_rule;
  const actions = `<button class="button button-outline" id="refresh">${icon("refresh")}Refresh</button><a class="button button-dark" href="/export">${icon("download")}Export data</a>`;
  function healthBadge(health) {
    if (health === "ok") return `<span class="badge badge-green"><span class="small-dot"></span>OK</span>`;
    if (health === "not_ok") return `<span class="badge badge-red"><span class="small-dot"></span>Not OK</span>`;
    return `<span class="badge badge-gray"><span class="small-dot"></span>Unknown</span>`;
  }
  function healthTitle(rec) {
    const v = rec.values["systemTemp"];
    if (v === undefined) return "No systemTemp in this transmission";
    const parts = [`systemTemp\u202F=\u202F${v}`];
    if (rule.unit) parts.push(rule.unit);
    return parts.join("\u00a0");
  }
  main.innerHTML = heading("YOUR FIELD, IN FOCUS", "Stored data", "A clear view of the readings collected from your sensor devices.", actions) + stats() +
    `<section class="panel">${panelTop("database", "Transmission log", "One row per accepted MQTT message · Newest first", `${icon("clock")} All times in UTC`)}${records.length ?
      `<div class="table-scroll" tabindex="0" aria-label="Telemetry transmission log">
        <table class="matrix-table">
          <thead><tr>
            <th>Registry ID</th>
            <th>Device</th>
            <th>Timestamp · UTC</th>
            ${columns.map((c) => `<th><span class="parameter-pill ${parameterColor(c)}">${esc(c)}</span></th>`).join("")}
            <th>Device Health</th>
          </tr></thead>
          <tbody>${records.map((rec) => `<tr>
            <td class="record-id">#${String(rec.registry_id).padStart(6, "0")}</td>
            <td><div class="device-cell"><span class="device-cell-icon">${icon("chip")}</span><div><strong>${esc(rec.device_name || rec.device_id)}</strong><small class="muted">${esc(rec.device_id)}</small></div></div></td>
            <td class="date-cell">${utcDate(rec.timestamp)}</td>
            ${columns.map((c) => `<td class="value-cell">${rec.values[c] !== undefined ? esc(rec.values[c]) : "<span class=\"muted\">—</span>"}</td>`).join("")}
            <td><div style="display: flex; align-items: center; gap: 8px;" title="${esc(healthTitle(rec))}">${healthBadge(rec.health)}${rec.values["systemTemp"] !== undefined ? `<span class="muted" style="font-size: 0.9em;">${esc(rec.values["systemTemp"])}${rule.unit ? `\u00a0${esc(rule.unit)}` : ""}</span>` : ""}</div></td>
          </tr>`).join("")}</tbody>
        </table>
      </div>` : empty("database", "Your first reading starts here", "Register a device and enable its parameters. Approved readings will appear here as they arrive.", '<a class="button button-outline" href="/devices">Manage devices</a>')}
      <div class="table-bottom"><span>${records.length ? `${number(state.history.length * 12 + 1)}\u2013${number(state.history.length * 12 + records.length)} shown` : "No transmissions yet"}</span><div class="pagination"><button id="previous" class="button button-outline" ${state.history.length ? "" : "disabled"}>${icon("arrow-left")}Previous</button><button id="next" class="button button-outline" ${state.nextCursor ? "" : "disabled"}>Next${icon("arrow-right")}</button></div></div></section>` +
    info(`<strong>Quality in, clarity out.</strong> Each row is one MQTT transmission. Parameter columns show <span class="muted">\u2014</span> when a value was not included. Device Health is derived from <code>systemTemp</code> and excluded from CSV exports. Refresh to see new readings.`);
  document.querySelector("#refresh").onclick = () => { state.cursor = null; state.history = []; loadPage(); };
  document.querySelector("#previous").onclick = () => { state.cursor = state.history.pop(); loadPage(); };
  document.querySelector("#next").onclick = () => { state.history.push(state.cursor); state.cursor = state.nextCursor; loadPage(); };
}
function parameterColor(name) {
  let hash = 0;
  for (const char of name) hash += char.charCodeAt(0);
  return ["", "blue", "purple"][hash % 3];
}
async function renderDevices() {
  state.devices = await api("/api/devices");
  const atCapacity = state.devices.length >= state.user.max_devices;
  main.innerHTML = heading("CONNECTED TO THE FIELD", "Your devices", "Manage the sensor devices that send data to your workspace.", `<button class="button button-green" id="add-device" ${atCapacity ? "disabled" : ""}>${icon("plus")}Add device</button>`) + stats() +
    `<section class="panel">${panelTop("chip", "Registered devices", "Enable a device to accept its approved readings", `${state.devices.length} of ${state.user.max_devices} devices`)}${state.devices.length ?
      `<div class="table-scroll" tabindex="0" aria-label="Devices table"><table><thead><tr><th>Device</th><th>Device ID</th><th>MQTT Password</th><th>Status</th><th>Registered · UTC</th><th>Actions</th></tr></thead><tbody>${state.devices.map((device) => `<tr><td><div class="device-cell"><span class="device-cell-icon">${icon("chip")}</span><strong>${esc(device.name)}</strong></div></td><td class="mono">${esc(device.device_id)}</td><td class="mono" style="user-select: all;">${esc(device.mqtt_password || "")}</td><td><div class="status-control"><button class="toggle" role="switch" aria-checked="${device.enabled}" aria-label="Enable ${esc(device.name)}" data-toggle-device="${esc(device.device_id)}"></button>${status(device.enabled)}</div></td><td class="date-cell">${utcDate(device.created_at, false)}</td><td><div class="row-actions"><button class="button button-ghost" data-edit-device="${esc(device.device_id)}">${icon("edit")}Edit</button><button class="icon-button danger" title="Clear telemetry data" aria-label="Clear data for ${esc(device.name)}" data-clear-device="${esc(device.device_id)}">${icon("database")}</button><button class="icon-button danger" title="Delete device and data" aria-label="Delete ${esc(device.name)}" data-delete-device="${esc(device.device_id)}">${icon("trash")}</button></div></td></tr>`).join("")}</tbody></table></div>` : empty("chip", "Meet your next connection", "Add your first sensor device to start collecting field data.", '<button class="button button-green" id="empty-add">Add your first device</button>')}
      <div class="table-bottom"><span>${atCapacity ? "All device slots are in use" : `${state.user.max_devices - state.devices.length} device slots available`}</span><span>Up to ${state.user.max_devices} devices per workspace</span></div></section>` +
    info("<strong>You're in control.</strong> Disabling a device stops new readings from being stored. Its previously collected data stays available. Use the trash icon to permanently delete all telemetry data for a device.");
  document.querySelector("#add-device").onclick = () => deviceForm();
  document.querySelector("#empty-add")?.addEventListener("click", () => deviceForm());
  main.querySelectorAll("[data-edit-device]").forEach((button) => button.onclick = () => deviceForm(state.devices.find((d) => d.device_id === button.dataset.editDevice)));
  main.querySelectorAll("[data-toggle-device]").forEach((button) => button.onclick = async () => {
    const device = state.devices.find((d) => d.device_id === button.dataset.toggleDevice);
    button.disabled = true;
    try { await api(`/api/devices/${encodeURIComponent(device.device_id)}`, {method: "PUT", body: JSON.stringify({name: device.name, enabled: !device.enabled})}); await loadPage(); toast(`Device ${device.enabled ? "disabled" : "enabled"}.`); }
    catch (error) { toast(error.message, true); button.disabled = false; }
  });
  main.querySelectorAll("[data-clear-device]").forEach((button) => button.onclick = () => clearDeviceData(state.devices.find((d) => d.device_id === button.dataset.clearDevice)));
  main.querySelectorAll("[data-delete-device]").forEach((button) => button.onclick = () => deleteDevice(state.devices.find((d) => d.device_id === button.dataset.deleteDevice)));
}
async function renderParameters() {
  state.parameters = await api("/api/parameters");
  main.innerHTML = heading("KEEP WHAT MATTERS", "Allowed parameters", "Choose which sensor values are approved for storage across all devices.", `<button class="button button-green" id="add-parameter">${icon("plus")}Add parameter</button>`) + stats() +
    `<section class="panel">${panelTop("sliders", "Parameter whitelist", "One shared whitelist for every registered device", `${state.summary.enabled_parameters} enabled`)}${state.parameters.length ?
      `<div class="table-scroll" tabindex="0" aria-label="Parameters table"><table><thead><tr><th>Parameter name</th><th>Value type</th><th>Scope</th><th>Status</th><th>Actions</th></tr></thead><tbody>${state.parameters.map((parameter) => `<tr><td><span class="parameter-pill ${parameterColor(parameter.name)}">${esc(parameter.name)}</span></td><td>Numeric</td><td><span class="muted">All devices</span></td><td><div class="status-control"><button class="toggle" role="switch" aria-checked="${parameter.enabled}" aria-label="Enable ${esc(parameter.name)}" data-toggle-parameter="${esc(parameter.name)}"></button>${status(parameter.enabled)}</div></td><td><div class="row-actions"><button class="icon-button danger" aria-label="Remove ${esc(parameter.name)}" data-remove-parameter="${esc(parameter.name)}">${icon("trash")}</button></div></td></tr>`).join("")}</tbody></table></div>` : empty("sliders", "Give your data a little direction", "Add the parameter names your sensors publish, such as temperature or humidity.", '<button class="button button-green" id="empty-add">Add your first parameter</button>')}
      <div class="table-bottom"><span>${state.parameters.length} ${state.parameters.length === 1 ? "parameter" : "parameters"} in your whitelist</span><span>Names are case-sensitive</span></div></section>` +
    info("<strong>History stays intact.</strong> Removing or disabling a parameter only affects new readings. Previously stored values remain available for viewing and export.");
  document.querySelector("#add-parameter").onclick = parameterForm;
  document.querySelector("#empty-add")?.addEventListener("click", parameterForm);
  main.querySelectorAll("[data-toggle-parameter]").forEach((button) => button.onclick = async () => {
    const parameter = state.parameters.find((p) => p.name === button.dataset.toggleParameter);
    button.disabled = true;
    try { await api(`/api/parameters/${encodeURIComponent(parameter.name)}`, {method: "PUT", body: JSON.stringify({enabled: !parameter.enabled})}); await loadPage(); toast(`Parameter ${parameter.enabled ? "disabled" : "enabled"}.`); }
    catch (error) { toast(error.message, true); button.disabled = false; }
  });
  main.querySelectorAll("[data-remove-parameter]").forEach((button) => button.onclick = () => removeParameter(button.dataset.removeParameter));
}
function modal(title, content, submitLabel, onSubmit, danger = false) {
  dialog.innerHTML = `<div class="dialog-heading"><h2 id="dialog-title">${title}</h2><button class="icon-button" type="button" data-close aria-label="Close dialog">${icon("close")}</button></div><form class="dialog-body">${content}<p class="form-error" id="dialog-error" role="alert" hidden></p><div class="dialog-footer"><button type="button" class="button button-outline" data-close>Cancel</button><button type="submit" class="button ${danger ? "button-danger" : "button-green"}">${submitLabel}</button></div></form>`;
  dialog.querySelectorAll("[data-close]").forEach((button) => button.onclick = () => dialog.close());
  const form = dialog.querySelector("form");
  form.onsubmit = async (event) => {
    event.preventDefault();
    const button = form.querySelector('[type="submit"]');
    const error = document.querySelector("#dialog-error");
    button.disabled = true; error.hidden = true;
    try { await onSubmit(new FormData(form)); dialog.close(); await loadPage(); }
    catch (err) { error.textContent = err.message; error.hidden = false; }
    finally { button.disabled = false; }
  };
  dialog.showModal();
}
function deviceForm(device) {
  modal(device ? "Edit device" : "Add a device", `<div class="field"><label for="device-name">Device name</label><input id="device-name" name="name" type="text" placeholder="e.g. Riverside station" maxlength="120" value="${esc(device?.name || "")}" required></div><div class="field"><label for="device-id">Device ID</label><input id="device-id" name="device_id" type="text" placeholder="e.g. sensor-01" pattern="[A-Za-z0-9][A-Za-z0-9_\\-]{0,63}" maxlength="64" value="${esc(device?.device_id || "")}" ${device ? "disabled" : "required"}><p class="field-help">${device ? "The ID stays fixed so incoming readings keep their connection." : "Match the ID configured on your sensor. Letters, numbers, hyphens and underscores only."}</p></div><label class="checkbox-label"><input type="checkbox" name="enabled" ${!device || device.enabled ? "checked" : ""}>Enable data collection for this device</label>`, device ? "Save changes" : "Add device", async (form) => {
    const body = {name: form.get("name").trim(), enabled: form.has("enabled")};
    if (!device) body.device_id = form.get("device_id").trim();
    await api(device ? `/api/devices/${encodeURIComponent(device.device_id)}` : "/api/devices", {method: device ? "PUT" : "POST", body: JSON.stringify(body)});
    toast(device ? "Device updated." : "Device added. You're ready to connect it.");
  });
}
function parameterForm() {
  modal("Add a parameter", '<div class="field"><label for="parameter-name">Parameter name</label><input id="parameter-name" name="name" type="text" placeholder="e.g. temperature" pattern="[A-Za-z][A-Za-z0-9_]{0,63}" maxlength="64" required><p class="field-help">Use the exact name sent by your sensor. Start with a letter; use letters, numbers and underscores.</p></div><label class="checkbox-label"><input type="checkbox" name="enabled" checked>Enable this parameter for all devices</label>', "Add parameter", async (form) => {
    await api("/api/parameters", {method: "POST", body: JSON.stringify({name: form.get("name").trim(), enabled: form.has("enabled")})});
    toast("Parameter added to your whitelist.");
  });
}
function removeParameter(name) {
  modal("Remove parameter?", `<p>New <strong>${esc(name)}</strong> readings will no longer be stored. Your existing readings will stay available.</p>`, "Remove parameter", async () => {
    await api(`/api/parameters/${encodeURIComponent(name)}`, {method: "DELETE"}); toast("Parameter removed. Historical data is unchanged.");
  }, true);
}
function clearDeviceData(device) {
  modal(
    "Clear all telemetry data?",
    `<p>This will permanently delete <strong>all stored readings</strong> for <strong>${esc(device.name)}</strong> (<code>${esc(device.device_id)}</code>).</p>
    <ul class="clear-data-list">
      <li>${icon("database")}All telemetry readings and transmission records</li>
      <li>${icon("refresh")}The deduplication history (allows the device to re-send old message IDs)</li>
    </ul>
    <p>The device registration, its name, and its enabled state are <strong>not</strong> affected. This action cannot be undone.</p>`,
    "Delete all data",
    async () => {
      await api(`/api/devices/${encodeURIComponent(device.device_id)}/telemetry`, {method: "DELETE"});
      toast(`All telemetry data for ${device.name} has been deleted.`);
    },
    true
  );
}
function deleteDevice(device) {
  modal(
    "Delete device and all data?",
    `<p>This will permanently delete <strong>${esc(device.name)}</strong> (<code>${esc(device.device_id)}</code>) and <strong>all its stored readings</strong>.</p>
    <ul class="clear-data-list">
      <li>${icon("database")}All telemetry readings and transmission records</li>
      <li>${icon("chip")}The device registration and MQTT credentials</li>
    </ul>
    <p>This action cannot be undone.</p>`,
    "Delete device",
    async () => {
      await api(`/api/devices/${encodeURIComponent(device.device_id)}`, {method: "DELETE"});
      toast(`${device.name} and its data have been deleted.`);

    },
    true
  );
}
function renderExport() {
  main.innerHTML = heading("TAKE YOUR DATA FURTHER", "CSV export", "Your field data, ready for its next chapter. Choose a time range and download.") +
    `<div class="export-grid"><section class="panel">${panelTop("download", "Create an export", "A simple file, with everything you need", '<span class="badge badge-green">CSV format</span>')}<form id="export-form" class="export-body"><p class="export-description">Export approved readings from all devices within a selected period. All dates and times below are in <strong>UTC</strong>.</p><div class="field-grid"><div class="field"><label for="start">Start date & time</label><input id="start" name="start" type="datetime-local" required><p class="field-help">Included in the export</p></div><div class="field"><label for="end">End date & time</label><input id="end" name="end" type="datetime-local" required><p class="field-help">Not included in the export</p></div></div><div class="quick-ranges"><span>Quick select</span><button class="range-button" type="button" data-hours="24">Last 24 hours</button><button class="range-button" type="button" data-hours="168">Last 7 days</button><button class="range-button" type="button" data-hours="720">Last 30 days</button></div><div class="export-divider"></div><div class="export-file"><div class="file-icon">${icon("file")}</div><div><strong>telemetry.csv</strong><small>Comma-separated values · UTF-8</small></div><span class="badge badge-gray">4 columns</span></div><p class="form-error" id="export-error" role="alert" hidden></p><button class="button button-green export-submit" type="submit">${icon("download")}<span>Download CSV</span></button><p class="export-note">Your stored data stays right where it is. This just makes a copy.</p><p class="export-success" id="export-success" role="status" hidden></p></form></section>
    <aside class="panel export-preview"><span class="eyebrow">A LOOK INSIDE</span><h3>Clean data. Ready to use.</h3><p>Open your CSV in a spreadsheet or bring it into your preferred analysis tool.</p><ul class="column-list"><li><code>timestamp</code><span>Reading time · UTC</span></li><li><code>device_id</code><span>Source device</span></li><li><code>parameter</code><span>Approved sensor parameter</span></li><li><code>value</code><span>Numeric reading</span></li></ul><div class="export-detail">${icon("info")}<p>One row per sensor value, ordered by time. If your range has no readings, the file will contain column headers only.</p></div></aside></div><div class="section-caption">${icon("shield")}Only approved, stored readings are included in your export.</div>`;
  const form = document.querySelector("#export-form");
  function setRange(hours) {
    const end = new Date(); end.setUTCMinutes(end.getUTCMinutes() + 1, 0, 0);
    form.end.value = end.toISOString().slice(0, 16);
    form.start.value = new Date(end.getTime() - hours * 3600000).toISOString().slice(0, 16);
    main.querySelectorAll("[data-hours]").forEach((button) => button.classList.toggle("active", Number(button.dataset.hours) === hours));
  }
  setRange(24);
  main.querySelectorAll("[data-hours]").forEach((button) => button.onclick = () => setRange(Number(button.dataset.hours)));
  form.querySelectorAll("input").forEach((input) => input.oninput = () => main.querySelectorAll("[data-hours]").forEach((button) => button.classList.remove("active")));
  form.onsubmit = async (event) => {
    event.preventDefault();
    const error = document.querySelector("#export-error");
    const success = document.querySelector("#export-success");
    const button = form.querySelector('[type="submit"]');
    error.hidden = true; success.hidden = true;
    const start = new Date(`${form.start.value}Z`), end = new Date(`${form.end.value}Z`);
    if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime()) || start >= end) { error.textContent = "Choose an end date and time after the start."; error.hidden = false; return; }
    button.disabled = true; button.querySelector("span").textContent = "Preparing your export…";
    try {
      const response = await fetch(`/api/telemetry/export?${new URLSearchParams({start: start.toISOString(), end: end.toISOString()})}`);
      if (response.status === 401) { location.replace("/login?expired=1"); return; }
      if (!response.ok) throw new Error("The export couldn't be created. Please try again.");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a"); link.href = url; link.download = "telemetry.csv"; document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      success.textContent = "Your CSV is ready. Check your browser's downloads."; success.hidden = false;
    } catch (err) { error.textContent = err.message; error.hidden = false; }
    finally { button.disabled = false; button.querySelector("span").textContent = "Download CSV"; }
  };
}

function toggleNavigation(open) {
  const sidebar = document.querySelector("#sidebar");
  sidebar.classList.toggle("open", open);
  sidebar.inert = !open && matchMedia("(max-width: 820px)").matches;
  document.querySelector(".workspace").inert = open;
  document.querySelector("#nav-backdrop").hidden = !open;
  document.querySelector("#menu-toggle").setAttribute("aria-expanded", String(open));
  if (open) sidebar.querySelector("nav a.active")?.focus();
  else if (matchMedia("(max-width: 820px)").matches) document.querySelector("#menu-toggle").focus();
}
document.querySelector("#menu-toggle").onclick = () => toggleNavigation(!document.querySelector("#sidebar").classList.contains("open"));
document.querySelector("#nav-backdrop").onclick = () => toggleNavigation(false);
document.addEventListener("keydown", (event) => {
  const sidebar = document.querySelector("#sidebar");
  if (!sidebar.classList.contains("open")) return;
  if (event.key === "Escape") toggleNavigation(false);
  if (event.key === "Tab") {
    const focusable = [...sidebar.querySelectorAll("a,button")];
    if (event.shiftKey && document.activeElement === focusable[0]) { event.preventDefault(); focusable.at(-1).focus(); }
    else if (!event.shiftKey && document.activeElement === focusable.at(-1)) { event.preventDefault(); focusable[0].focus(); }
  }
});
const mobileQuery = matchMedia("(max-width: 820px)");
document.querySelector("#sidebar").inert = mobileQuery.matches;
mobileQuery.addEventListener("change", () => toggleNavigation(false));
document.querySelector("#logout").onclick = async () => {
  try { await api("/api/auth/logout", {method: "POST"}); location.assign("/login"); }
  catch (error) { toast(error.message, true); }
};
function showIdentity() {
  const name = state.user.full_name || state.user.username;
  document.querySelector("#admin-name").textContent = name;
  const initials = name.slice(0, 2).toUpperCase();
  document.querySelector("#avatar").textContent = initials;
  document.querySelector("#topbar-avatar").textContent = initials;
}
document.querySelector("#edit-profile").onclick = async () => {
  try {
    const profile = await api("/api/profile");
    if (document.querySelector("#sidebar").classList.contains("open")) toggleNavigation(false);
    modal("Your profile", `<div class="field"><label for="profile-username">Username</label><input id="profile-username" type="text" value="${esc(profile.username)}" disabled><p class="field-help">Your sign-in username stays the same.</p></div><div class="field"><label for="profile-name">Full name</label><input id="profile-name" name="full_name" type="text" maxlength="120" autocomplete="name" value="${esc(profile.full_name)}" placeholder="Your name"></div><div class="field"><label for="profile-email">Email address</label><input id="profile-email" name="email" type="email" maxlength="254" autocomplete="email" value="${esc(profile.email)}" placeholder="you@example.com"><p class="field-help">Optional contact details. This address is not used for sign-in or password resets.</p></div>`, "Save profile", async (form) => {
      const result = await api("/api/profile", {method: "PUT", body: JSON.stringify({full_name: form.get("full_name"), email: form.get("email")})});
      state.user.full_name = result.full_name;
      showIdentity();
      toast("Your profile has been updated.");
    });
  } catch (error) { toast(error.message, true); }
};
document.querySelectorAll("[data-page]").forEach((link) => {
  if (link.dataset.page === route) { link.classList.add("active"); link.setAttribute("aria-current", "page"); }
});
document.querySelector("#breadcrumb-page").textContent = pageNames[route];
document.title = `${pageNames[route]} · Telemetry Hub`;
(async () => {
  try {
    state.user = await api("/api/auth/me");
    showIdentity();
    if (state.user.demo_mode) { document.querySelector("#workspace-name").textContent = "Demo workspace"; document.querySelector("#demo-badge").hidden = false; }
    await loadPage();
  } catch (error) { showPageError(error); }
})();
