// main.js — KIDA web HUD live updater

const STATUS_INTERVAL = 2000;

const MODE_COLORS = {
  KEYBOARD:      'mode-KEYBOARD',
  IR_REMOTE:     'mode-IR_REMOTE',
  AUTONOMOUS:    'mode-AUTONOMOUS',
  LINE_FOLLOWER: 'mode-LINE_FOLLOWER',
  WATCHDOG:      'mode-WATCHDOG',
  LANE_DETECT:   'mode-LANE_DETECT',
  PERSON_FOLLOW: 'mode-PERSON_FOLLOW',
  IDLE:          'mode-IDLE',
};

function $(id) { return document.getElementById(id); }

let _lastPhotoTs = null;

function applyStatus(data) {
  // Power row
  const pr = $('power-row');
  if (pr) {
    const v    = data.bus_v   != null ? data.bus_v.toFixed(2)   : '—';
    const a    = data.cur_ma  != null ? (data.cur_ma / 1000).toFixed(3) : '—';
    const w    = data.pwr_w   != null ? data.pwr_w.toFixed(2)   : '—';
    const pct  = data.bat_pct != null ? data.bat_pct.toFixed(0) : '—';
    pr.textContent = `⚡ ${v}V   ${a}A   ${w}W   🔋 ${pct}%`;
  }

  // Status strip
  $('st-spd').textContent  = `Spd:${data.motor_speed ?? '—'}`;
  $('st-temp').textContent = `T:${data.cpu_temp ?? '—'}`;
  $('st-cpu').textContent  = `CPU:${data.cpu ?? '—'}%`;
  $('st-ram').textContent  = `RAM:${data.ram ?? '—'}%`;
  $('st-ip').textContent   = `IP:${data.ip ?? '—'}`;
  $('st-inf').textContent  = `Inf:${data.inference_on ? 'ON' : 'off'}`;

  // Music badge
  const musBadge = $('st-mus');
  if (data.music_on) {
    musBadge.textContent = '♪ ON';
    musBadge.classList.add('playing');
  } else {
    musBadge.textContent = '♪ off';
    musBadge.classList.remove('playing');
  }

  // Mode badge
  const modeBadge = $('st-mode');
  modeBadge.textContent = `[${data.mode ?? '—'}]`;
  modeBadge.className   = 'mode-badge ' + (MODE_COLORS[data.mode] || '');
  syncModeDropdown(data.mode);
  syncVoiceButtons(data.voice_mode);

  // Sensors
  const sensors = data.sensors || {};
  for (const [label, value] of Object.entries(sensors)) {
    const el = document.getElementById(`s-${label}`);
    if (el) el.textContent = value ?? '—';
  }

  // Play button label flips based on music state
  const playBtn = $('web-play-btn');
  if (playBtn) playBtn.textContent = data.music_on ? '⏭ Skip' : '▶ Play';

  // Lock button reflects live motor_lock state
  syncLockButton(!!data.motor_lock);

  // Drive scheme button reflects live state (also driven by the </> keys)
  syncSchemeButton(data.drive_scheme === 'QAWS' ? 'QAWS' : 'WASD');

  // Highlight whichever camera slot "Switch Cam" made active
  const slot0 = $('cam-slot-0');
  const slot1 = $('cam-slot-1');
  if (slot0) slot0.classList.toggle('cam-active', data.active_cam_id === 0);
  if (slot1) slot1.classList.toggle('cam-active', data.active_cam_id === 1);

  // Last-photo panel — only refetch the image when a new photo was taken
  if (data.last_photo_ts && data.last_photo_ts !== _lastPhotoTs) {
    _lastPhotoTs = data.last_photo_ts;
    const photoImg = $('last-photo-feed');
    if (photoImg) photoImg.src = '/last_photo?t=' + data.last_photo_ts;
  }
}

async function fetchStatus() {
  try {
    const res  = await fetch('/status');
    const data = await res.json();
    applyStatus(data);
  } catch (_) {
    // server not yet ready — silently retry
  }
}

// Initial fetch then poll
fetchStatus();
setInterval(fetchStatus, STATUS_INTERVAL);

// Re-show cam feed if it recovers after an error
document.querySelectorAll('.cam-feed').forEach(img => {
  img.addEventListener('load', () => {
    img.style.display = '';
    const nosig = img.nextElementSibling;
    if (nosig) nosig.style.display = 'none';
  });
});

