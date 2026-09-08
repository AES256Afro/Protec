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
