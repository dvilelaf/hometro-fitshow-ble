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

function currentSpeed() {
  return Number.parseFloat(els.speedInput.value);
}

function formatElapsed(seconds) {
  const value = Math.max(0, Number(seconds || 0));
  const minutes = Math.floor(value / 60);
  const secs = Math.floor(value % 60);
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function setSpeedControl(value) {
  const speed = Math.min(14, Math.max(1, Number(value || 1)));
  els.speedInput.value = String(speed);
  els.speedInput.style.setProperty("--progress", `${((speed - 1) / 13) * 100}%`);
}

function setMessage(text = "", type = "") {
  els.connectionMessage.textContent = text;
  els.connectionMessage.classList.toggle("error", type === "error");
}

function isBusy(snapshot) {
  return snapshot?.connection_state === "connecting" || snapshot?.connection_state === "disconnecting";
}

function isConnected(snapshot) {
  return Boolean(snapshot?.connected);
}

function render(snapshot) {
  state = snapshot;

  const connected = isConnected(state);
  const busy = isBusy(state);
  const targetSpeed = Number(state.target_speed_kmh || 1);

  els.speed.textContent = Number(state.speed_kmh || 0).toFixed(1);
  if (els.target) {
    els.target.textContent =
      state.target_speed_kmh === null || state.target_speed_kmh === undefined
        ? "-"
        : targetSpeed.toFixed(1);
  }
  els.distanceKm.textContent = (Number(state.distance_m || 0) / 1000).toFixed(3);
  els.calories.textContent =
    state.calories_kcal === null || state.calories_kcal === undefined
      ? "-"
      : String(state.calories_kcal);
  els.elapsed.textContent = formatElapsed(state.elapsed_s);
  setSpeedControl(targetSpeed);

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

  els.pauseButton.textContent = state.paused ? "Resume" : "Pause";

  if (state.connection_state === "error" && state.last_error) {
    setMessage(state.last_error, "error");
  } else if (connected) {
    setMessage();
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
  return payload;
}

function cancelSpeedUpdate() {
  window.clearTimeout(speedDebounce);
  speedDebounce = null;
}

function run(action) {
  return async () => {
    cancelSpeedUpdate();
    try {
      setMessage();
      await action();
    } catch (error) {
      console.error(error);
      setMessage(error.message || String(error), "error");
    }
  };
}

function connectToggle() {
  return post(isConnected(state) ? "/api/disconnect" : "/api/connect");
}

function play() {
  return post("/api/control/play");
}

function pauseToggle() {
  return post("/api/control/pause-toggle");
}

function stop() {
  return post("/api/control/stop");
}

function mainControl() {
  return state?.paused ? pauseToggle() : play();
}

function sendSpeed(speed) {
  setSpeedControl(speed);
  return post("/api/control/speed", { speed_kmh: currentSpeed() });
}

function sendSpeedSoon(speed) {
  setSpeedControl(speed);
  window.clearTimeout(speedDebounce);
  speedDebounce = window.setTimeout(() => {
    speedDebounce = null;
    sendSpeed(currentSpeed()).catch((error) => {
      console.error(error);
      setMessage(error.message || String(error), "error");
    });
  }, 450);
}

els.connectionButton.addEventListener("click", run(connectToggle));
els.startButton.addEventListener("click", run(play));
els.pauseButton.addEventListener("click", run(pauseToggle));
els.stopButton.addEventListener("click", run(stop));

els.speedInput.addEventListener("input", () => sendSpeedSoon(els.speedInput.value));

for (let speed = 1; speed <= 14; speed += 1) {
  const tick = document.createElement("button");
  tick.type = "button";
  tick.textContent = String(speed);
  tick.style.left = `${((speed - 1) / 13) * 100}%`;
  tick.addEventListener("click", () => sendSpeed(speed).catch((error) => {
    console.error(error);
    setMessage(error.message || String(error), "error");
  }));
  els.speedTicks.appendChild(tick);
}

document.addEventListener("keydown", (event) => {
  if (event.repeat) {
    return;
  }

  if (event.code === "Space" || event.key === " " || event.key === "Spacebar") {
    event.preventDefault();
    run(mainControl)();
    return;
  }

  if (/^[0-9]$/.test(event.key)) {
    event.preventDefault();
    const speed = event.key === "0" ? 10 : Number(event.key);
    sendSpeed(speed).catch((error) => {
      console.error(error);
      setMessage(error.message || String(error), "error");
    });
  }
}, { capture: true });

fetch("/api/state")
  .then((response) => response.json())
  .then(render)
  .catch((error) => {
    console.error(error);
    setMessage(error.message || String(error), "error");
  });

const events = new EventSource("/api/events");
events.onmessage = (event) => render(JSON.parse(event.data));
events.onerror = (error) => console.error(error);
