// main.js — KIDA web HUD live updater

const STATUS_INTERVAL = 2000;

const MODE_COLORS = {
  KEYBOARD:      'mode-KEYBOARD',
  IR_REMOTE:     'mode-IR_REMOTE',
  AUTONOMOUS:    'mode-AUTONOMOUS',
  LINE_FOLLOWER: 'mode-LINE_FOLLOWER',
  WATCHDOG:      'mode-WATCHDOG',
  LANE_DETECT:   'mode-LANE_DETECT',
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

function pressDrive(channelName, cmd) {
  const ch = _driveChannels[channelName];
  if (!ch.stack.includes(cmd)) ch.stack.push(cmd);
  sendAction(cmd);
  if (!ch.timer) {
    ch.timer = setInterval(() => {
      if (ch.stack.length) sendAction(ch.stack[ch.stack.length - 1]);
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
    sendAction(ch.stack[ch.stack.length - 1]);
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
const MODE_CYCLE = ['mode_1', 'mode_2', 'mode_3', 'mode_5', 'mode_6', 'mode_4'];
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
