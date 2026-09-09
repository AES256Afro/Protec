const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
process.env.TZ='America/Chicago';

async function fixture(timestamp=Date.UTC(2026,8,9,12)) {
  const events=new Map(),elements=new Map();let current=timestamp;
  for(const [,id] of fs.readFileSync('static/index.html','utf8').matchAll(/id="([^"]+)"/g)) {
    elements.set(id,{value:'',textContent:'',innerHTML:'',hidden:false,disabled:false,open:false,selectedOptions:[],
      focus(){this.focused=true;},addEventListener(type,handler){events.set(id+':'+type,handler);},
      showModal(){this.open=true;},close(){this.open=false;events.get(id+':close')?.();},
      classList:{toggle(){}},insertAdjacentHTML(_,value){this.innerHTML+=value;}});
  }
  class Clock extends Date {constructor(...args){super(...(args.length?args:[current]));}static now(){return current;}}
  const context=vm.createContext({Date:Clock,Intl,URLSearchParams,structuredClone,
    document:{getElementById:id=>elements.get(id)||null,querySelector(){return {hidden:false,disabled:false};},querySelectorAll(){return [];}},
    fetch(){throw Error('UI attempted network access');},setInterval(){},confirm(){return true;},location:{origin:'https://demo.example',reload(){}}});
  vm.runInContext(fs.readFileSync('website/demo.js','utf8'),context);
  vm.runInContext(fs.readFileSync('static/app.js','utf8'),context);
  await vm.runInContext('refresh()',context);
  return {context,elements,events,run:code=>vm.runInContext(code,context),setTime:value=>{current=value;},
    submit:()=>events.get('schedule-form:submit')({preventDefault(){}}),
    open:()=>elements.get('device-rows').onclick({target:{closest:()=>({dataset:{schedule:'demo-linux-01'}})}})};
}

test('schedule form previews local bounds and queues matching UTC times in mock activity and history',async()=>{
 const f=await fixture();assert.match(f.elements.get('device-rows').innerHTML,/data-schedule="demo-linux-01"/);
 await f.open();assert.equal(f.elements.get('schedule-dialog').open,true);
 assert.match(f.elements.get('schedule-timezone').textContent,/America\/Chicago/);
 f.elements.get('schedule-start').value='2026-09-09T08:00';f.elements.get('schedule-end').value='2026-09-09T08:30';
 f.elements.get('schedule-start').oninput();assert.match(f.elements.get('schedule-preview').textContent,/13:00:00.000Z/);
 await f.submit();assert.equal(f.elements.get('schedule-dialog').open,false);
 const job=(await f.run("protecDemo.request('dashboard')")).jobs[0];
 assert.equal(job.not_before,Date.UTC(2026,8,9,13)/1000);assert.equal(job.not_after,Date.UTC(2026,8,9,13,30)/1000);
 assert.equal(job.status,'queued');assert.equal(job.attempt,0);
 assert.match(f.elements.get('job-list').innerHTML,/Window \(local time\)/);
 f.elements.get('history-kind').value='jobs';await f.run('loadHistory(true)');
 assert.match(f.elements.get('history-list').innerHTML,/Window \(local time\)/);
 assert.equal(f.elements.get('schedule-start').value,'');
});

test('capability omission, viewer access, revoked devices and pending jobs prevent scheduling',async()=>{
 for(const edit of ["delete snapshot.job_windows", "snapshot.identity.permissions=['inventory.read','jobs.read']", "snapshot.devices[0].revoked=1"]){
  const f=await fixture();f.run(edit+';render()');await f.open();assert.equal(f.elements.get('schedule-dialog').open,false);
 }
 const f=await fixture();f.run("openSchedule('demo-mac-01')");assert.equal(f.elements.get('schedule-dialog').open,false);
 assert.match(f.elements.get('notice').textContent,/already pending/);
});