// Map mode name → dropdown option value
const MODE_SELECT_MAP = {
  KEYBOARD:      'mode_1',
  IR_REMOTE:     'mode_2',
  AUTONOMOUS:    'mode_3',
  IDLE:          'mode_4',
  LINE_FOLLOWER: 'mode_5',
  WATCHDOG:      'mode_6',
  LANE_DETECT:   'mode_7',
  PERSON_FOLLOW: 'mode_8',
};

async function sendAction(cmd, password) {
  try {
    const body = { command: cmd };
    if (password != null) body.password = password;
    const res  = await fetch('/action', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(body),
    });
    const data = res.ok ? await res.json() : null;
    fetchStatus();
    return data;
  } catch (_) {
    return null;
  }
}

// Action buttons — send POST /action with {command}
document.querySelectorAll('.act-btn[data-cmd]').forEach(btn => {
  btn.addEventListener('click', () => sendAction(btn.dataset.cmd));
});

// Mode dropdown — applies immediately on selection. Previously this only
// fired on the separate "Go" button, so picking a mode and not clicking Go
// left the change pending; the next /status poll (every 2s) then called
// syncModeDropdown() and silently snapped the dropdown back to whatever
// mode the robot was actually still in (often AUTONOMOUS), which looked
// like "selecting a mode reverts to autonomous." Go is kept as a no-op-safe
// fallback for browsers/inputs that don't fire 'change' the way you'd expect.
const modeSelect = document.getElementById('mode-select');
const modeGoBtn  = document.getElementById('mode-go-btn');
if (modeSelect) {
  modeSelect.addEventListener('change', () => sendAction(modeSelect.value));
}
if (modeGoBtn && modeSelect) {
  modeGoBtn.addEventListener('click', () => sendAction(modeSelect.value));
}

function syncModeDropdown(modeName) {
  const val = MODE_SELECT_MAP[modeName];
  if (!val) return;
  // Don't overwrite the dropdown while the user currently has it focused —
  // a poll landing mid-selection shouldn't fight their in-progress pick.
  if (modeSelect && document.activeElement !== modeSelect) modeSelect.value = val;
  const idx = MODE_CYCLE.indexOf(val);
  if (idx !== -1) _modeCycleIdx = idx;
}

// Voice mode buttons
const voiceWakewordBtn  = document.getElementById('voice-wakeword-btn');
const voiceAlwaysOnBtn  = document.getElementById('voice-always-on-btn');

function syncVoiceButtons(voiceMode) {
  if (voiceWakewordBtn) voiceWakewordBtn.classList.toggle('active', voiceMode === 'WAKEWORD');
  if (voiceAlwaysOnBtn) voiceAlwaysOnBtn.classList.toggle('active', voiceMode === 'ALWAYS_ON');
}

// ── Voice recording on this device (mic workaround) ─────────────
// Records with the browser's own mic (usually much better than the
// robot's onboard USB dongle) and uploads the clip to /voice_upload,
// which runs it through the same Whisper→LLM pipeline as the wake word.
// Note: getUserMedia needs a secure context — this will fail on plain
// http://<lan-ip>:port origins in most browsers (localhost is exempt).
const voiceRecordBtn  = document.getElementById('voice-record-btn');
const voiceTranscript = document.getElementById('voice-transcript');
let _mediaRecorder = null;
let _recordedChunks = [];
let _isRecording = false;

async function toggleVoiceRecording() {
  if (_isRecording) {
    _mediaRecorder.stop();
    return;
  }
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    window.alert('Voice recording needs HTTPS (or localhost) and browser mic support.');
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    _recordedChunks = [];
    _mediaRecorder = new MediaRecorder(stream);
    _mediaRecorder.addEventListener('dataavailable', (e) => {
      if (e.data.size > 0) _recordedChunks.push(e.data);
    });
    _mediaRecorder.addEventListener('stop', () => {
      stream.getTracks().forEach((t) => t.stop());
      uploadVoiceRecording();
    });
    _mediaRecorder.start();
    _isRecording = true;
    voiceRecordBtn.textContent = '⏹ Stop & Send';
    voiceRecordBtn.classList.add('recording');
  } catch (err) {
    window.alert('Microphone access denied or unavailable: ' + err.message);
  }
}

