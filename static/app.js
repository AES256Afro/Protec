let credential = '';
let snapshot = null;
const $ = id => document.getElementById(id);
const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const date = value => new Date(value * 1000).toLocaleString();
async function api(path, body) {
  if (globalThis.protecDemo) return globalThis.protecDemo.request(path,body);
  const response = await fetch('/api/' + path, {method: body === undefined ? 'GET' : 'POST', headers: {'Authorization':'Bearer '+credential,'Content-Type':'application/json'}, ...(body === undefined ? {} : {body:JSON.stringify(body)})});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Request failed');
  return data;
}
const can = permission => snapshot?.identity?.permissions.includes(permission) || false;
function notify(message) { $('notice').textContent = message; }
function cancelJobButton(job) {
  return can('jobs.write') && ['queued','running'].includes(job.status) ? `<button data-cancel-job="${escape(job.id)}">${job.kind==='preview_packages'?'Cancel preview':'Cancel refresh'}</button>` : '';
}
const canSchedule = () => can('jobs.write') && snapshot?.job_windows === 1;
const pendingRefresh = device => snapshot?.jobs.some(job => job.device === device && ['queued','running'].includes(job.status));
function jobWindow(job) {
  return job.not_before == null ? '' : `<p>Window (local time): ${escape(date(job.not_before))} to ${escape(date(job.not_after))}</p>`;
}
function jobReceipt(job) {
  const receipt=job.receipt;
  if(!receipt) return `<p>${job.status==='completed'?'Legacy completion; no receipt recorded':['failed','cancelled'].includes(job.status)?'No completion receipt recorded':job.contract_version?'Awaiting completion receipt':job.attempt?'Legacy agent; no completion receipt':'Awaiting agent delivery'}</p>`;
  return `<details><summary>Completion receipt</summary><p>Attempt ${escape(receipt.attempt)} · Recorded ${escape(date(receipt.recorded_at))}</p><p>${receipt.kind==='preview_packages'?'Result':'Inventory'} SHA-256: <code class="receipt-digest">${escape(receipt.inventory_sha256||receipt.result_sha256)}</code></p></details>`;
}
function render() {
  if (!snapshot) return;
  $('identity-label').textContent = `${snapshot.identity.name} · ${snapshot.identity.role} · ${snapshot.identity.device_ids ? snapshot.identity.device_ids.length+' selected devices' : 'Whole fleet'}`;
  document.querySelector('[data-view="policies"]').hidden = snapshot.policy_management !== 1 || !can('policies.read');
  $('enroll').disabled = !can('enrollments.write');
  $('empty-enroll').hidden = !can('enrollments.write');
  for (const [view,permission] of [['tokens','enrollments.read'],['audit','audit.read'],['access','credentials.read'],['health','health.read']]) {
    document.querySelector(`[data-view="${view}"]`).hidden = !can(permission);
  }
  for (const [kind,permission] of [['audit','audit.read'],['enrollments','enrollments.read']]) {
    document.querySelector(`#history-kind option[value="${kind}"]`).disabled = !can(permission);
  }
  if (!can('audit.read') && ['audit','enrollments'].includes($('history-kind').value)) $('history-kind').value='devices';
  $('fleet-label').textContent = snapshot.identity.device_ids ? 'Enrolled devices in scope' : 'Enrolled devices';
  const selections=new Set(Array.from($('access-devices').selectedOptions || [],option=>option.value));
  $('access-devices').innerHTML=snapshot.devices.filter(device=>!device.revoked).map(device=>`<option value="${escape(device.id)}" ${selections.has(device.id)?'selected':''}>${escape(device.inventory.hostname)} · ${escape(device.id)}</option>`).join('');
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
    return `<tr><td><strong>${escape(inv.hostname)}</strong><small>${escape(d.id)}</small></td><td><span class="badge ${connected?'green':''}">${d.revoked?'Revoked':connected?'Connected':'Offline'}</span></td><td>${escape(inv.os)}<small>${escape(inv.version)} · ${escape(inv.architecture)}</small></td><td>${escape(inv.privilege)}<small>Self-reported</small></td><td>${escape(date(d.seen))}</td><td>${d.revoked?'Access removed':`<button data-packages="${escape(d.id)}">Packages</button>${can('jobs.write')?`<button data-refresh="${escape(d.id)}">Refresh inventory</button>${canSchedule()?`<button data-schedule="${escape(d.id)}" ${pendingRefresh(d.id)?'disabled title="An inventory refresh is already pending"':''}>Schedule refresh</button>`:''}`:''}${can('devices.revoke')?`<button data-revoke="${escape(d.id)}">Revoke</button>`:''}`}</td></tr>`;
  }).join('') || (snapshot.devices.length ? '<tr><td colspan="6">No devices match your search.</td></tr>' : '');
  $('job-list').innerHTML = snapshot.jobs.map(j => `<div class="event"><div><strong>${j.kind==='preview_packages'?'Package change preview':'Inventory refresh'}</strong><p>${escape(j.device)} · ${escape(j.result || 'Awaiting agent result')}</p><p>Delivery attempts: ${escape(j.attempt ?? 0)} of 3</p>${jobWindow(j)}${jobReceipt(j)}${packagePlan(j)}${cancelJobButton(j)}</div><div><span class="badge ${j.status==='completed'&&j.preview?.outcome!=='unavailable'?'green':''}">${escape(j.preview?.outcome==='unavailable'?'unavailable':j.status)}</span><p>${escape(date(j.created))}</p></div></div>`).join('') || '<p>No device actions yet. Request an inventory refresh from Devices.</p>';
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
    notify('Paste the token file contents, not the file path or masked dots. Use your deployment’s token retrieval instructions, then paste here.');
    $('token').focus();
    return;
  }
  credential = token;
  try { await refresh(); $('token').value=''; $('login').hidden=true; $('content').hidden=false; $('lock').hidden=false; notify(''); }
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
  $('breadcrumb').textContent = ['tokens','history','health','access','policies'].includes(button.dataset.view) ? button.textContent.trim() : button.textContent.slice(1).trim();
  if (button.dataset.view==='policies' && credential) loadPolicies().catch(error => notify(error.message));
  if (button.dataset.view==='access' && credential) loadAccess().catch(error => notify(error.message));
  if (button.dataset.view==='history' && credential) loadHistory(true).catch(error => notify(error.message));
  if (button.dataset.view==='health' && credential) loadHealth().catch(error => notify(error.message));
  if (button.dataset.view==='tokens' && credential) loadEnrollments().catch(error => notify(error.message));
});
$('device-rows').onclick = async event => {
  const button = event.target.closest('button');
  if (!button) return;
  if (button.dataset.packages) { showPackages(button.dataset.packages); return; }
  if (button.dataset.schedule) { openSchedule(button.dataset.schedule); return; }
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
      return `<div class="event"><div><strong>${escape(title)}</strong><p>${escape(detail)}</p>${kind==='jobs'?jobWindow(item)+jobReceipt(item)+cancelJobButton(item):''}</div><small>${kind==='enrollments'?'Expires ':''}${escape(date(timestamp))}</small></div>`;
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
  $('health-output').textContent=`Version: ${result.version || 'not reported'}. Status: ${result.status}. Database: ${result.database}. Schema: ${result.schema_version}. Uptime: ${result.uptime_seconds} seconds. Records: ${result.counts.devices} devices, ${result.counts.jobs} jobs, ${result.counts.enrollments} enrollment tokens, ${result.counts.audit} audit events.`;
}
$('health-refresh').onclick=()=>loadHealth().catch(error=>notify(error.message));

