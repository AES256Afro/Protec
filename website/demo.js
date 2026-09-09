/* Browser-only fixture transport. This file is absent from the management image. */
(() => {
  const now = () => Date.now()/1000;
  let sequence=20;
  const id=()=>`demo-${++sequence}`;
  const permissions=['groups.read','groups.write','policies.read','policies.write','inventory.read','jobs.read','health.read','jobs.write','devices.revoke','enrollments.read','enrollments.write','audit.read','credentials.read','credentials.write'];
  const devices=[['demo-linux-01','lab-ubuntu','Linux','Ubuntu 24.04','x86_64',12],['demo-mac-01','studio-mac','macOS','27.0','arm64',25],['demo-linux-02','lab-debian','Linux','Debian 13','x86_64',7200]].map(([id,hostname,os,version,architecture,age])=>({id,seen:now()-age,revoked:0,inventory:{apt_preview:os==='Linux'?1:0,hostname,os,version,architecture,agent_version:'0.2.0',privilege:'standard',packages:{status:'complete',scope:os==='macOS'?'Homebrew formulae':'Debian packages',manager:os==='macOS'?'homebrew':'dpkg',collected_at:now()-age,total:3,truncated:false,message:'Illustrative package versions from mock devices.',items:[{name:'curl',version:'8.14.1'},{name:'git',version:'2.49.0'},{name:'python3',version:'3.13.5'}]}}}));
  const groups=[{id:'demo-group-linux',name:'Linux pilot',revision:1,members:['demo-linux-01','demo-linux-02']}];
  const policies=[{id:'demo-policy-git',name:'Git installed',revision:1,group_id:'demo-group-linux',enabled:true,rule:{kind:'package_present',manager:'dpkg',package:'git',max_age_seconds:3600}}];
  const jobs=[['demo-running-refresh','demo-mac-01','running',1],['demo-queued-refresh','demo-linux-02','queued',0]].map(([id,device,status,attempt])=>({id,device,status,attempt,kind:'refresh_inventory',created:now()-45,result:null,contract_version:attempt?1:0,receipt:null,completed:null,issued_by:'demo-administrator',not_before:status==='queued'?Math.ceil(now()+3600):null,not_after:status==='queued'?Math.ceil(now()+7200):null}));
  const audit=[{id:1,time:now()-60,actor:'demo-administrator',action:'demo.started',target:'Mock fleet'}];
  const enrollments=[];
  const credentials=[];
  const record=(action,target)=>audit.unshift({id:++sequence,time:now(),actor:'demo-administrator',action,target});
  const status=(items)=>items.map(item=>({...item,status:item.status==='revoked'?'revoked':item.expires<=now()?'expired':item.rotation_deadline!=null?(item.rotation_deadline>now()?'rotating':'rotated'):item.status}));
  const finishJob=(job)=>{
    job.status='completed';job.result='Simulated inventory received';job.contract_version=1;job.attempt=1;job.completed=now();
    job.receipt={version:1,job:job.id,device:job.device,kind:'refresh_inventory',attempt:1,outcome:'succeeded',inventory_sha256:'d'.repeat(64),recorded_at:now()};
    const device=devices.find(d=>d.id===job.device);device.seen=now();device.inventory.packages.collected_at=now();record('inventory.completed',job.device);
  };
  const advanceWindows=()=>{
    for(const job of jobs.filter(j=>j.status==='queued'&&j.not_before!=null&&j.not_before<=now())) {
      if(job.not_after<=now()){job.status='failed';job.result='Maintenance window expired';record('inventory.window_expired',job.id);}
      else finishJob(job);
    }
  };
  const windowBounds=(value)=>{
    if(value==null)return [null,null];
    if(typeof value!=='object'||Array.isArray(value)||Object.keys(value).sort().join(',')!=='end,start'||!Number.isInteger(value.start)||!Number.isInteger(value.end)||value.start<now()||value.end<=value.start||value.end>now()+30*86400||value.end-value.start>86400)throw Error('Invalid maintenance window');
    return [value.start,value.end];
  };
  globalThis.protecDemo={async request(path,body){
    const [route,query='']=path.split('?');
    advanceWindows();
    let result;
    if(body===undefined) {
      if(route==='dashboard') result={devices,jobs,audit,policy_management:1,package_previews:1,job_windows:1,time:now(),pending:jobs.filter(job=>['queued','running'].includes(job.status)).length,fleet:{records:devices.length,active:devices.filter(d=>!d.revoked).length,online:devices.filter(d=>!d.revoked && now()-d.seen<90).length},identity:{id:'demo-administrator',name:'Demo administrator',role:'administrator',device_ids:null,permissions}};
      else if(route==='groups') result={groups};
      else if(route==='policies') result={policies};
      else if(route==='compliance') result={evaluated_at:now(),scope_limited:false,results:policies.filter(p=>p.enabled).flatMap(p=>groups.find(g=>g.id===p.group_id).members.map(device_id=>{const g=groups.find(g=>g.id===p.group_id),d=devices.find(d=>d.id===device_id),report=d?.inventory.packages;let status='unknown',reason='Device or package evidence is unavailable, stale, or unsupported';if(d&&!d.revoked&&now()-d.seen<=p.rule.max_age_seconds&&report?.status==='complete'&&report.manager===p.rule.manager&&now()-report.collected_at<=p.rule.max_age_seconds){if(report.items.some(i=>i.name===p.rule.package)){status='compliant';reason='The required package is present in fresh inventory';}else if(!report.truncated){status='noncompliant';reason='Complete fresh inventory does not contain the required package';}}return {policy_id:p.id,policy_revision:p.revision,group_id:g.id,group_revision:g.revision,device_id,status,reason,evaluated_at:now()};}))};
      else if(route==='enrollments') result={enrollments:status(enrollments)};
      else if(route==='credentials') result={credentials:status(credentials),next_cursor:null};
      else if(route==='health') result={version:'0.6.0',status:'simulated',database:'mock data in this tab',schema_version:8,uptime_seconds:0,counts:{devices:devices.length,jobs:jobs.length,enrollments:enrollments.length,audit:audit.length}};
      else if(route==='history') { const kind=new URLSearchParams(query).get('kind'); const items={devices,jobs,audit,enrollments:status(enrollments)}[kind]; if(!items) throw Error('Unknown history collection'); result={items,next_cursor:null,kind}; }
    } else if(route==='package-previews') {
      const device=devices.find(d=>d.id===body.device&&!d.revoked&&d.inventory.apt_preview===1),request=body.request;
      if(!device||jobs.some(j=>j.device===body.device&&['queued','running'].includes(j.status)))throw Error('Choose an available Linux device without a pending action');
      if(Object.keys(body).sort().join(',')!=='device,request'||!request||Object.keys(request).sort().join(',')!=='action,packages'||!['install','remove'].includes(request.action)||!Array.isArray(request.packages)||!request.packages.length||request.packages.length>20)throw Error('Invalid package preview request');
      const names=new Set();
      for(const p of request.packages){if(!p||Object.keys(p).sort().join(',')!==(request.action==='install'?'name,version':'name')||typeof p.name!=='string'||!/^[a-z0-9][a-z0-9+.-]{1,127}(?::[a-z0-9][a-z0-9-]{0,31})?$/.test(p.name)||/[+-]$/.test(p.name.split(':')[0])||names.has(p.name)||(request.action==='install'&&(typeof p.version!=='string'||!/^[0-9][A-Za-z0-9.+:~\-]{0,127}$/.test(p.version))))throw Error('Use exact package names and versions');if(request.action==='remove'&&!device.inventory.packages.items.some(i=>i.name===p.name))throw Error('Removal preview requires an installed mock package');names.add(p.name);}
      const changes=request.packages.flatMap(p=>{const before=device.inventory.packages.items.find(i=>i.name===p.name)?.version||null;const after=request.action==='install'?p.version:null;return before===after?[]:[{name:p.name,before,after,action:after===null?'remove':before===null?'install':'change_version'}];});
      const plan={version:2,kind:'apt_preview',device:device.id,request,changes,artifacts:changes.filter(c=>c.after!==null).map(c=>({name:c.name,version:c.after,sha256:'c'.repeat(64),size:123456})),created:now(),expires:now()+900,root_simulation:false,requires_revalidation:true,plan_sha256:'a'.repeat(64)};
      const job={id:id(),device:device.id,kind:'preview_packages',status:'completed',created:now(),completed:now(),attempt:1,contract_version:1,result:'Simulated package preview; no changes applied',payload:request,preview:{outcome:'succeeded',plan},receipt:{version:1,job:null,device:device.id,kind:'preview_packages',attempt:1,outcome:'succeeded',result_sha256:'b'.repeat(64),recorded_at:now()}};job.receipt.job=job.id;jobs.unshift(job);record('packages.preview_completed',job.id);result={id:job.id};
    } else if(route==='groups' ||route==='policies') {
      const list=route==='groups'?groups:policies;
      const fields=route==='groups'?['members','name']:['enabled','group_id','name','rule'];
      if(body.id!==undefined)fields.push('id','revision');
      if(Object.keys(body).sort().join(',')!==fields.sort().join(',')||typeof body.name!=='string'||!body.name.trim()||body.name.trim().length>80||/[\x00-\x1f\x7f]/.test(body.name))throw Error('Supply a name and all required fields');
      const old=list.find(x=>x.id===body.id);
      if(body.id!==undefined&&(!old||old.revision!==body.revision))throw Error('This object changed. Reload before saving again');
      if(!old&&list.length>=100)throw Error('Maximum of 100 objects in this collection');
      if(route==='groups'){
        if(!Array.isArray(body.members)||body.members.length>100||new Set(body.members).size!==body.members.length||body.members.some(id=>!devices.some(d=>d.id===id&&!d.revoked)))throw Error('Choose up to 100 active mock devices');
      }else{
        const r=body.rule;
        if(!groups.some(g=>g.id===body.group_id)||typeof body.enabled!=='boolean'||!r||Object.keys(r).sort().join(',')!=='kind,manager,max_age_seconds,package'||r.kind!=='package_present'||!['dpkg','homebrew'].includes(r.manager)||typeof r.package!=='string'||!/^[a-zA-Z0-9][a-zA-Z0-9+._:@/-]{0,127}$/.test(r.package)||!Number.isInteger(r.max_age_seconds)||r.max_age_seconds<60||r.max_age_seconds>86400)throw Error('Choose a group and a valid package-presence rule');
      }
      result={...structuredClone(body),name:body.name.trim(),id:old?.id||id(),revision:(old?.revision||0)+1,created:now()};
      if(old)list[list.indexOf(old)]=result;else list.push(result);
      record(route+'.saved',result.id+':'+result.revision);
    } else if(route==='enrollments') {const item={id:id(),expires:now()+900,status:'active'};enrollments.unshift(item);record('enrollment.created',item.id);result={token:'DEMO_ONLY_NOT_A_REAL_ENROLLMENT_TOKEN',expires_in:900};}
    else if(route==='enrollments/revoke') {const list=route.startsWith('enrollments')?enrollments:credentials;const item=list.find(i=>i.id===body.id && i.status==='active');if(!item) throw Error('Active mock credential not found');item.status='revoked';record(route.startsWith('enrollments')?'enrollment.revoked':'credential.revoked',item.id);result={ok:true};}
    else if(route==='credentials') {if(!['viewer','operator','administrator'].includes(body.role)||!body.name?.trim()||!Number.isInteger(body.hours)||body.hours<1||body.hours>720) throw Error('Enter a name, role, and lifetime of 1 to 720 hours'); if(body.device_ids!==undefined && body.device_ids!==null && (!Array.isArray(body.device_ids)||!body.device_ids.length||body.device_ids.length>100||new Set(body.device_ids).size!==body.device_ids.length||body.role==='administrator'||body.device_ids.some(id=>!devices.some(d=>d.id===id&&!d.revoked)))) throw Error('Select active mock devices for a viewer or operator credential'); const item={id:id(),name:body.name,role:body.role,device_ids:body.device_ids??null,created:now(),expires:now()+body.hours*3600,status:'active',replacement_id:null,rotation_deadline:null};credentials.unshift(item);record('credential.issued',item.id);result={...item,token:'DEMO_ONLY_NOT_A_REAL_ACCESS_TOKEN'};}
    else if(['credentials/rotate','credentials/rotation/finish','credentials/rotation/cancel','credentials/revoke'].includes(route)) {
      const item=credentials.find(i=>i.id===body.id && i.status!=='revoked');
      if(!item) throw Error('Unrevoked mock service credential not found');
      const replacement=credentials.find(i=>i.id===item.replacement_id);
      if(route==='credentials/rotate') {
        if(item.expires<=now()||item.replacement_id) throw Error('Active credential without a pending rotation required');
        if(credentials.some(i=>i.replacement_id===item.id&&i.status!=='revoked')) throw Error('Finish the previous handover before rotating its replacement');
        const next={...item,id:id(),created:now()};
        item.replacement_id=next.id;item.rotation_deadline=Math.min(now()+900,item.expires);
        credentials.unshift(next);record('credential.rotation_started',item.id+':'+next.id);
        result={...next,token:'DEMO_ONLY_NOT_A_REAL_ACCESS_TOKEN',replaces:item.id,rotation_deadline:item.rotation_deadline};
      } else if(route==='credentials/revoke') {
        item.status='revoked';record('credential.revoked',item.id);
        if(replacement&&replacement.status!=='revoked'){replacement.status='revoked';record('credential.revoked',replacement.id);}
        result={ok:true,invalidated_ids:[item.id,...(replacement?[replacement.id]:[])]};
      } else {
        if(!replacement) throw Error('Pending credential rotation not found');
        if(route.endsWith('/cancel')) {
          if(now()>=Math.min(item.rotation_deadline,item.expires)) throw Error('Handover deadline passed; use another administrator credential to issue a replacement');
          replacement.status='revoked';item.replacement_id=null;item.rotation_deadline=null;
          record('credential.rotation_cancelled',item.id+':'+replacement.id);
        } else {
          if(replacement.status==='revoked'||replacement.expires<=now()) throw Error('Replacement credential is no longer active');
          item.status='revoked';record('credential.rotation_finished',item.id+':'+replacement.id);
        }
        result={ok:true,invalidated_ids:[route.endsWith('/cancel')?replacement.id:item.id]};
      }
    }
    else if(route==='jobs/cancel') {
      const job=jobs.find(item=>item.id===body.id);
      if(!job) throw Error('Inventory job not found');
      if(job.status==='cancelled') result={ok:true,id:job.id,status:'cancelled',duplicate:true};
      else {
        if(!['queued','running'].includes(job.status)) throw Error('Only queued or running inventory jobs can be cancelled');
        job.status='cancelled';job.result='Cancelled by operator';record('inventory.cancelled',job.id);
        result={ok:true,id:job.id,status:'cancelled',duplicate:false};
      }
    }
    else if(route==='jobs'||route==='revoke') {
      const device=devices.find(d=>d.id===body.device&&!d.revoked);if(!device)throw Error('Active mock device not found');
      if(route==='revoke') {
        device.revoked=1;for(const job of jobs.filter(j=>j.device===device.id&&['queued','running'].includes(j.status)))job.status='cancelled';record('device.revoked',device.id);result={ok:true};
      } else {
        const [not_before,not_after]=windowBounds(body.window);
        if(jobs.some(j=>j.device===device.id&&['queued','running'].includes(j.status)))throw Error('An inventory refresh is already pending');
        const job={id:id(),device:device.id,kind:'refresh_inventory',status:'queued',created:now(),result:null,contract_version:0,attempt:0,completed:null,issued_by:'demo-administrator',receipt:null,not_before,not_after};
        jobs.unshift(job);record('inventory.requested',device.id);
        if(not_before==null)finishJob(job);
        result={id:job.id};
      }
    }
    if(!result) throw Error('This operation is not available in the demo');
    if(route==='compliance'&&result){
      const params=new URLSearchParams(query),limit=Number(params.get('limit')||100),cursor=params.get('cursor');
      if(!Number.isInteger(limit)||limit<1||limit>100)throw Error('Invalid compliance page');
      result.results.sort((a,b)=>(a.policy_id+':'+a.device_id).localeCompare(b.policy_id+':'+b.device_id));
      result.total=result.results.length;
      const remaining=result.results.filter(r=>!cursor||r.policy_id+':'+r.device_id>cursor);
      result.results=remaining.slice(0,limit);
      const last=result.results.at(-1);result.next_cursor=remaining.length>limit?last.policy_id+':'+last.device_id:null;
    }
    return structuredClone(result);
  }};
})();