async function uploadVoiceRecording() {
  _isRecording = false;
  voiceRecordBtn.textContent = '🎤 Record';
  voiceRecordBtn.classList.remove('recording');

  if (voiceTranscript) {
    voiceTranscript.style.display = '';
    voiceTranscript.textContent = '⏳ Transcribing…';
  }

  const blob = new Blob(_recordedChunks, { type: _mediaRecorder.mimeType || 'audio/webm' });
  const formData = new FormData();
  formData.append('audio', blob, 'recording.webm');

  try {
    const res  = await fetch('/voice_upload', { method: 'POST', body: formData });
    const data = await res.json();
    if (voiceTranscript) {
      voiceTranscript.textContent = data.ok
        ? `You said: "${data.transcribed || '(nothing heard)'}"`
        : `Error: ${data.error || 'upload failed'}`;
    }
  } catch (e) {
    if (voiceTranscript) voiceTranscript.textContent = 'Upload failed — network error.';
  }
}

if (voiceRecordBtn) {
  voiceRecordBtn.addEventListener('click', toggleVoiceRecording);
}

// ── Motor lock button ──────────────────────────────────────────
const lockBtn = document.getElementById('lock-btn');
let _motorLocked = true;

function syncLockButton(locked) {
  _motorLocked = locked;
  if (!lockBtn) return;
  lockBtn.textContent = locked ? '🔒 Locked' : '🔓 Unlocked';
  lockBtn.classList.toggle('unlocked', !locked);
}

async function toggleLock() {
  if (_motorLocked) {
    const pw = window.prompt('Enter password to unlock motors:');
    if (pw === null) return;
    const res = await sendAction('motor_lock_off', pw);
    if (!res || !res.ok) window.alert('Wrong password — motors stay locked.');
  } else {
    await sendAction('motor_lock_on');
  }
}

if (lockBtn) {
  lockBtn.addEventListener('click', toggleLock);
}

// ── Keyboard controls ───────────────────────────────────────────
// Mirrors the shortcuts listed in the Controls panel. Drive keys send a
// direction on keydown and a stop on keyup; the rest fire once per press.
const DRIVE_KEYS = {
  w: 'move_forward',
  s: 'move_backward',
  a: 'move_left',
  d: 'move_right',
};

const ACTION_KEYS = {
  x: 'speed_cycle',
  i: 'inference_toggle',
  m: 'music_play',
  l: 'leds_toggle',
  k: 'leds_effects_toggle',
};

function isTypingTarget(el) {
  if (!el) return false;
  const tag = el.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable;
}

// Drive "channels" — each is a stack of active commands (not key labels)
// so releasing the most recently pressed input resumes whichever command
// is still held, instead of freezing on the last one. WASD scheme only
// ever uses 'main' (both motors move together). QAWS (tank) scheme uses
// 'left' and 'right' independently, since each side is a separate motor
// that can be held/released without affecting the other.
//
// Dead-man's switch: the backend auto-stops the motors if it doesn't see a
// drive command within ~800ms (scripts/web_bridge.py: check_web_drive_timeout).
// So while a key/button is held we must keep resending, or a dropped tab/
// connection would otherwise leave the robot driving forever with no way
// to reach it.
const DRIVE_HEARTBEAT_MS = 300;
const _driveChannels = {
  main:  { stack: [], timer: null, stopCmd: 'move_stop' },
  left:  { stack: [], timer: null, stopCmd: 'left_stop' },
  right: { stack: [], timer: null, stopCmd: 'right_stop' },
};

// The 'main' (WASD) channel combines everything held, like scripts/drive_mix.py:
// one direction = the usual preset, a diagonal (W+A, S+D...) = 'move_curve',
// where both tracks keep turning and the inside one runs slower — so she
// turns while moving instead of one motor stopping. W+S / A+D cancel out.
function mainDriveBody(stack) {
  const throttle = (stack.includes('move_forward') ? 1 : 0) - (stack.includes('move_backward') ? 1 : 0);
  const turn     = (stack.includes('move_right') ? 1 : 0) - (stack.includes('move_left') ? 1 : 0);
  if (throttle && turn) return { command: 'move_curve', throttle, turn };
  if (throttle) return { command: throttle > 0 ? 'move_forward' : 'move_backward' };
  if (turn) return { command: turn > 0 ? 'move_right' : 'move_left' };
  return null;
}

