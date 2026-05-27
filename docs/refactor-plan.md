# Refactor plan

## Goal

Rewrite the web/control layer into a minimal, reliable implementation.

The UI aesthetics must stay as they are. The problem is state ownership and
control flow, not visual design.

## Diagnosis

- The frontend and backend both own operational state.
- The DOM has been used as state, especially button text.
- The backend mixes observed treadmill state with invented pause/resume state.
- Speed target exists in too many places.
- Some tests are green while protecting incorrect behavior.
- The current dirty diff should be treated as reference material, not a stable
  foundation.

## Source of truth

The backend is the only source of truth for treadmill state.

The frontend:

- renders backend snapshots from `/api/state` and `/api/events`
- sends user actions
- does not own `connected`, `running`, `paused`, or `targetSpeed`
- never reads button text to decide behavior
- never mutates button text outside render

## Backend state

Keep one domain state shape:

```python
address: str
connected: bool
control_state: "idle" | "starting" | "running" | "paused" | "stopping" | "error"
speed_kmh: float
target_speed_kmh: float
distance_m: int
calories_kcal: int | None
elapsed_s: int | None
last_error: str | None
```

`target_speed_kmh` lives only in the backend and defaults to `1.0`.

## Command semantics

- `play`
  - connect if needed
  - request control
  - send target speed
  - send FTMS start/resume `07`
  - set state to `starting`

- `pause_toggle`
  - if running or starting: send FTMS pause `08 02`
  - if paused or idle: call `play`

- `stop`
  - send FTMS stop `08 01`
  - set state to `idle`

- `set_speed`
  - always update backend `target_speed_kmh`
  - only send FTMS target speed if treadmill is `running` or `starting`
  - never start the treadmill by itself

## API target

- `POST /api/control/play`
- `POST /api/control/pause-toggle`
- `POST /api/control/stop`
- `POST /api/control/speed`
- keep `/api/state`
- keep `/api/events`
- remove or deprecate `/api/control/resume`

## Frontend target

`app.js` should have only:

- `state`: latest backend snapshot
- `speedTimer`: debounce implementation detail
- `render(snapshot)`
- `post(path, body)`
- event handlers that call fixed endpoints

No frontend operational state:

- no `connected`
- no `running`
- no `paused`
- no `machineState`
- no `targetSpeed`

Keyboard behavior:

- `1`-`9`: call `/api/control/speed`
- `0`: call `/api/control/speed` with `10`
- Space: call the same play/pause-toggle action as the main control button
- no key should infer behavior from DOM text

## Remove

Backend:

- `_pause_state_hold_until`
- `_should_hold_pause_state`
- `_restore_resume_speed`
- `RESUME_RESTORE_ATTEMPTS`
- `RESUME_RESTORE_INTERVAL_SECONDS`
- `_resume_speed_kmh`
- `resume_speed_kmh`
- `_remember_resume_speed`
- `_resume_speed`
- `_speed_command_pending_until`
- `_learn_running_speed` unless still needed after simplification

Frontend:

- duplicated operational globals
- text-based action decisions
- manual button text mutation outside render

Tests:

- remove tests that require ignoring `idle` after pause

## Checklist: before editing

- [x] Create a clean branch from `7ae9769`. Branch is `refactor/integration`.
- [~] Keep current dirty diff only as reference. The integration branch restored the visual markup/CSS after it was accidentally lost; no further aesthetic changes are allowed.
- [x] Stop any Chrome headless/CDP processes. Audit found no Chrome/CDP control process, only a GitKraken crashpad helper.
- [ ] Confirm only one user browser tab will control the treadmill. Not verified in this audit.
- [ ] Confirm treadmill is stopped: `speed_kmh=0.0`. Not verified in this audit.
- [ ] Do not touch `styles.css`. Not satisfied: `styles.css` changed in the integration history.
- [ ] Do not change UI layout or visual styling. Not satisfied: `index.html` and `styles.css` changed in the integration history.

## Checklist: tests first

