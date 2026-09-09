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

test('policy workspace creates groups, versions policies and displays evidence without network',async()=>{
 const f=await fixture();await f.run('loadPolicies()');
 assert.match(f.elements.get('policy-results').innerHTML,/compliant/);assert.match(f.elements.get('policy-results').innerHTML,/unknown/);
 f.elements.get('group-name').value='Pilot';f.elements.get('group-members').selectedOptions=[{value:'demo-linux-01'}];
 await f.elements.get('group-form').onsubmit({preventDefault(){}});
 const groups=(await f.run("protecDemo.request('groups')")).groups;assert.equal(groups.length,2);
 f.elements.get('policy-name').value='Missing package';f.elements.get('policy-group').value=groups[1].id;f.elements.get('policy-package').value='not-installed';
 await f.elements.get('policy-form').onsubmit({preventDefault(){}});
 assert.match(f.elements.get('policy-results').innerHTML,/noncompliant/);
 const p=(await f.run("protecDemo.request('policies')")).policies[1];
 f.elements.get('policy-choice').value=p.id;f.elements.get('policy-choice').onchange();f.elements.get('policy-enabled').value='false';
 await f.elements.get('policy-form').onsubmit({preventDefault(){}});
 const updated=(await f.run("protecDemo.request('policies')")).policies[1];assert.equal(updated.revision,2);assert.equal(updated.enabled,false);
 assert.doesNotMatch(f.elements.get('policy-results').innerHTML,/noncompliant/);
});
test('readers cannot write policies and old servers do not load policy endpoints',async()=>{
 const f=await fixture();f.run("snapshot.identity.permissions=['groups.read','policies.read'];");await f.run('loadPolicies()');
 assert.equal(f.elements.get('group-form').hidden,true);assert.equal(f.elements.get('policy-form').hidden,true);
 await f.elements.get('group-form').onsubmit({preventDefault(){}});assert.equal((await f.run("protecDemo.request('groups')")).groups.length,1);
 f.run('snapshot.policy_management=undefined');f.context.protecDemo.request=()=>{throw Error('unexpected request');};await f.run('loadPolicies()');
});
test('mock rejects stale policy edits and invalid group membership',async()=>{
 const f=await fixture();const p=(await f.run("protecDemo.request('policies')")).policies[0];
 const {created,...body}=p;await f.context.protecDemo.request('policies',body);
 await assert.rejects(()=>f.context.protecDemo.request('policies',body),/changed/);
 await assert.rejects(()=>f.context.protecDemo.request('groups',{name:'Bad',members:['unknown']}),/active/);
});
test('a pending group save cannot submit twice and saved drafts clear before reload failure',async()=>{
 const f=await fixture();await f.run('loadPolicies()');f.elements.get('group-name').value='Once';
 let resolve,calls=0;const original=f.context.protecDemo.request;
 f.context.protecDemo.request=async(path,body)=>{if(path==='groups'&&body){calls++;await new Promise(done=>resolve=done);return original(path,body);}throw Error('Reload unavailable');};
 const submit=()=>f.elements.get('group-form').onsubmit({preventDefault(){}});
 const pending=submit();await submit();assert.equal(calls,1);resolve();await pending;
 assert.equal(f.elements.get('group-name').value,'');assert.match(f.elements.get('notice').textContent,/saved, but reload failed/);
});