function sendChannel(channelName) {
  const ch = _driveChannels[channelName];
  if (channelName === 'main') {
    const body = mainDriveBody(ch.stack);
    if (body) postJoy(body).catch(() => {});
    else sendAction(ch.stopCmd);
    return;
  }
  sendAction(ch.stack[ch.stack.length - 1]);
}

function pressDrive(channelName, cmd) {
  const ch = _driveChannels[channelName];
  if (!ch.stack.includes(cmd)) ch.stack.push(cmd);
  sendChannel(channelName);
  if (!ch.timer) {
    ch.timer = setInterval(() => {
      if (ch.stack.length) sendChannel(channelName);
    }, DRIVE_HEARTBEAT_MS);
  }
}

function releaseDrive(channelName, cmd) {
  const ch  = _driveChannels[channelName];
  const idx = ch.stack.indexOf(cmd);
  if (idx === -1) return;
  ch.stack.splice(idx, 1);
  if (ch.stack.length === 0) {
    if (ch.timer) { clearInterval(ch.timer); ch.timer = null; }
    sendAction(ch.stopCmd);
  } else {
    sendChannel(channelName);
  }
}

function stopAllDriveChannels() {
  for (const name of Object.keys(_driveChannels)) {
    const ch = _driveChannels[name];
    if (ch.stack.length === 0) continue;
    ch.stack.length = 0;
    if (ch.timer) { clearInterval(ch.timer); ch.timer = null; }
    sendAction(ch.stopCmd);
  }
}

// QAWS (tank) key map — Q/A drive the left motor, W/S drive the right motor,
// independently of each other. Toggled via the Scheme button or </>.
const QAWS_KEYS = {
  q: { channel: 'left',  cmd: 'left_forward'   },
  a: { channel: 'left',  cmd: 'left_backward'  },
  w: { channel: 'right', cmd: 'right_forward'  },
  s: { channel: 'right', cmd: 'right_backward' },
};

let driveScheme = 'WASD'; // synced from /status by applyStatus()

window.addEventListener('keydown', (e) => {
  if (isTypingTarget(document.activeElement) || e.repeat) return;
  const key = e.key.toLowerCase();

  if (key === ' ') {
    e.preventDefault();
    sendAction('hard_stop');
    return;
  }
  if (key === '<' || key === ',') {
    e.preventDefault();
    syncSchemeButton('WASD');   // optimistic — don't wait on the round trip
    sendAction('scheme_wasd');
    return;
  }
  if (key === '>' || key === '.') {
    e.preventDefault();
    syncSchemeButton('QAWS');
    sendAction('scheme_qaws');
    return;
  }
  if (key === '[') {
    e.preventDefault();
    cycleMode(-1);
    return;
  }
  if (key === ']') {
    e.preventDefault();
    cycleMode(1);
    return;
  }
  if (key === 'u') {
    e.preventDefault();
    toggleLock();
    return;
  }
  if (driveScheme === 'QAWS' && QAWS_KEYS[key]) {
    e.preventDefault();
    const { channel, cmd } = QAWS_KEYS[key];
    pressDrive(channel, cmd);
    return;
  }
  if (driveScheme === 'WASD' && DRIVE_KEYS[key]) {
    e.preventDefault();
    pressDrive('main', DRIVE_KEYS[key]);
    return;
  }
  if (ACTION_KEYS[key]) {
    e.preventDefault();
    sendAction(ACTION_KEYS[key]);
  }
});

window.addEventListener('keyup', (e) => {
  const key = e.key.toLowerCase();
  if (driveScheme === 'QAWS' && QAWS_KEYS[key]) {
    const { channel, cmd } = QAWS_KEYS[key];
    releaseDrive(channel, cmd);
  } else if (DRIVE_KEYS[key]) {
    releaseDrive('main', DRIVE_KEYS[key]);
  }
});

// Stop driving if the tab/window loses focus (key held then alt-tabbed away).
window.addEventListener('blur', stopAllDriveChannels);

// ── On-screen drive pad (touch/mouse) — always the simple differential
// (WASD-equivalent) scheme regardless of the current keyboard scheme, since
// a single D-pad doesn't map naturally to independent per-motor control.
document.querySelectorAll('.dpad-btn[data-drive]').forEach((btn) => {
  const cmd = btn.dataset.drive;
  btn.addEventListener('pointerdown', (e) => { e.preventDefault(); pressDrive('main', cmd); });
  btn.addEventListener('pointerup',     () => releaseDrive('main', cmd));
  btn.addEventListener('pointerleave',  () => releaseDrive('main', cmd));
  btn.addEventListener('pointercancel', () => releaseDrive('main', cmd));
});