test('invalid bounds and permission loss during an open form never create a job',async()=>{
 const f=await fixture();await f.open();const count=(await f.run("protecDemo.request('dashboard')")).jobs.length;
 for(const [start,end] of [['2026-09-09T06:59','2026-09-09T08:00'],['2026-09-09T08:00','2026-09-09T08:00'],['2026-09-09T08:00','2026-09-10T08:01'],['2026-10-10T08:00','2026-10-10T09:00'],['2026-02-30T08:00','2026-09-09T09:00']]){
  f.elements.get('schedule-start').value=start;f.elements.get('schedule-end').value=end;await f.submit();
  assert.notEqual(f.elements.get('schedule-error').textContent,'');
 }
 f.elements.get('schedule-start').value='2026-09-09T08:00';f.elements.get('schedule-end').value='2026-09-09T09:00';
 f.run("snapshot.identity.permissions=[]");await f.submit();assert.match(f.elements.get('schedule-error').textContent,/no longer available/);
 assert.equal((await f.run("protecDemo.request('dashboard')")).jobs.length,count);
});

test('spring-forward gaps are rejected and fall-back overlap has an explicit first-occurrence preview',async()=>{
 const spring=await fixture(Date.UTC(2026,2,1));await spring.open();
 spring.elements.get('schedule-start').value='2026-03-08T02:30';spring.elements.get('schedule-end').value='2026-03-08T04:00';
 await spring.submit();assert.match(spring.elements.get('schedule-error').textContent,/clocks move forward/);
 const fall=await fixture(Date.UTC(2026,9,25));await fall.open();
 fall.elements.get('schedule-start').value='2026-11-01T01:30';fall.elements.get('schedule-end').value='2026-11-01T02:30';
 fall.elements.get('schedule-start').oninput();
 assert.match(fall.elements.get('schedule-preview').textContent,/06:30:00.000Z to .*08:30:00.000Z/);
 assert.match(fall.elements.get('schedule-preview').textContent,/120 minutes/);
});

test('pending submission blocks duplicate submits and dialog dismissal',async()=>{
 const f=await fixture();await f.open();let resolve,calls=0;
 const original=f.context.protecDemo.request;
 f.context.protecDemo.request=async(path,body)=>{if(path==='jobs'){calls++;await new Promise(done=>{resolve=done;});}return original(path,body);};
 const pending=f.submit();await f.submit();assert.equal(calls,1);
 let prevented=false;f.events.get('schedule-dialog:cancel')({preventDefault(){prevented=true;}});
 assert.equal(prevented,true);f.elements.get('schedule-cancel').onclick();assert.equal(f.elements.get('schedule-dialog').open,true);
 resolve();await pending;assert.equal(f.elements.get('schedule-dialog').open,false);
});

test('failed submission retains inputs while a successful queue followed by reload failure cannot be resubmitted',async()=>{
 const f=await fixture();await f.open();let jobs=0;
 f.context.protecDemo.request=async(path)=>{if(path==='jobs'){jobs++;throw Error('Lost response');}throw Error('offline');};
 await f.submit();assert.equal(f.elements.get('schedule-dialog').open,true);assert.notEqual(f.elements.get('schedule-start').value,'');
 assert.match(f.elements.get('schedule-error').textContent,/check Activity before retrying/);
 f.context.protecDemo.request=async(path)=>{if(path==='jobs'){jobs++;return {id:'queued'};}throw Error('reload failure');};
 await f.submit();assert.equal(jobs,2);assert.equal(f.elements.get('schedule-dialog').open,false);
 assert.match(f.elements.get('notice').textContent,/was scheduled, but the dashboard could not reload/);
 await f.submit();assert.equal(jobs,2);
});

test('cancelling a draft clears its target and times without changing jobs',async()=>{
 const f=await fixture();await f.open();const before=(await f.run("protecDemo.request('dashboard')")).jobs.length;
 f.elements.get('schedule-cancel').onclick();assert.equal(f.elements.get('schedule-dialog').open,false);
 assert.equal(f.elements.get('schedule-device').textContent,'');assert.equal(f.elements.get('schedule-start').value,'');
 assert.equal((await f.run("protecDemo.request('dashboard')")).jobs.length,before);
});
