let credential = '';
let snapshot = null;
const $ = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const date = value => new Date(value * 1000).toLocaleString();
async function api(path, body) {
  const response = await fetch('/api/' + path, {method: body === undefined ? 'GET' : 'POST', headers: {'Authorization':'Bearer '+credential,'Content-Type':'application/json'}, ...(body === undefined ? {} : {body:JSON.stringify(body)})});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
function notify(message) { $('notice').textContent = message; }
function render() {
  if (!snapshot) return;
  const active = snapshot.devices.filter(d => !d.revoked);
  const online = active.filter(d => snapshot.time - d.seen < 90);
  $('total').textContent = snapshot.fleet.active;
  $('online').textContent = snapshot.fleet.online;
  $('offline').textContent = snapshot.fleet.active - snapshot.fleet.online;
  $('pending').textContent = snapshot.pending;
  $('count').textContent = `${snapshot.devices.length} of ${snapshot.fleet.records}`;
  const term = $('search').value.toLowerCase();
  const devices = snapshot.devices.filter(d => (d.inventory.hostname+' '+d.inventory.os).toLowerCase().includes(term));
  $('empty').hidden = snapshot.devices.length > 0;
  $('device-rows').innerHTML = devices.map(d => {
    const inv = d.inventory;
    const connected = !d.revoked && snapshot.time - d.seen < 90;
    return `<tr><td><strong>${escape(inv.hostname)}</strong><small>${escape(d.id)}</small></td><td><span class="badge ${connected?'green':''}">${d.revoked?'Revoked':connected?'Connected':'Offline'}</span></td><td>${escape(inv.os)}<small>${escape(inv.version)} · ${escape(inv.architecture)}</small></td><td>${escape(inv.privilege)}<small>Self-reported</small></td><td>${escape(date(d.seen))}</td><td>${d.revoked?'Access removed':`<button data-refresh="${escape(d.id)}">Refresh inventory</button><button data-revoke="${escape(d.id)}">Revoke</button>`}</td></tr>`;
  }).join('') || (snapshot.devices.length ? '<tr><td colspan="6">No devices match your search.</td></tr>' : '');
  $('job-list').innerHTML = snapshot.jobs.map(j => `<div class="event"><div><strong>Inventory refresh</strong><p>${escape(j.device)} · ${escape(j.result || 'Awaiting agent result')}</p></div><div><span class="badge ${j.status==='completed'?'green':''}">${escape(j.status)}</span><p>${escape(date(j.created))}</p></div></div>`).join('') || '<p>No device actions yet. Request an inventory refresh from Devices.</p>';
  $('audit-list').innerHTML = snapshot.audit.map(a => `<div class="event"><div><strong>${escape(a.action.replaceAll('.',' '))}</strong><p>${escape(a.actor)} → ${escape(a.target)}</p></div><small>${escape(date(a.time))}</small></div>`).join('') || '<p>No audit events yet. Enroll your first device to begin.</p>';
}
async function refresh() {
  const current = credential;
  const next = await api('dashboard');
  if (!current || credential !== current) return;
  snapshot = next;
  render();
}
$('login-form').addEventListener('submit', async event => {
  event.preventDefault();
  const token = $('token').value.trim();
  if (!/^[A-Za-z0-9_-]{32,128}$/.test(token)) {
    credential = '';
    notify('Paste the token file contents, not the file path or masked dots. On your Mac, run the copy command shown above, then paste here.');
    $('token').focus();
    return;
  }
  credential = token;
  try { await refresh(); $('token').value=''; $('login').hidden=true; $('content').hidden=false; $('lock').hidden=false; $('enroll').disabled=false; notify(''); }
  catch(error) { credential=''; notify(error.message); }
});
$('lock').onclick = () => location.reload();
$('search').oninput = render;
async function enroll() {
  try { const result = await api('enrollments',{}); $('enrollment-token').value=result.token; $('enrollment').showModal(); await refresh(); }
  catch(error) { notify(error.message); }
}
$('enroll').onclick = enroll;
$('empty-enroll').onclick = enroll;
$('enrollment').addEventListener('close', () => { $('enrollment-token').value=''; });
document.querySelectorAll('[data-view]').forEach(button => button.onclick = () => {
  document.querySelectorAll('[data-view]').forEach(b => b.classList.toggle('active', b===button));
  document.querySelectorAll('.view').forEach(view => view.hidden = view.id!==button.dataset.view);
  $('breadcrumb').textContent = ['tokens','history','health'].includes(button.dataset.view) ? button.textContent.trim() : button.textContent.slice(1).trim();
  if (button.dataset.view==='history' && credential) loadHistory(true).catch(error => notify(error.message));
  if (button.dataset.view==='health' && credential) loadHealth().catch(error => notify(error.message));
  if (button.dataset.view==='tokens' && credential) loadEnrollments().catch(error => notify(error.message));
});
$('device-rows').onclick = async event => {
  const button = event.target.closest('button');
  if (!button) return;
  const revoke = button.dataset.revoke;
  if (revoke && !confirm('Revoke this device? Further check-ins will be rejected and pending jobs cancelled. Re-enrollment requires a new token.')) return;
  button.disabled=true;
  try { await api(revoke?'revoke':'jobs',{device:revoke || button.dataset.refresh}); await refresh(); notify(revoke?'Device access revoked.':'Inventory refresh queued. The agent will pick it up on its next check-in.'); }
  catch(error) { notify(error.message); button.disabled=false; }
};
setInterval(() => { if (credential) refresh().catch(error => notify('Dashboard could not refresh: '+error.message)); },10000);

async function loadEnrollments() {
  const result = await api('enrollments');
  $('token-list').innerHTML = result.enrollments.map(item => `<div class="event"><div><strong>${escape(item.id.slice(0,12))}</strong><p>Expires ${escape(date(item.expires))}</p></div><div><span class="badge ${item.status==='active'?'green':''}">${escape(item.status)}</span> ${item.status==='active'?`<button data-token-revoke="${escape(item.id)}">Revoke token</button>`:''}</div></div>`).join('') || '<p>No enrollment tokens issued yet. Select Enroll device to create one.</p>';
}
$('tokens-refresh').onclick = () => loadEnrollments().catch(error => notify(error.message));
$('token-list').onclick = async event => {
  const button = event.target.closest('[data-token-revoke]');
  if (!button) return;
  button.disabled = true;
  try {
    await api('enrollments/revoke',{id:button.dataset.tokenRevoke});
    await loadEnrollments();
    await refresh();
    notify('Enrollment token revoked. Existing device access is unchanged.');
  } catch (error) { notify(error.message); button.disabled=false; }
};

let historyCursor = null;
let historyBusy = false;
async function loadHistory(reset) {
  if (historyBusy) return;
  historyBusy = true;
  $('history-kind').disabled = true;
  $('history-more').disabled = true;
  $('history-reload').disabled = true;
  try {
    const kind = $('history-kind').value;
    const result = await api(`history?kind=${encodeURIComponent(kind)}&limit=50${!reset && historyCursor ? '&cursor='+historyCursor : ''}`);
    const entries = result.items.map(item => {
      let title, detail, timestamp;
      if (kind==='devices') { title=item.inventory.hostname; detail=`${item.inventory.os} · ${item.revoked?'Revoked':'Enrolled'} · ${item.id}`; timestamp=item.seen; }
      else if (kind==='jobs') { title=item.kind; detail=`${item.status} · ${item.device} · ${item.result || 'Awaiting result'}`; timestamp=item.created; }
      else if (kind==='enrollments') { title=`Token ${item.id.slice(0,12)}`; detail=item.status; timestamp=item.expires; }
      else { title=item.action; detail=`${item.actor} → ${item.target}`; timestamp=item.time; }
      return `<div class="event"><div><strong>${escape(title)}</strong><p>${escape(detail)}</p></div><small>${kind==='enrollments'?'Expires ':''}${escape(date(timestamp))}</small></div>`;
    }).join('');
    if (reset) $('history-list').innerHTML = entries || '<p>No records.</p>';
    else $('history-list').insertAdjacentHTML('beforeend',entries);
    historyCursor=result.next_cursor;
  } finally {
    historyBusy=false;
    $('history-kind').disabled=false;
    $('history-more').disabled=!historyCursor;
    $('history-reload').disabled=false;
  }
}
$('history-kind').onchange=()=>loadHistory(true).catch(error=>notify(error.message));
$('history-reload').onclick=()=>loadHistory(true).catch(error=>notify(error.message));
$('history-more').onclick=()=>loadHistory(false).catch(error=>notify(error.message));
async function loadHealth() {
  const result=await api('health');
  $('health-output').textContent=`Status: ${result.status}. Database: ${result.database}. Schema: ${result.schema_version}. Uptime: ${result.uptime_seconds} seconds. Records: ${result.counts.devices} devices, ${result.counts.jobs} jobs, ${result.counts.enrollments} enrollment tokens, ${result.counts.audit} audit events.`;
}
$('health-refresh').onclick=()=>loadHealth().catch(error=>notify(error.message));