// ── [/] mode cycling ─────────────────────────────────────────────
const MODE_CYCLE = ['mode_1', 'mode_2', 'mode_3', 'mode_5', 'mode_6', 'mode_7', 'mode_8', 'mode_4'];
let _modeCycleIdx = 0;

function cycleMode(delta) {
  _modeCycleIdx = (_modeCycleIdx + delta + MODE_CYCLE.length) % MODE_CYCLE.length;
  sendAction(MODE_CYCLE[_modeCycleIdx]);
}

// ── Drive scheme button ──────────────────────────────────────────
const schemeBtn = document.getElementById('scheme-btn');

function syncSchemeButton(scheme) {
  driveScheme = scheme;
  if (!schemeBtn) return;
  schemeBtn.textContent = scheme === 'QAWS' ? '🎮 Scheme: Tank (QAWS)' : '🎮 Scheme: WASD';
  schemeBtn.classList.toggle('tank', scheme === 'QAWS');
}

if (schemeBtn) {
  schemeBtn.addEventListener('click', () => {
    const next = driveScheme === 'QAWS' ? 'WASD' : 'QAWS';
    syncSchemeButton(next);   // optimistic — don't wait on the round trip
    sendAction(next === 'QAWS' ? 'scheme_qaws' : 'scheme_wasd');
  });
}

// ── Mind panel (kida_mind via /mind) ─────────────────────────────
// Hidden until the robot answers — if the inner life isn't running
// (/mind → 503) the panel simply never appears.
const MIND_INTERVAL = 5000;

function setMindBar(id, v) {
  const el = $(id);
  if (el) el.style.width = `${Math.round(Math.max(0, Math.min(1, v || 0)) * 100)}%`;
}

async function fetchMind() {
  let s;
  try {
    const res = await fetch('/mind');
    if (!res.ok) return;
    s = await res.json();
  } catch (_) {
    return;
  }
  $('mind-panel').style.display = '';
  $('mind-mood').textContent = s.sleeping ? `${s.mood.label} — asleep 💤` : s.mood.label;
  setMindBar('mb-social', s.drives.social);
  setMindBar('mb-curiosity', s.drives.curiosity);
  setMindBar('mb-security', s.drives.security);
  setMindBar('mb-sleepy', s.drives.sleepiness);
  $('mind-memories').textContent = `${s.memories} memories · ${s.conversations} conversations`;
  $('mind-thought').textContent = s.thought ? `💭 ${s.thought}` : '';
  $('mind-body').textContent = s.body ? `⌁ body feels ${s.body.feels}` + (s.clock ? ` · ${s.clock.time}, ${s.clock.weekday}` : '') : '';
  $('mind-philosophy').textContent = s.philosophy && s.philosophy.lean ? `◈ leans ${s.philosophy.lean}` : '';
}

fetchMind();
setInterval(fetchMind, MIND_INTERVAL);