let packageItems=[];
let previewDevice=null;
function showPackages(deviceId) {
  const device=snapshot.devices.find(item=>item.id===deviceId);
  if (!device) return;
  previewDevice=deviceId;
  $('package-preview-form').hidden=!(can('jobs.write') && snapshot.package_previews===1 && device.inventory.apt_preview===1 && !device.revoked);
  $('package-preview-error').textContent='';$('package-name').value='';$('package-version').value='';
  $('package-title').textContent=`Packages on ${device.inventory.hostname}`;
  const report=device.inventory.packages;
  packageItems=report?.items || [];
  $('package-search').value='';
  $('package-summary').textContent=report ? `${report.scope}. Status: ${report.status}${snapshot.time-report.collected_at>900?' (stale)':''}. Collected ${date(report.collected_at)}. Showing ${packageItems.length} of ${report.total}${report.truncated?' (limited report)':''}. ${report.message}.` : 'No package report yet. Update the foreground agent and request an inventory refresh.';
  renderPackages();
  $('packages-dialog').showModal();
}
function renderPackages() {
  const search=$('package-search').value.toLowerCase();
  $('package-list').innerHTML=packageItems.filter(item=>item.name.toLowerCase().includes(search)).map(item=>`<div class="event"><strong>${escape(item.name)}</strong><span>${escape(item.version)}</span></div>`).join('') || '<p>No matching package records.</p>';
}
$('package-search').oninput=renderPackages;

