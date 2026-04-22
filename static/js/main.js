// main.js — KIDA web HUD live updater
// Polls /status every 2 seconds and updates status strip + sensor grid in-place.

const STATUS_INTERVAL = 2000;

const MODE_COLORS = {
  KEYBOARD:   'mode-KEYBOARD',
  IR_REMOTE:  'mode-IR_REMOTE',
  AUTONOMOUS: 'mode-AUTONOMOUS',
  IDLE:       'mode-IDLE',
};

function $(id) { return document.getElementById(id); }

function applyStatus(data) {
  // Status strip
  $('st-spd').textContent  = `Spd:${data.motor_speed ?? '—'}`;
  $('st-temp').textContent = `T:${data.cpu_temp ?? '—'}`;
  $('st-cpu').textContent  = `CPU:${data.cpu ?? '—'}%`;
  $('st-ram').textContent  = `RAM:${data.ram ?? '—'}%`;
  $('st-ip').textContent   = `IP:${data.ip ?? '—'}`;
  $('st-inf').textContent  = `Inf:${data.inference_on ? 'ON' : 'off'}`;

  const modeBadge = $('st-mode');
  modeBadge.textContent = `[${data.mode ?? '—'}]`;
  modeBadge.className = 'mode-badge ' + (MODE_COLORS[data.mode] || '');

  // Sensors
  const sensors = data.sensors || {};
  for (const [label, value] of Object.entries(sensors)) {
    const el = document.getElementById(`s-${label}`);
    if (el) el.textContent = value ?? '—';
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