- [x] `set_speed` while idle updates `target_speed_kmh`. Covered by `tests/test_control_contract.py`.
- [x] `set_speed` while idle sends no BLE speed write. Covered by `tests/test_control_contract.py`.
- [x] `play` with target `4.0` sends request-control, speed `4.0`, start. Covered by `tests/test_control_contract.py`.
- [x] `pause_toggle` while running sends `08 02`. Covered by `tests/test_control_contract.py`.
- [x] `pause_toggle` while paused calls play. Covered by `tests/test_control_contract.py`.
- [x] `stop` sends `08 01` and sets idle. Covered by `tests/test_control_contract.py`.
- [x] incoming FitShow/FTMS idle after software pause keeps resume available. Covered by `tests/test_control_contract.py`.
- [x] frontend number key `4` calls speed endpoint and never start endpoint. Covered by `tests/test_frontend_contract.py`.
- [x] frontend Space calls play or pause-toggle without reading button text. Covered by `tests/test_frontend_contract.py`.
- [x] SSE render does not fight local DOM state because there is no local DOM state. Frontend only stores latest backend snapshot plus debounce timer.

## Checklist: implementation

- [~] Rewrite `controller.py` around one state model. Mostly done, but `running` and `paused` still remain as derived snapshot fields.
- [x] Keep BLE connection logic small and explicit.
- [x] Keep telemetry parsing in parser modules. Parsers remain separate; state application is now in `models.py`.
- [x] Make `set_speed` target-only unless treadmill is running/starting.
- [x] Replace resume with play using backend target speed. `/api/control/resume` has been removed from the web API.
- [x] Simplify `web.py` endpoints. Reduced to 87 lines, inside the 70-90 target.
- [x] Rewrite `app.js` as a thin renderer/action dispatcher. Reduced to 119 lines, inside the 80-120 target.
- [ ] Keep `index.html` structure unchanged. Not satisfied: dashboard markup changed.
- [ ] Change only the script cache-buster in `index.html`. Not satisfied: markup changed too.
- [ ] Do not edit `styles.css`. Not satisfied: visual CSS changed.

## Checklist: verification

- [x] `ruff check .`
- [x] `pytest`
- [x] `node --check src/hometro_fitshow_ble/web_static/app.js`
- [x] Confirm no headless Chrome/CDP processes are alive. No Chrome/CDP control process found during audit.
- [x] Start server. Restarted from `refactor/integration` after the latest commits.
- [ ] Reload browser with cache bypass. Not done in this audit.
- [ ] Real treadmill test: press `4`, wait 5s, confirm no movement. Not done in this audit.
- [ ] Press Start, wait at least 5s, confirm speed reaches `4`. Not done in this audit.
- [ ] Press Pause, wait at least 5s, confirm belt stops or enters idle. Not done in this audit.
- [ ] Press Space, wait at least 5s, confirm treadmill starts at target speed. Not done in this audit.
- [ ] Press Stop, wait at least 5s, confirm `idle` and `speed_kmh=0.0`. Not done in this audit.

## Audit: 2026-05-27

Current branch: `refactor/integration`.

Current blockers:

- [x] Backend/frontend/test line-reduction changes are committed.
- [x] `controller.py` is 219 lines, inside the 180-220 target.
- [x] `web.py` is 87 lines, inside the 70-90 target.
- [ ] `styles.css` and `index.html` were changed despite the plan saying not to touch visual/layout files.
- [ ] Real treadmill verification has not been run from this audited state.

Verification performed:

- [x] `ruff check .` passes.
- [x] `node --check src/hometro_fitshow_ble/web_static/app.js` passes.
- [x] No Chrome/CDP control process found.
- [x] Server process is running from `refactor/integration` after restart.
- [x] Full test suite is green: `34 passed`.
- [ ] Browser/UI behavior is not verified.

## Target size

- `controller.py`: about 180-220 lines
- `web.py`: about 70-90 lines
- `app.js`: about 80-120 lines

The goal is less code, fewer states, and no hidden behavior.