let accessCursor=null;
let accessBusy=false;
async function loadAccess(reset=true) {
  if(accessBusy) return;
  accessBusy=true;
  $('access-more').disabled=true;
  try {
  const result=await api('credentials'+(!reset && accessCursor?'?cursor='+accessCursor:''));
  const entries=result.credentials.map(item=>`<div class="event"><div><strong>${escape(item.name)}</strong><p>${escape(item.role)} · ${item.device_ids?escape(item.device_ids.length+' selected devices: '+item.device_ids.join(', ')):'Whole fleet'} · Expires ${escape(date(item.expires))}</p><p>${escape(item.id)}</p>${item.replacement_id?`<p>Replacement ${escape(item.replacement_id)} · Handover deadline ${escape(date(item.rotation_deadline))}</p>`:''}</div><div><span class="badge ${item.status==='active'?'green':''}">${escape(item.status)}</span> ${item.status==='active'?`<button data-access-action="rotate" data-access-id="${escape(item.id)}">Rotate credential</button>`:''} ${['rotating','rotated'].includes(item.status)?`<button data-access-action="rotation/finish" data-access-id="${escape(item.id)}">Finish handover</button>`:''} ${item.status==='rotating'?`<button data-access-action="rotation/cancel" data-access-id="${escape(item.id)}">Cancel handover</button>`:''} ${['active','rotating','rotated'].includes(item.status)?`<button data-access-action="revoke" data-access-id="${escape(item.id)}">${item.replacement_id?'Revoke both credentials':'Revoke credential'}</button>`:''}</div></div>`).join('');
  if(reset) $('access-list').innerHTML=entries || '<p>No service credentials issued. Your local administrator token remains available in its protected file.</p>';
  else $('access-list').insertAdjacentHTML('beforeend',entries);
  accessCursor=result.next_cursor;
  } finally {accessBusy=false;$('access-more').disabled=!accessCursor;}
}
$('access-more').onclick=()=>loadAccess(false).catch(error=>notify(error.message));
$('access-form').addEventListener('submit',async event=>{
  event.preventDefault();
  const button=$('access-create');
  button.disabled=true;
  try {
    const result=await api('credentials',{name:$('access-name').value.trim(),role:$('access-role').value,hours:Number($('access-hours').value),device_ids:$('access-scope').value==='selected'?Array.from($('access-devices').selectedOptions,option=>option.value):null});
    $('issued-access').value=result.token;
    $('issued-access-description').textContent=`${result.name} · ${result.role} · ${result.device_ids?result.device_ids.length+' selected devices':'Whole fleet'} · Expires ${date(result.expires)}. Save this credential securely. Closing this dialog clears its value from the page.`;
    $('access-dialog').showModal();
    $('access-name').value='';
    await loadAccess();
    await refresh();
  } catch(error) {notify(error.message);}
  finally {button.disabled=false;}
});
$('access-dialog').addEventListener('close',()=>{$('issued-access').value='';});
$('access-list').onclick=async event=>{
  const button=event.target.closest('[data-access-action]');
  if (!button) return;
  const action=button.dataset.accessAction;
  const messages={
    rotate:'Create a replacement with the same role, device scope and expiry? The old token will stop working in at most 15 minutes. Save the replacement before finishing the handover. You can cancel before the deadline if the response is lost.',
    'rotation/finish':'Have you saved and tested the replacement token? Finish the handover and immediately invalidate the old token?',
    'rotation/cancel':'Invalidate the replacement and keep the original token until its original expiry?',
    revoke:'Revoke this credential? An unfinished handover also revokes its replacement. Subsequent requests will be rejected.'
  };
  if (!confirm(messages[action])) return;
  button.disabled=true;
  try {
    const result=await api('credentials/'+action,{id:button.dataset.accessId});
    if(action==='rotate') {
      $('issued-access').value=result.token;
      $('issued-access-description').textContent=`Replacement for ${result.replaces}. Same ${result.role} role and device scope. Expires ${date(result.expires)}. Old token stops at ${date(result.rotation_deadline)}. Save and test this replacement, then finish the handover. If this token is lost, cancel before the deadline and rotate again. Closing this dialog clears its value.`;
      $('access-dialog').showModal();
    }
    if (result.invalidated_ids?.includes(snapshot.identity.id)) {location.reload();return;}
    await loadAccess();
    await refresh();
    notify(action==='rotate'?'Replacement issued. Save it before closing the dialog.':action==='rotation/cancel'?'Handover cancelled; replacement invalidated.':action==='rotation/finish'?'Handover finished; old token invalidated.':'Service credential revoked.');
  } catch(error) {notify(error.message);button.disabled=false;}
};

