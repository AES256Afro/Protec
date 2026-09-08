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
  $('total').textContent = active.length;
  $('online').textContent = online.length;
  $('offline').textContent = active.length - online.length;
  $('pending').textContent = snapshot.pending;
  $('count').textContent = snapshot.devices.length;
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
  event.preventDefault(); credential = $('token').value.trim();
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
  $('breadcrumb').textContent = button.textContent.slice(1).trim();
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
