const els = Object.fromEntries("speed target distanceKm calories elapsed scanButton connectionButton connectionMessage devicePanel deviceList startButton stopButton speedInput speedTicks".split(" ").map((id) => [id, document.querySelector(`#${id}`)]));

let speedDebounce = null;
const clampSpeed = (value) => Math.min(14, Math.max(1, Number(value || 1)));

function message(text = "", error = false) {
  els.connectionMessage.textContent = text;
  els.connectionMessage.classList.toggle("error", error);
}

function report(error) {
  console.error(error);
  message(error.message || String(error), true);
}

function showSpeed(value) {
  const speed = clampSpeed(value);
  els.speedInput.value = String(speed);
  els.speedInput.style.setProperty("--progress", `${((speed - 1) / 13) * 100}%`);
  return speed;
}

function render(state) {
  const target = Number(state.target_speed_kmh || 1);
  const connected = Boolean(state.connected);
  const busy = ["connecting", "disconnecting"].includes(state.connection_state);
  const seconds = Math.max(0, Number(state.elapsed_s || 0));

  els.speed.textContent = Number(state.speed_kmh || 0).toFixed(1);
  els.distanceKm.textContent = (Number(state.distance_m || 0) / 1000).toFixed(3);
  els.calories.textContent = state.calories_kcal == null ? "-" : String(state.calories_kcal);
  els.elapsed.textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  els.startButton.textContent = state.primary_action_label || "Start";
  if (els.target) els.target.textContent = state.target_speed_kmh == null ? "-" : target.toFixed(1);
  showSpeed(target);

  els.connectionButton.disabled = busy;
  els.connectionButton.textContent = busy ? connected ? "Disconnecting..." : "Connecting..." : "Disconnect";
  els.connectionButton.hidden = !connected && !busy;
  els.connectionButton.classList.toggle("danger", connected || busy);
  if (state.connection_state === "error" && state.last_error) message(state.last_error, true);
  else if (connected) message(`Connected to ${state.address}`);
}

async function post(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.detail || response.statusText);
  render(payload);
}

function cancelSpeed() {
  window.clearTimeout(speedDebounce?.id);
  speedDebounce = null;
}

function setSpeed(speed) {
  cancelSpeed();
  return post("/api/control/speed", { speed_kmh: showSpeed(speed) });
}

async function flushSpeed() {
  if (!speedDebounce) return;
  const { speed } = speedDebounce;
  cancelSpeed();
  await setSpeed(speed);
}

function action(fn, flush = false) {
  return async () => {
    message();
    try {
      flush ? await flushSpeed() : cancelSpeed();
      await fn();
    } catch (error) {
      report(error);
    }
  };
}

function deviceName(device) {
  return device.local_name || device.name || device.address || "Unknown device";
}

function renderDevices(devices) {
  els.deviceList.replaceChildren();
  els.devicePanel.hidden = false;

  if (!devices.length) {
    const empty = document.createElement("div");
    empty.className = "device-empty";
    empty.textContent = "No devices found";
    els.deviceList.appendChild(empty);
    return;
  }

  for (const device of devices) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "device-button";
    button.innerHTML = `<strong></strong><span></span>`;
    button.querySelector("strong").textContent = deviceName(device);
    button.querySelector("span").textContent = [device.address, device.rssi == null ? null : `${device.rssi} dBm`].filter(Boolean).join(" · ");
    button.addEventListener("click", action(() => post("/api/connect", { address: device.address })));
    els.deviceList.appendChild(button);
  }
}

async function scanDevices() {
  message("Searching...");
  els.scanButton.disabled = true;
  try {
    const response = await fetch("/api/devices/scan?timeout_s=5");
    const devices = await response.json();
    if (!response.ok) throw new Error(devices.detail || response.statusText);
    renderDevices(devices.filter((device) => device.address));
    message();
  } catch (error) {
    report(error);
  } finally {
    els.scanButton.disabled = false;
  }
}

els.scanButton.addEventListener("click", scanDevices);
els.connectionButton.addEventListener("click", action(() => post("/api/disconnect")));
els.startButton.addEventListener("click", action(() => post("/api/control/primary"), true));
els.stopButton.addEventListener("click", action(() => post("/api/control/stop")));
els.speedInput.addEventListener("input", () => {
  const speed = showSpeed(els.speedInput.value);
  window.clearTimeout(speedDebounce?.id);
  speedDebounce = { speed, id: window.setTimeout(() => setSpeed(speed).catch(report), 450) };
});

for (let speed = 1; speed <= 14; speed += 1) {
  const tick = document.createElement("button");
  tick.type = "button";
  tick.textContent = String(speed);
  tick.style.left = `${((speed - 1) / 13) * 100}%`;
  tick.addEventListener("click", () => setSpeed(speed).catch(report));
  els.speedTicks.appendChild(tick);
}

document.addEventListener("keydown", (event) => {
  if (event.repeat) return;
  if (event.code === "Space" || event.key === " " || event.key === "Spacebar") {
    event.preventDefault();
    action(() => post("/api/control/primary"), true)();
  } else if (/^[0-9]$/.test(event.key)) {
    event.preventDefault();
    setSpeed(event.key === "0" ? 10 : Number(event.key)).catch(report);
  }
}, { capture: true });
fetch("/api/state").then((response) => response.json()).then(render).catch(report);
const events = new EventSource("/api/events");
events.onmessage = (event) => render(JSON.parse(event.data));
events.onerror = (error) => console.error(error);