if (location.origin) $('agent-command').textContent = 'python3 -m protec.agent --enroll --server ' + location.origin;
if (globalThis.protecDemo) {
  credential = 'demo';
  $('login').hidden=true;
  $('content').hidden=false;
  $('lock').hidden=false;
  $('lock').textContent='Reset demo';
  $('agent-command').textContent='Demo only. No device connects or receives commands.';
  refresh().catch(error=>notify(error.message));
}

function updateScopeForm() {
  const admin=$('access-role').value==='administrator';
  if(admin) $('access-scope').value='fleet';
  $('access-scope').disabled=admin;
  $('access-devices-label').hidden=$('access-scope').value!=='selected';
  $('access-devices').required=$('access-scope').value==='selected';
}
$('access-role').onchange=updateScopeForm;
$('access-scope').onchange=updateScopeForm;


async function cancelJob(event) {
  const button=event.target.closest('[data-cancel-job]');
  if(!button) return;
  if(!confirm('Cancel this inventory refresh? Further delivery and late completion will be rejected. An inventory read already running on the device may still finish.')) return;
  button.disabled=true;
  try {
    await api('jobs/cancel',{id:button.dataset.cancelJob});
    await refresh();
    if(!$('history').hidden) await loadHistory(true);
    notify('Inventory refresh cancelled. Regular device check-ins continue.');
  } catch(error) {notify(error.message);button.disabled=false;}
}
$('job-list').onclick=cancelJob;
$('history-list').onclick=cancelJob;