// ── Joystick (Gamepad API) ───────────────────────────────────────
// Same pad layout as the Pi/PC HUDs (scripts/joystick_drive.py): the pad
// is plugged into this computer, never the robot.
//   left stick  drive — arcade-mixed into left/right track throttle
//               (-1..1) and sent as 'joy_drive'; the robot scales it by
//               the current speed and only obeys it in KEYBOARD mode.
//               Resent every JOY_HEARTBEAT_MS while deflected, for the
//               same dead-man timeout the drive keys rely on.
//   right stick aim the servo ('servo_aim')
//   A photo  B stop  X/Y speed −/+  LB/RB mode (applied after a pause)
//   RT video  Start lock/unlock  Back LIDAR sweep
// Pads the browser reports with the 'standard' mapping (Logitech in X
// mode, Xbox, PlayStation…) get the full layout; anything else (e.g. the
// Generic USB Joystick) gets the stick + the first four buttons.
// Rumble comes from the robot's /haptics while a pad is connected.
// Browsers only expose a gamepad after a button is pressed.
const JOY_DEADZONE       = 0.08;
// 'standard' mapping button indices → action
const JOY_STD_ACTIONS = { 0: 'photo', 1: 'hard_stop', 2: 'speed_down', 3: 'speed_up', 8: 'lidar_sweep' };
const JOY_STD_LB = 4, JOY_STD_RB = 5, JOY_STD_LT = 6, JOY_STD_RT = 7, JOY_STD_START = 9;
const JOY_STD_DUP = 12, JOY_STD_DLEFT = 14, JOY_STD_DRIGHT = 15;
const JOY_TRIGGER_DZ = 0.05;
// Non-standard pads: generic stick trigger/B1/B2/B3…
const JOY_RAW_ACTIONS    = { 0: 'photo', 1: 'hard_stop', 2: 'speed_down', 3: 'speed_up' };
// …or a Logitech in D mode ("Cordless RumblePad 2"): face buttons X, A, B, Y.
const JOY_D_MODE_ACTIONS = { 1: 'photo', 2: 'hard_stop', 0: 'speed_down', 3: 'speed_up' };
const JOY_SEND_MS        = 50;
const JOY_HEARTBEAT_MS   = 250;
const JOY_MODE_COMMIT_MS = 800;
const JOY_SERVO_RANGE    = 70;
const JOY_SERVO_STEP     = 5;
const JOY_SERVO_MS       = 200;
const JOY_RUMBLE_MS      = 250;

const joyStatus = $('joy-status');
let _joyIndex       = null;
let _joySent        = [0, 0];
let _joyLastSend    = 0;
let _joyInFlight    = false;
let _joyPrevButtons = [];
let _joyStatusText  = '';
let _joyRtDown      = false;
let _joyPendingIdx  = null;
let _joyPendingAt   = 0;
let _joyServoSent   = 90;
let _joyServoAt     = 0;
let _joyRumble      = { low: 0, high: 0, reason: '' };
let _joyRumbleAt    = 0;

function joyDz(v) { return Math.abs(v) < JOY_DEADZONE ? 0 : v; }

function joyMix(turn, throttle) {
  const fwd = -joyDz(throttle);
  const t   = joyDz(turn);
  const l = fwd + t, r = fwd - t;
  const s = Math.max(1, Math.abs(l), Math.abs(r));
  return [Math.round(l / s * 100) / 100, Math.round(r / s * 100) / 100];
}

function setJoyStatus(text) {
  if (!joyStatus || text === _joyStatusText) return;
  _joyStatusText = text;
  joyStatus.textContent = text;
}

// Separate from sendAction(): that refetches /status after every call,
// which at joystick send rates would hammer the robot for nothing.
async function postJoy(body) {
  const res = await fetch('/action', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(body),
  });
  return res.ok;
}

async function postJoyDrive(l, r) {
  if (_joyInFlight) return;
  _joyInFlight = true;
  _joyLastSend = performance.now();
  try {
    if (await postJoy({ command: 'joy_drive', left: l, right: r })) _joySent = [l, r];
  } catch (_) {
    // unsent — the next tick sees the mismatch and retries
  } finally {
    _joyInFlight = false;
  }
}

function joyStepMode(delta) {
  const base = _joyPendingIdx ?? _modeCycleIdx;
  _joyPendingIdx = (base + delta + MODE_CYCLE.length) % MODE_CYCLE.length;
  _joyPendingAt  = performance.now();
}

async function pollHaptics(gp) {
  _joyRumbleAt = performance.now();
  try {
    const res = await fetch('/haptics');
    _joyRumble = await res.json();
  } catch (_) {
    _joyRumble = { low: 0, high: 0, reason: '' };
  }
  const act = gp.vibrationActuator;
  if (act && (_joyRumble.low || _joyRumble.high)) {
    act.playEffect('dual-rumble', {
      duration: JOY_RUMBLE_MS + 150,
      strongMagnitude: _joyRumble.low,
      weakMagnitude:   _joyRumble.high,
    }).catch(() => {});
  }
}

