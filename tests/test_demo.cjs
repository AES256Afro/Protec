const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function demo(clock=Date){const context=vm.createContext({Date:clock,URLSearchParams,structuredClone,fetch(){throw Error('Demo attempted network access');}});vm.runInContext(fs.readFileSync('website/demo.js','utf8'),context);return context.protecDemo;}
test('demo lifecycle changes only mock state and reset restores it',async()=>{
 const app=demo();const before=await app.request('dashboard');assert.equal(before.devices.length,3);
 const device=before.devices[0].id;
 await app.request('jobs',{device});assert.equal((await app.request('dashboard')).jobs[0].status,'completed');
 await app.request('revoke',{device});assert.equal((await app.request('dashboard')).fleet.active,2);
 await assert.rejects(()=>app.request('jobs',{device}),/not found/);
 assert.equal((await demo().request('dashboard')).fleet.active,3);
 const enrollment=await app.request('enrollments',{});assert.match(enrollment.token,/DEMO_ONLY/);
 const issued=(await app.request('enrollments')).enrollments[0];await app.request('enrollments/revoke',{id:issued.id});assert.equal((await app.request('enrollments')).enrollments[0].status,'revoked');
 const credential=await app.request('credentials',{name:'Reader',role:'viewer',hours:24});assert.match(credential.token,/DEMO_ONLY/);
 await app.request('credentials/revoke',{id:credential.id});assert.equal((await app.request('credentials')).credentials[0].status,'revoked');
 assert.equal((await app.request('health')).status,'simulated');
 assert.ok((await app.request('history?kind=audit')).items.length>1);
 await assert.rejects(()=>app.request('ssh',{}),/not available/);
});
test('mock snapshots cannot mutate transport state',async()=>{const app=demo();const data=await app.request('dashboard');data.devices.splice(0);assert.equal((await app.request('dashboard')).devices.length,3);});

test('demo credential scopes validate selected devices and forbid scoped administrators',async()=>{
 const app=demo(); const device=(await app.request('dashboard')).devices[0].id;
 const scoped=await app.request('credentials',{name:'Selected reader',role:'viewer',hours:1,device_ids:[device]});
 assert.deepEqual(scoped.device_ids,[device]);
 const listing=await app.request('credentials');assert.deepEqual(listing.credentials[0].device_ids,[device]);
 for(const change of [{device_ids:[]},{device_ids:['unknown']},{device_ids:[device,device]},{role:'administrator'}]) await assert.rejects(()=>app.request('credentials',{name:'Invalid scope',role:'viewer',hours:1,device_ids:[device],...change}),/Select active/);
});


test('mock credential handover supports loss recovery, finish and pair revocation',async()=>{
 const app=demo();const source=await app.request('credentials',{name:'Reader',role:'viewer',hours:24});
 const newToken=await app.request('credentials/rotate',{id:source.id});
 assert.equal(newToken.expires,source.expires);assert.equal(newToken.role,source.role);
 assert.match(newToken.token,/DEMO_ONLY/);
 let items=(await app.request('credentials')).credentials;
 assert.equal(items.find(i=>i.id===source.id).status,'rotating');
 assert.ok(!JSON.stringify(items).includes(newToken.token));
 await assert.rejects(()=>app.request('credentials/rotate',{id:source.id}),/pending rotation/);
 await assert.rejects(()=>app.request('credentials/rotate',{id:newToken.id}),/previous handover/);
 await app.request('credentials/rotation/cancel',{id:source.id});
 items=(await app.request('credentials')).credentials;
 assert.equal(items.find(i=>i.id===source.id).status,'active');
 assert.equal(items.find(i=>i.id===newToken.id).status,'revoked');
 const retry=await app.request('credentials/rotate',{id:source.id});
 await app.request('credentials/rotation/finish',{id:source.id});
 assert.equal((await app.request('credentials')).credentials.find(i=>i.id===source.id).status,'revoked');
 const next=await app.request('credentials/rotate',{id:retry.id});
 const result=await app.request('credentials/revoke',{id:retry.id});
 assert.deepEqual(result.invalidated_ids,[retry.id,next.id]);
});

test('mock handover cutoff prevents cancellation or expiry extension',async()=>{
 let timestamp=1000000;const app=demo({now:()=>timestamp*1000});
 const source=await app.request('credentials',{name:'Reader',role:'viewer',hours:1});
 const next=await app.request('credentials/rotate',{id:source.id});
 timestamp=next.rotation_deadline;
 assert.equal((await app.request('credentials')).credentials.find(i=>i.id===source.id).status,'rotated');
 await assert.rejects(()=>app.request('credentials/rotation/cancel',{id:source.id}),/deadline passed/);
 timestamp=source.expires;
 assert.equal((await app.request('credentials')).credentials.find(i=>i.id===next.id).status,'expired');
 await assert.rejects(()=>app.request('credentials/rotation/finish',{id:source.id}),/no longer active/);
});


test('mock refresh includes a safe simulated completion receipt in job history',async()=>{
 const app=demo(),device=(await app.request('dashboard')).devices[0].id;
 await app.request('jobs',{device});
 const job=(await app.request('dashboard')).jobs[0];
 assert.equal(job.attempt,1);assert.equal(job.contract_version,1);
 assert.equal(job.receipt.device,device);assert.equal(job.receipt.job,job.id);
 assert.equal(job.receipt.outcome,'succeeded');assert.match(job.receipt.inventory_sha256,/^[a-f0-9]{64}$/);
 assert.deepEqual((await app.request('history?kind=jobs')).items[0].receipt,job.receipt);
 assert.ok(!JSON.stringify(job).includes('lease_token'));
});

test('mock queued and running refreshes can be cancelled once and block late cancellation of completed work',async()=>{
 const app=demo();let snapshot=await app.request('dashboard');assert.equal(snapshot.pending,2);
 for(const job of snapshot.jobs){
   await assert.rejects(()=>app.request('jobs',{device:job.device}),/already pending/);
   assert.equal((await app.request('jobs/cancel',{id:job.id})).duplicate,false);
   assert.equal((await app.request('jobs/cancel',{id:job.id})).duplicate,true);
 }
 snapshot=await app.request('dashboard');assert.equal(snapshot.pending,0);
 assert.equal(snapshot.audit.filter(row=>row.action==='inventory.cancelled').length,2);
 assert.ok(snapshot.jobs.every(job=>job.status==='cancelled'&&!job.receipt));
 await app.request('jobs',{device:snapshot.devices[0].id});
 const completed=(await app.request('dashboard')).jobs[0];
 await assert.rejects(()=>app.request('jobs/cancel',{id:completed.id}),/Only queued or running/);
 await assert.rejects(()=>app.request('jobs/cancel',{id:'missing'}),/not found/);
});