let scheduledDevice = null;
let scheduleBusy = false;
function localMinute(value) {
  const pad = number => String(number).padStart(2,'0');
  return `${value.getFullYear()}-${pad(value.getMonth()+1)}-${pad(value.getDate())}T${pad(value.getHours())}:${pad(value.getMinutes())}`;
}
function scheduleWindow() {
  const read = id => {
    const raw = $(id).value;
    const value = new Date(raw);
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(raw) || !Number.isFinite(value.getTime()) || localMinute(value) !== raw) throw Error('Choose valid local start and end times. A time skipped when clocks move forward cannot be scheduled.');
    return Math.floor(value.getTime()/1000);
  };
  const start = read('schedule-start'), end = read('schedule-end'), now = Date.now()/1000;
  if (start < now) throw Error('Choose a start time in the future.');
  if (end <= start) throw Error('The window must end after it starts.');
  if (end - start > 86400 || end > now + 30*86400) throw Error('Use a window no longer than 24 hours, ending within the next 30 days.');
  return {start,end};
}
function previewSchedule() {
  try {
    const window = scheduleWindow();
    $('schedule-error').textContent = '';
    $('schedule-preview').textContent = `UTC: ${new Date(window.start*1000).toISOString()} to ${new Date(window.end*1000).toISOString()}. Duration: ${(window.end-window.start)/60} minutes.`;
    $('schedule-submit').disabled = scheduleBusy;
    return window;
  } catch(error) {
    $('schedule-preview').textContent = '';
    $('schedule-error').textContent = error.message;
    $('schedule-submit').disabled = true;
    return null;
  }
}
function openSchedule(deviceId) {
  const device = snapshot?.devices.find(item => item.id === deviceId && !item.revoked);
  if (!device || !canSchedule()) { notify('Scheduling is unavailable for this device or control plane.'); return; }
  if (pendingRefresh(deviceId)) { notify('An inventory refresh is already pending. Review it in Activity.'); return; }
  scheduledDevice = deviceId;
  $('schedule-device').textContent = `${device.inventory.hostname} · ${deviceId}`;
  $('schedule-timezone').textContent = `Times use ${Intl.DateTimeFormat().resolvedOptions().timeZone}. Review the UTC preview when clocks change; a repeated local time uses its first occurrence.`;
  const start = Math.ceil((Date.now()+10*60000)/60000)*60000;
  $('schedule-start').value = localMinute(new Date(start));
  $('schedule-end').value = localMinute(new Date(start+30*60000));
  previewSchedule();
  $('schedule-dialog').showModal();
  $('schedule-start').focus();
}
$('schedule-start').oninput = previewSchedule;
$('schedule-end').oninput = previewSchedule;
$('schedule-cancel').onclick = () => { if (!scheduleBusy) $('schedule-dialog').close(); };
$('schedule-dialog').addEventListener('cancel',event => { if (scheduleBusy) event.preventDefault(); });
$('schedule-dialog').addEventListener('close',() => {
  scheduledDevice = null;
  for (const id of ['schedule-start','schedule-end']) $(id).value = '';
  for (const id of ['schedule-device','schedule-preview','schedule-error']) $(id).textContent = '';
});
$('schedule-form').addEventListener('submit',async event => {
  event.preventDefault();
  if (scheduleBusy) return;
  const window = previewSchedule();
  if (!window) return;
  const device = snapshot?.devices.find(item => item.id === scheduledDevice && !item.revoked);
  if (!device || !canSchedule()) { $('schedule-error').textContent = 'This device or scheduling permission is no longer available.'; return; }
  if (pendingRefresh(scheduledDevice)) { $('schedule-error').textContent = 'A refresh is already pending. Close this dialog and review Activity.'; return; }
  scheduleBusy = true;
  for (const id of ['schedule-start','schedule-end','schedule-submit','schedule-close','schedule-cancel']) $(id).disabled = true;
  let queued = false;
  try {
    await api('jobs',{device:scheduledDevice,window});
    queued = true;
    $('schedule-dialog').close();
    notify('Inventory refresh scheduled. Review the window in Activity.');
    await refresh();
  } catch(error) {
    if (queued) notify('The refresh was scheduled, but the dashboard could not reload. Reload the page to see it.');
    else $('schedule-error').textContent = `${error.message} If the response was lost, check Activity before retrying.`;
  } finally {
    scheduleBusy = false;
    for (const id of ['schedule-start','schedule-end','schedule-submit','schedule-close','schedule-cancel']) $(id).disabled = false;
  }
});

