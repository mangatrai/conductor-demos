// v2 chat page: plain JS, no build. The page only keeps a pointer (sessionId + last good executionId);
// the conversation itself lives in Conductor, in the output of the last completed workflow run.
const $ = (id) => document.getElementById(id);
let cfg = { version: 'v2' };
let api = { base: 'api', headers: {} };   // same-origin front door, or the Orkes API Gateway (config.local.json)
let state = { sessionId: '', executionId: '' };
let modelChanged = false;

const key = () => 'convo:' + cfg.version;   // keyed by version: two versions never share a session
const save = () => localStorage.setItem(key(), JSON.stringify(state));

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

async function call(path, opts = {}) {
  const r = await fetch(api.base + path, { ...opts, headers: { ...api.headers, ...(opts.headers || {}) } });
  let body = {};
  try { body = await r.json(); } catch (_) { body = { error: 'HTTP ' + r.status }; }
  if (!r.ok) throw new Error(body.error || 'HTTP ' + r.status);
  return body;
}

function scroll() { const m = document.querySelector('main'); m.scrollTop = m.scrollHeight; }

function addMsg(role, text, steps) {
  const m = el('div', 'msg ' + role, text);
  if (steps && steps.length) {
    const d = el('details', 'steps');
    d.appendChild(el('summary', null, 'what Conductor did (' + steps.length + ' steps)'));
    const ul = el('ul');
    steps.forEach((s) => ul.appendChild(el('li', null, `${s.ref} · ${s.type} · ${s.ms} ms`)));
    d.appendChild(ul);
    m.appendChild(d);
  }
  $('messages').appendChild(m);
  scroll();
  return m;
}

function addError(text, retry) {
  const m = el('div', 'msg error', text);
  const b = el('button', null, 'Retry');
  b.type = 'button';
  b.onclick = () => { m.remove(); retry(); };
  m.appendChild(b);
  $('messages').appendChild(m);
  scroll();
}

function setLinks(execUrl, sessionUrl) {
  for (const [id, url] of [['exec-link', execUrl], ['session-link', sessionUrl]]) {
    if (url) { $(id).href = url; $(id).hidden = false; }
  }
}

function toast(text) {
  $('toast').textContent = text;
  $('toast').hidden = false;
  setTimeout(() => { $('toast').hidden = true; }, 4000);
}

function newChat() {
  state = { sessionId: crypto.randomUUID(), executionId: '' };
  save();
  $('messages').innerHTML = '';
  $('resume-banner').hidden = true;
  $('exec-link').hidden = true;
  $('session-link').hidden = true;
  $('starters').hidden = false;
}

function busy(on) {
  $('send').disabled = on;
  $('input').disabled = on;
  $('typing').hidden = !on;
}

async function send(text) {
  text = (text || '').trim();
  if (!text) return;
  if (!state.sessionId) newChat();
  $('starters').hidden = true;
  addMsg('user', text);
  await turn(text);
}

async function turn(text) {
  const body = { sessionId: state.sessionId, prevExecutionId: state.executionId || '', message: text };
  if (modelChanged) body.model = $('model').value;
  busy(true);
  try {
    const r = await call('/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    state.executionId = r.executionId;   // only a completed turn moves the pointer
    save();
    addMsg('bot', r.reply, r.steps);
    setLinks(r.uiUrl, r.sessionUrl);
  } catch (e) {
    addError('⚠ ' + e.message, () => turn(text));   // retry with the same, unchanged pointer
  } finally {
    busy(false);
    $('input').focus();
  }
}

async function resume() {
  $('resume-banner').hidden = true;
  try {
    const q = new URLSearchParams({ sessionId: state.sessionId, executionId: state.executionId });
    const r = await call('/session?' + q);
    if (!r.found) throw new Error('not found');
    $('messages').innerHTML = '';
    $('starters').hidden = true;
    r.history.forEach((h) => addMsg(h.role === 'user' ? 'user' : 'bot', h.message));
    setLinks(r.uiUrl, r.sessionUrl);
  } catch (_) {
    toast("Couldn't restore — starting fresh");
    newChat();
  }
}

async function init() {
  try {   // optional: talk to the Orkes API Gateway instead of the local front door
    const r = await fetch('config.local.json');
    if (r.ok) {
      const loc = await r.json();
      if (loc.apiBase) api = { base: loc.apiBase.replace(/\/$/, ''), headers: loc.apiKey ? { 'X-API-KEY': loc.apiKey } : {} };
    }
  } catch (_) { /* no local gateway config */ }
  try { cfg = await (await fetch('api/config')).json(); } catch (_) { /* keep defaults */ }

  document.title = cfg.title || document.title;
  $('title').textContent = cfg.title || 'Wealth advisor chat';
  $('version').textContent = cfg.version;
  (cfg.features || []).forEach((f) => $('features').appendChild(el('span', 'chip', f)));
  (cfg.models || [cfg.model]).filter(Boolean).forEach((m) => {
    const o = el('option', null, m); o.value = m; $('model').appendChild(o);
  });
  if (cfg.model) $('model').value = cfg.model;
  (cfg.starters || []).forEach((s) => {
    const b = el('button', 'starter', s); b.type = 'button'; b.onclick = () => send(s);
    $('starters').appendChild(b);
  });

  $('model').onchange = () => { modelChanged = true; };
  $('composer').onsubmit = (e) => { e.preventDefault(); const t = $('input').value; $('input').value = ''; send(t); };
  $('new-chat').onclick = newChat;
  $('resume-new').onclick = newChat;
  $('resume-continue').onclick = resume;

  try { state = JSON.parse(localStorage.getItem(key())) || state; } catch (_) { /* fresh */ }
  if (state.sessionId && state.executionId) $('resume-banner').hidden = false;
  else newChat();
}

init();