function joyTick(now) {
  requestAnimationFrame(joyTick);

  // No stick, or the window isn't focused (browsers freeze gamepad values
  // for unfocused pages, so a held stick would keep resending forever):
  // treat as centred, which sends one stop if we were moving.
  let l = 0, r = 0;
  const gp = _joyIndex !== null ? navigator.getGamepads()[_joyIndex] : null;
  if (gp && document.hasFocus()) {
    const std = gp.mapping === 'standard';
    // Tank scheme (the same Scheme toggle the keyboard uses): LT/RT drive the
    // left/right track, analog; hold LB/RB to reverse that side.
    const tank = std && driveScheme === 'QAWS';
    const actions = std ? JOY_STD_ACTIONS
                  : /rumblepad/i.test(gp.id) ? JOY_D_MODE_ACTIONS : JOY_RAW_ACTIONS;
    gp.buttons.forEach((b, i) => {
      if (b.pressed && !_joyPrevButtons[i]) {
        if (actions[i]) sendAction(actions[i]);
        else if (std && i === JOY_STD_DLEFT) joyStepMode(-1);
        else if (std && i === JOY_STD_DRIGHT) joyStepMode(1);
        else if (std && !tank && i === JOY_STD_LB) joyStepMode(-1);
        else if (std && !tank && i === JOY_STD_RB) joyStepMode(1);
        else if (std && i === JOY_STD_DUP) sendAction('video_toggle');
        else if (std && i === JOY_STD_START) toggleLock();
      }
      _joyPrevButtons[i] = b.pressed;
    });

    if (std && !tank) {   // in tank mode RT is the right track
      const rt = gp.buttons[JOY_STD_RT]?.value ?? 0;
      if (!_joyRtDown && rt > 0.6) { _joyRtDown = true; sendAction('video_toggle'); }
      else if (_joyRtDown && rt < 0.3) _joyRtDown = false;
    }
    if (std) {
      const angle = Math.round((90 + joyDz(gp.axes[2] ?? 0) * JOY_SERVO_RANGE) / JOY_SERVO_STEP) * JOY_SERVO_STEP;
      if (angle !== _joyServoSent && now - _joyServoAt >= JOY_SERVO_MS) {
        _joyServoSent = angle;
        _joyServoAt   = now;
        postJoy({ command: 'servo_aim', angle }).catch(() => {});
      }
    }

    if (_joyPendingIdx !== null && now - _joyPendingAt >= JOY_MODE_COMMIT_MS) {
      _modeCycleIdx  = _joyPendingIdx;
      _joyPendingIdx = null;
      sendAction(MODE_CYCLE[_modeCycleIdx]);
    }

    if (now - _joyRumbleAt >= JOY_RUMBLE_MS) pollHaptics(gp);

    if (tank) {
      const side = (trig, bumper) => {
        const v = (gp.buttons[trig]?.value ?? 0) < JOY_TRIGGER_DZ ? 0 : Math.min(1, gp.buttons[trig].value);
        return Math.round((gp.buttons[bumper]?.pressed ? -v : v) * 100) / 100;
      };
      l = side(JOY_STD_LT, JOY_STD_LB);
      r = side(JOY_STD_RT, JOY_STD_RB);
    } else {
      [l, r] = joyMix(gp.axes[0] ?? 0, gp.axes[1] ?? 0);
    }
    let text = `🕹️ ${gp.id.slice(0, 32)} — L ${l.toFixed(2)}  R ${r.toFixed(2)}`;
    if (_joyPendingIdx !== null) text += `  → ${MODE_CYCLE[_joyPendingIdx].replace('_', ' ')}…`;
    if (_joyRumble.reason) text += `  📳 ${_joyRumble.reason}`;
    setJoyStatus(text);
  } else if (gp) {
    setJoyStatus(`🕹️ ${gp.id.slice(0, 32)} — paused (window not focused)`);
  }

  if (now - _joyLastSend < JOY_SEND_MS) return;
  const changed = l !== _joySent[0] || r !== _joySent[1];
  const moving  = l !== 0 || r !== 0;
  if (changed || (moving && now - _joyLastSend >= JOY_HEARTBEAT_MS)) postJoyDrive(l, r);
}

window.addEventListener('gamepadconnected', (e) => {
  if (_joyIndex === null) {
    _joyIndex = e.gamepad.index;
    _joyPrevButtons = e.gamepad.buttons.map((b) => b.pressed);
  }
});

window.addEventListener('gamepaddisconnected', (e) => {
  if (e.gamepad.index !== _joyIndex) return;
  _joyIndex = null;
  _joyPendingIdx = null;
  setJoyStatus('No joystick — plug one in and press a button');
});

requestAnimationFrame(joyTick);