let policyWorkspace = {groups:[],policies:[]};
let policyCursor=null;
const policyOptions = items => items.map(x=>`<option value="${escape(x.id)}">${escape(x.name)} · revision ${x.revision}</option>`).join('');
async function loadPolicies() {
  if(snapshot?.policy_management!==1 || !can('policies.read')) return;
  const [groups,policies,compliance]=await Promise.all([api('groups'),api('policies'),api('compliance')]);
  policyWorkspace={...groups,...policies};
  $('group-form').hidden=!can('groups.write');$('policy-form').hidden=!can('policies.write');
  $('group-choice').innerHTML='<option value="">New group</option>'+policyOptions(groups.groups);
  $('policy-choice').innerHTML='<option value="">New policy</option>'+policyOptions(policies.policies);
  $('policy-group').innerHTML=policyOptions(groups.groups);
  $('group-choice').value='';$('policy-choice').value='';editGroup();editPolicy();
  $('group-list').innerHTML=groups.groups.map(g=>`<p><strong>${escape(g.name)}</strong> · revision ${g.revision} · ${g.members.length} visible members${g.scope_limited?' (credential scope)':''}</p>`).join('')||'<p>No groups in scope.</p>';
  $('policy-list').innerHTML=policies.policies.map(p=>`<p><strong>${escape(p.name)}</strong> · revision ${p.revision} · ${p.enabled?'Enabled':'Disabled'} · ${escape(p.rule.manager)} / ${escape(p.rule.package)}</p>`).join('')||'<p>No policies in scope.</p>';
  renderCompliance(compliance,false);
}
function renderCompliance(compliance,append){
  const names=new Map(policyWorkspace.policies.map(p=>[p.id,p.name]));
  $('policy-time').textContent='Page evaluated '+date(compliance.evaluated_at)+' · '+compliance.total+' results in scope';
  const html=compliance.results.map(r=>`<article><strong>${escape(names.get(r.policy_id)||r.policy_id)} · ${escape(r.status)}</strong><p>Device ${escape(r.device_id)} · policy revision ${r.policy_revision} · group revision ${r.group_revision}</p><p>${escape(r.reason)}</p></article>`).join('');
  if(append)$('policy-results').insertAdjacentHTML('beforeend',html);else $('policy-results').innerHTML=html||'<p>No enabled policies have devices assigned.</p>';
  policyCursor=compliance.next_cursor;$('policy-more').hidden=!policyCursor;
}
$('policy-more').onclick=async()=>{const button=$('policy-more');if(button.disabled||!policyCursor)return;button.disabled=true;try{renderCompliance(await api('compliance?cursor='+encodeURIComponent(policyCursor)),true);}catch(e){notify(e.message);}finally{button.disabled=false;}};

