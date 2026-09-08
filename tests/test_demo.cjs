const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
function demo(){const context=vm.createContext({Date,URLSearchParams,structuredClone,fetch(){throw Error('Demo attempted network access');}});vm.runInContext(fs.readFileSync('website/demo.js','utf8'),context);return context.protecDemo;}
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
