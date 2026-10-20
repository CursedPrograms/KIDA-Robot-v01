// options.js — her options page: config.json as folding sections, saved with her PIN
// (GET / POST /options.json, server.py). options_choices.json's lists become drop-downs.

let saved = null;     // config.json as loaded
let data = null;      // what's being edited
let choices = {};

function $(id) { return document.getElementById(id); }

function nice(key) {
  return String(key).replace(/([a-z])([A-Z])/g, '$1 $2').replace(/_/g, ' ');
}

function get(obj, path) { return path.reduce((o, k) => (o == null ? o : o[k]), obj); }

function set(path, value) {
  const parent = get(data, path.slice(0, -1));
  parent[path[path.length - 1]] = value;
}

function mark(row, path) {
  row.classList.toggle('changed', JSON.stringify(get(data, path)) !== JSON.stringify(get(saved, path)));
}

function field(key, value, path) {
  const row = document.createElement('div');
  row.className = 'row';
  const label = document.createElement('label');
  label.textContent = nice(key);
  row.appendChild(label);

  const opts = choices[path.join('/')];
  let input;
  if (opts) {
    input = document.createElement('select');
    opts.forEach((o) => {
      const op = document.createElement('option');
      op.value = JSON.stringify(o);
      op.textContent = String(o);
      input.appendChild(op);
    });
    input.value = JSON.stringify(value);
    input.addEventListener('change', () => { set(path, JSON.parse(input.value)); mark(row, path); });
  } else if (typeof value === 'boolean') {
    input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = value;
    input.addEventListener('change', () => { set(path, input.checked); mark(row, path); });
  } else if (typeof value === 'number') {
    input = document.createElement('input');
    input.type = 'number';
    input.step = Number.isInteger(value) ? '1' : 'any';
    input.value = value;
    input.addEventListener('input', () => {
      const n = Number(input.value);
      if (input.value !== '' && !Number.isNaN(n)) { set(path, n); mark(row, path); }
    });
  } else {
    input = document.createElement('input');
    input.type = 'text';
    const isText = typeof value === 'string';
    input.value = isText ? value : JSON.stringify(value);
    input.addEventListener('input', () => {
      if (isText) { set(path, input.value); mark(row, path); return; }
      try { set(path, JSON.parse(input.value)); mark(row, path); input.style.borderColor = ''; }
      catch (_) { input.style.borderColor = 'var(--red)'; }
    });
  }
  input.id = 'f-' + path.join('-');
  label.htmlFor = input.id;
  row.appendChild(input);
  return row;
}

function isSection(v) {
  return v && typeof v === 'object' && !(Array.isArray(v) && v.every((x) => typeof x !== 'object'));
}

function build(obj, path) {
  const frag = document.createDocumentFragment();
  Object.keys(obj).forEach((key) => {
    const v = obj[key];
    const p = path.concat([key]);
    if (isSection(v)) {
      const d = document.createElement('details');
      d.open = path.length < 2;
      const s = document.createElement('summary');
      s.textContent = nice(key);
      d.appendChild(s);
      d.appendChild(build(v, p));
      frag.appendChild(d);
    } else {
      frag.appendChild(field(key, v, p));
    }
  });
  return frag;
}

function render() {
  const tree = $('tree');
  tree.textContent = '';
  tree.appendChild(build(data, []));
}

function say(text, ok) {
  const m = $('msg');
  m.textContent = text;
  m.className = ok ? 'ok' : 'err';
}

async function load() {
  try {
    const r = await fetch('/options.json');
    const j = await r.json();
    saved = j.config || {};
    choices = j.choices || {};
    data = JSON.parse(JSON.stringify(saved));
    render();
  } catch (e) {
    $('tree').textContent = 'Can’t read her options: ' + e;
  }
}

$('save').addEventListener('click', async () => {
  try {
    const r = await fetch('/options.json', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: $('pin').value, config: data }),
    });
    const j = await r.json();
    if (!j.ok) { say(j.error || 'not saved', false); return; }
    saved = JSON.parse(JSON.stringify(data));
    render();
    say('Saved. Restart her for most of it to take effect.', true);
  } catch (e) {
    say('Not saved: ' + e, false);
  }
});

$('revert').addEventListener('click', () => {
  data = JSON.parse(JSON.stringify(saved));
  render();
  say('Back to what she has.', true);
});

load();