function editGroup(){
  const g=policyWorkspace.groups.find(g=>g.id===$('group-choice').value);
  $('group-name').value=g?.name||'';
  const members=new Set(g?.members||[]),devices=new Map((snapshot?.devices||[]).filter(d=>!d.revoked).map(d=>[d.id,d.inventory.hostname]));
  for(const id of members)if(!devices.has(id))devices.set(id,id+' (outside loaded inventory or revoked)');
  $('group-members').innerHTML=Array.from(devices,([id,name])=>`<option value="${escape(id)}" ${members.has(id)?'selected':''}>${escape(name)} · ${escape(id)}</option>`).join('');
}
function editPolicy(){const p=policyWorkspace.policies.find(p=>p.id===$('policy-choice').value);$('policy-name').value=p?.name||'';$('policy-group').value=p?.group_id||policyWorkspace.groups[0]?.id||'';$('policy-manager').value=p?.rule.manager||'dpkg';$('policy-package').value=p?.rule.package||'';$('policy-age').value=p?.rule.max_age_seconds||3600;$('policy-enabled').value=String(p?.enabled??true);}
$('group-choice').onchange=editGroup;$('policy-choice').onchange=editPolicy;
$('policy-refresh').onclick=()=>loadPolicies().catch(e=>notify(e.message));
async function savePolicyObject(kind,body,button){
  if(button.disabled || !can(kind+'.write') || snapshot?.policy_management!==1)return;
  const item=policyWorkspace[kind].find(x=>x.id===$(kind==='groups'?'group-choice':'policy-choice').value);
  if(item)Object.assign(body,{id:item.id,revision:item.revision});
  button.disabled=true;
  try{await api(kind,body);$(kind==='groups'?'group-choice':'policy-choice').value='';if(kind==='groups')editGroup();else editPolicy();notify('Revision saved.');try{await loadPolicies();}catch(e){notify('Revision saved, but reload failed: '+e.message);}}
  catch(e){notify(e.message);}finally{button.disabled=false;}
}
$('group-form').onsubmit=event=>{event.preventDefault();return savePolicyObject('groups',{name:$('group-name').value,members:Array.from($('group-members').selectedOptions,option=>option.value)},$('group-save'));};
$('policy-form').onsubmit=event=>{event.preventDefault();return savePolicyObject('policies',{name:$('policy-name').value,group_id:$('policy-group').value,enabled:$('policy-enabled').value==='true',rule:{kind:'package_present',manager:$('policy-manager').value,package:$('policy-package').value,max_age_seconds:Number($('policy-age').value)}},$('policy-save'));};

function packagePlan(job){
  const plan=job.preview?.plan;
  if(!plan)return '';
  return `<details><summary>Review package preview</summary><p>No changes applied. Preview ${plan.expires<=snapshot.time?'expired':'expires '+escape(date(plan.expires))}. Approval and execution are not enabled.</p><p>Plan SHA-256: <code class="receipt-digest">${escape(plan.plan_sha256)}</code></p>${plan.changes.map(c=>`<p><strong>${escape(c.name)}</strong> · ${escape({change_version:'Version change',install:'Install',remove:'Remove'}[c.action]||c.action)} · ${escape(c.before||'not installed')} → ${escape(c.after||'removed')}</p>`).join('')||'<p>No package changes needed.</p>'}<p>${plan.root_simulation?'Root':'Unprivileged'} simulation. Native package state must be revalidated before any future execution.</p></details>`;
}
$('package-action').onchange=()=>{$('package-version-label').hidden=$('package-action').value==='remove';};
$('package-preview-form').onsubmit=async event=>{
  event.preventDefault();const button=$('package-preview-submit');
  if(button.disabled)return;
  const device=snapshot?.devices.find(d=>d.id===previewDevice);
  if(!can('jobs.write')||snapshot?.package_previews!==1||!device||device.revoked||device.inventory.apt_preview!==1){$('package-preview-error').textContent='Package previews are no longer available for this device.';return;}
  if(pendingRefresh(previewDevice)){$('package-preview-error').textContent='A device action is already pending.';return;}
  const name=$('package-name').value.trim(),version=$('package-version').value.trim(),action=$('package-action').value;
  if(!/^[a-z0-9][a-z0-9+.-]{1,127}(?::[a-z0-9][a-z0-9-]{0,31})?$/.test(name)||/[+-]$/.test(name.split(':')[0])||!['install','remove'].includes(action)||(action==='install'&&!/^[0-9][A-Za-z0-9.+:~\-]{0,127}$/.test(version))){$('package-preview-error').textContent='Enter an exact package name and, for installation, an exact version.';return;}
  button.disabled=true;
  try{await api('package-previews',{device:previewDevice,request:{action,packages:[{name,...(action==='install'?{version}:{})}]}});$('packages-dialog').close();previewDevice=null;notify('Package preview requested. Results will appear in Activity.');try{await refresh();}catch(e){notify('Preview requested, but dashboard reload failed: '+e.message);}}
  catch(e){$('package-preview-error').textContent=e.message;}finally{button.disabled=false;}
};
