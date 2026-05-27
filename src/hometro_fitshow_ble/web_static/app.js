const els = {
  speed: document.querySelector("#speed"),
  target: document.querySelector("#target"),
  distanceKm: document.querySelector("#distanceKm"),
  calories: document.querySelector("#calories"),
  elapsed: document.querySelector("#elapsed"),
  connectionButton: document.querySelector("#connectionButton"),
  connectionMessage: document.querySelector("#connectionMessage"),
  startButton: document.querySelector("#startButton"),
  pauseButton: document.querySelector("#pauseButton"),
  stopButton: document.querySelector("#stopButton"),
  speedInput: document.querySelector("#speedInput"),
  speedTicks: document.querySelector("#speedTicks"),
};

let state = null;
let speedDebounce = null;

function message(text = "", type = "") {
  els.connectionMessage.textContent = text;
  els.connectionMessage.classList.toggle("error", type === "error");
}

function showError(error) {
  console.error(error);
  message(error.message || String(error), "error");
}

function setSpeedInput(value) {
  const speed = Math.min(14, Math.max(1, Number(value || 1)));
  els.speedInput.value = String(speed);
  els.speedInput.style.setProperty("--progress", `${((speed - 1) / 13) * 100}%`);
  return speed;
}

function elapsedText(seconds) {
  const value = Math.max(0, Number(seconds || 0));
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
}

function render(snapshot) {
  state = snapshot;

  const connected = Boolean(state.connected);
  const busy = state.connection_state === "connecting" || state.connection_state === "disconnecting";
  const targetSpeed = Number(state.target_speed_kmh || 1);

  els.speed.textContent = Number(state.speed_kmh || 0).toFixed(1);
  els.distanceKm.textContent = (Number(state.distance_m || 0) / 1000).toFixed(3);
  els.calories.textContent = state.calories_kcal == null ? "-" : String(state.calories_kcal);
  els.elapsed.textContent = elapsedText(state.elapsed_s);
  els.pauseButton.textContent = state.paused ? "Resume" : "Pause";
  setSpeedInput(targetSpeed);

  if (els.target) {
    els.target.textContent = state.target_speed_kmh == null ? "-" : targetSpeed.toFixed(1);
  }

  els.connectionButton.disabled = busy;
  els.connectionButton.textContent = busy
    ? connected
      ? "Disconnecting..."
      : "Connecting..."
    : connected
      ? "Disconnect"
      : "Connect";
  els.connectionButton.classList.toggle("primary", !connected);
  els.connectionButton.classList.toggle("danger", connected);

  if (state.connection_state === "error" && state.last_error) {
    message(state.last_error, "error");
  } else if (connected) {
    message();
  }
}

async function post(path, body = undefined) {
  const response = await fetch(path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || response.statusText);
  }
  render(payload);
}

function cancelSpeed() {
  window.clearTimeout(speedDebounce);
  speedDebounce = null;
}

function action(fn) {
  return async () => {
    cancelSpeed();
    message();
    try {
      await fn();
    } catch (error) {
      showError(error);
    }
  };
}

function setSpeed(speed) {
  return post("/api/control/speed", { speed_kmh: setSpeedInput(speed) });
}

function setSpeedSoon(speed) {
  setSpeedInput(speed);
  window.clearTimeout(speedDebounce);
  speedDebounce = window.setTimeout(() => {
    speedDebounce = null;
    setSpeed(speed).catch(showError);
  }, 450);
}

els.connectionButton.addEventListener("click", action(() =>
  post(state?.connected ? "/api/disconnect" : "/api/connect")
));
els.startButton.addEventListener("click", action(() => post("/api/control/play")));
els.pauseButton.addEventListener("click", action(() => post("/api/control/pause-toggle")));
els.stopButton.addEventListener("click", action(() => post("/api/control/stop")));
els.speedInput.addEventListener("input", () => setSpeedSoon(els.speedInput.value));

for (let speed = 1; speed <= 14; speed += 1) {
  const tick = document.createElement("button");
  tick.type = "button";
  tick.textContent = String(speed);
  tick.style.left = `${((speed - 1) / 13) * 100}%`;
  tick.addEventListener("click", () => setSpeed(speed).catch(showError));
  els.speedTicks.appendChild(tick);
}

document.addEventListener("keydown", (event) => {
  if (event.repeat) {
    return;
  }

  if (event.code === "Space" || event.key === " " || event.key === "Spacebar") {
    event.preventDefault();
    action(() => post(state?.paused ? "/api/control/pause-toggle" : "/api/control/play"))();
    return;
  }

  if (/^[0-9]$/.test(event.key)) {
    event.preventDefault();
    setSpeed(event.key === "0" ? 10 : Number(event.key)).catch(showError);
  }
}, { capture: true });

fetch("/api/state")
  .then((response) => response.json())
  .then(render)
  .catch(showError);

const events = new EventSource("/api/events");
events.onmessage = (event) => render(JSON.parse(event.data));
events.onerror = (error) => console.error(error);
