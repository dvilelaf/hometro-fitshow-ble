const stateEls = {
  speed: document.querySelector("#speed"),
  distanceKm: document.querySelector("#distanceKm"),
  calories: document.querySelector("#calories"),
  elapsed: document.querySelector("#elapsed"),
  connectionButton: document.querySelector("#connectionButton"),
  connectionMessage: document.querySelector("#connectionMessage"),
  pauseButton: document.querySelector("#pauseButton"),
  speedInput: document.querySelector("#speedInput"),
  speedTicks: document.querySelector("#speedTicks"),
};

let connected = false;
let connectionBusy = false;
let connectionState = "disconnected";
let speedDebounce = null;

function speedValue() {
  return Number.parseFloat(stateEls.speedInput.value);
}

function setSpeedControl(value) {
  const clamped = Math.min(14, Math.max(1, Number(value)));
  stateEls.speedInput.value = String(clamped);
}

function formatElapsed(seconds) {
  if (seconds === null || seconds === undefined) {
    return "00:00";
  }
  const value = Math.max(0, Number(seconds));
  const minutes = Math.floor(value / 60);
  const secs = Math.floor(value % 60);
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function setConnectionMessage(message = "", type = "") {
  stateEls.connectionMessage.textContent = message;
  stateEls.connectionMessage.classList.toggle("error", type === "error");
}

function renderConnectionButton() {
  if (
    connectionBusy ||
    connectionState === "connecting" ||
    connectionState === "disconnecting"
  ) {
    stateEls.connectionButton.disabled = true;
    stateEls.connectionButton.textContent =
      connectionState === "disconnecting" ? "Disconnecting..." : "Connecting...";
    return;
  }
  stateEls.connectionButton.disabled = false;
  stateEls.connectionButton.textContent = connected ? "Disconnect" : "Connect";
  stateEls.connectionButton.classList.toggle("primary", !connected);
  stateEls.connectionButton.classList.toggle("danger", connected);
}

function renderState(state) {
  connected = Boolean(state.connected);
  connectionState = state.connection_state || (connected ? "connected" : "disconnected");
  renderConnectionButton();
  if (connectionState === "error" && state.last_error) {
    setConnectionMessage(state.last_error, "error");
  } else if (connected) {
    setConnectionMessage();
  }
  stateEls.speed.textContent = Number(state.speed_kmh || 0).toFixed(1);
  stateEls.distanceKm.textContent = (Number(state.distance_m || 0) / 1000).toFixed(3);
  stateEls.calories.textContent =
    state.calories_kcal === null || state.calories_kcal === undefined
      ? "-"
      : String(state.calories_kcal);
  stateEls.elapsed.textContent = formatElapsed(state.elapsed_s);
  stateEls.pauseButton.textContent = state.paused ? "Resume" : "Pause";
}

async function api(path, body = undefined) {
  const response = await fetch(path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || response.statusText);
  }
  renderState(payload);
  return payload;
}

function bindButton(id, action) {
  const button = document.querySelector(id);
  button.addEventListener("click", async () => {
    const isConnectionButton = button === stateEls.connectionButton;
    try {
      if (isConnectionButton) {
        connectionBusy = true;
        connectionState = connected ? "disconnecting" : "connecting";
        button.disabled = true;
        button.textContent = connected ? "Disconnecting..." : "Connecting...";
      }
      setConnectionMessage();
      await action();
    } catch (error) {
      console.error(error);
      if (isConnectionButton) {
        connectionState = connected ? "connected" : "error";
      }
      setConnectionMessage(error.message || String(error), "error");
    } finally {
      if (isConnectionButton) {
        connectionBusy = false;
        if (connectionState === "connecting" || connectionState === "disconnecting") {
          connectionState = connected ? "connected" : "disconnected";
        }
        renderConnectionButton();
      }
    }
  });
}

function scheduleSpeedUpdate() {
  window.clearTimeout(speedDebounce);
  if (!connected) {
    return;
  }
  speedDebounce = window.setTimeout(async () => {
    try {
      await api("/api/control/speed", { speed_kmh: speedValue() });
    } catch (error) {
      console.error(error);
    }
  }, 450);
}

stateEls.speedInput.addEventListener("input", () => {
  setSpeedControl(stateEls.speedInput.value);
  scheduleSpeedUpdate();
});

bindButton("#connectionButton", () => api(connected ? "/api/disconnect" : "/api/connect"));
bindButton("#startButton", () => api("/api/control/start", { speed_kmh: speedValue() }));
bindButton("#pauseButton", () =>
  api(stateEls.pauseButton.textContent === "Resume" ? "/api/control/resume" : "/api/control/pause")
);
bindButton("#stopButton", () => api("/api/control/stop"));

for (let speed = 1; speed <= 14; speed += 1) {
  const tick = document.createElement("button");
  tick.type = "button";
  tick.textContent = String(speed);
  tick.style.left = `${((speed - 1) / 13) * 100}%`;
  tick.addEventListener("click", () => {
    setSpeedControl(speed);
    scheduleSpeedUpdate();
  });
  stateEls.speedTicks.appendChild(tick);
}

document.addEventListener("keydown", (event) => {
  if (!/^[0-9]$/.test(event.key)) {
    return;
  }
  const speed = event.key === "0" ? 10 : Number(event.key);
  setSpeedControl(speed);
  scheduleSpeedUpdate();
});

fetch("/api/state")
  .then((response) => response.json())
  .then(renderState)
  .catch((error) => console.error(error));

const events = new EventSource("/api/events");
events.onmessage = (event) => renderState(JSON.parse(event.data));
events.onerror = (error) => console.error(error);
