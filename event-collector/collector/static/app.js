"use strict";
const $ = id => document.getElementById(id);
let connected = false, busy = false, cursor = null, shown = 0, generation = 0;
function message(text, error = false) { $("message").textContent = text; $("message").className = error ? "error" : ""; }
function setConnected(value) {
  connected = value; generation++;
  $("connection").hidden = value; $("session").hidden = !value;
  if (!value) {
    cursor = null; shown = 0; $("older").disabled = true;
    for (const id of ["health", "stored", "controllers", "last"]) $(id).textContent = "—";
    $("events").replaceChildren();
    const row = $("events").insertRow(), cell = row.insertCell();
    cell.colSpan = 6; cell.className = "empty"; cell.textContent = "Connect to load the archive.";
    $("count").textContent = "0 shown";
    $("source").replaceChildren(new Option("All controllers", ""));
  }
}
async function api(path, options = {}) {
  const current = generation;
  const response = await fetch(path, {credentials: "same-origin", cache: "no-store", ...options});
  if (!response.ok) {
    if (response.status === 401) {
      if (current === generation) setConnected(false);
      const error = new Error("Token or browser session rejected. Enter the collector’s API token and reconnect.");
      error.status = 401; throw error;
    }
    const detail = await response.json().catch(() => ({}));
    throw new Error(`API ${response.status}: ${typeof detail.detail === "string" ? detail.detail : "Check filter values or collector health."}`);
  }
  return response;
}
function selection() {
  const params = new URLSearchParams();
  for (const field of ["source", "event", "item"]) if ($(field).value) params.set(field, $(field).value);
  for (const field of ["since", "until"]) if ($(field).value) params.set(field, new Date($(field).value).toISOString());
  return params;
}
function localTime(value) { return value ? new Date(value).toLocaleString() : "None observed"; }
async function refresh(append = false) {
  if (!connected || busy) return;
  const current = generation;
  busy = true;
  try {
    const params = selection(); params.set("limit", "200");
    if (append && cursor) params.set("before_id", cursor);
    const [page, status, devices] = await Promise.all([
      api(`/api/v1/events?${params}`).then(r => r.json()),
      api("/api/v1/status").then(r => r.json()), api("/api/v1/controllers").then(r => r.json())
    ]);
    if (current !== generation) return;
    $("health").textContent = status.status === "ok" ? "Listening" : "Degraded";
    $("stored").textContent = status.stored_events.toLocaleString();
    $("controllers").textContent = devices.controllers.length;
    $("last").textContent = localTime(status.newest_received_at);
    const selected = $("source").value;
    $("source").replaceChildren(new Option("All controllers", ""));
    for (const device of devices.controllers) $("source").add(new Option(device.source, device.source));
    if (selected && !devices.controllers.some(d => d.source === selected)) $("source").add(new Option(selected, selected));
    $("source").value = selected;
    if (!append) { $("events").replaceChildren(); shown = 0; }
    for (const event of page.events) {
      const row = document.createElement("tr");
      for (const value of [localTime(event.received_at), event.source, event.event, event.item, event.reason || "—", event.id]) {
        const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
      }
      row.firstChild.title = event.received_at; $("events").append(row); shown++;
    }
    if (!shown) { const row = $("events").insertRow(); const cell = row.insertCell(); cell.colSpan = 6; cell.className = "empty"; cell.textContent = "No events match these filters."; }
    cursor = page.next_before_id; $("older").disabled = !page.has_more;
    $("count").textContent = `${shown.toLocaleString()} shown · newest first`;
    const counters = status.counters;
    const losses = counters.queue_overflows + counters.write_errors;
    message(`Updated ${new Date().toLocaleTimeString()} · ${counters.invalid_packets} invalid packets · ${losses} events lost by this collector since startup${status.storage_error ? " · Storage error" : ""}${status.retention_error ? " · Retention error" : ""}`, losses > 0 || status.status !== "ok");
  } catch (error) { if (current === generation || !connected) message(error.message, true); }
  finally { busy = false; }
}
$("connection").addEventListener("submit", async event => {
  event.preventDefault(); $("connect").disabled = true;
  try {
    await api("/api/v1/session", {method: "POST", headers: {
      Authorization: `Bearer ${$("token").value.trim()}`, "Content-Type": "application/json"
    }, body: JSON.stringify({remember: $("remember").checked})});
    $("token").value = ""; setConnected(true); await refresh();
  } catch (error) { message(error.message, true); }
  finally { $("connect").disabled = false; }
});
$("signout").addEventListener("click", async () => {
  $("signout").disabled = true;
  try {
    await api("/api/v1/session", {method: "DELETE"});
    setConnected(false); $("token").value = ""; message("Signed out on this browser.");
  } catch (error) { message(error.message, true); }
  finally { $("signout").disabled = false; }
});
$("filters").addEventListener("submit", event => { event.preventDefault(); refresh(); });
$("older").addEventListener("click", () => { $("auto").checked = false; refresh(true); });
$("export").addEventListener("click", async () => {
  if (!connected) { message("Connect before exporting.", true); return; }
  const current = generation;
  try {
    const params = selection(); params.set("limit", "1000");
    const response = await api(`/api/v1/events.csv?${params}`);
    if (current !== generation) return;
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a"); link.href = url; link.download = "controller-events.csv"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    message(response.headers.get("X-Has-More") === "true" ? "Exported newest 1,000 matches. Use narrower filters or API pagination for the rest." : "Exported matching events.");
  } catch (error) { message(error.message, true); }
});
setInterval(() => { if ($("auto").checked && !document.hidden) refresh(); }, 5000);
(async () => {
  const current = generation;
  try {
    await api("/api/v1/session");
    if (current !== generation) return;
    setConnected(true); await refresh();
  }
  catch (error) { if (error.status !== 401) message(error.message, true); }
})();
