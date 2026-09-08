/* Browser-only fixture transport. This file is absent from the management image. */
(() => {
  const now = () => Date.now()/1000;
  let sequence=20;
  const id=()=>`demo-${++sequence}`;
  const permissions=['inventory.read','jobs.read','health.read','jobs.write','devices.revoke','enrollments.read','enrollments.write','audit.read','credentials.read','credentials.write'];
  const devices=[['demo-linux-01','lab-ubuntu','Linux','Ubuntu 24.04','x86_64',12],['demo-mac-01','studio-mac','macOS','27.0','arm64',25],['demo-linux-02','lab-debian','Linux','Debian 13','x86_64',7200]].map(([id,hostname,os,version,architecture,age])=>({id,seen:now()-age,revoked:0,inventory:{hostname,os,version,architecture,agent_version:'0.2.0',privilege:'standard',packages:{status:'ok',scope:os==='macOS'?'Homebrew formulae':'Debian packages',manager:os==='macOS'?'homebrew':'dpkg',collected_at:now()-age,total:3,truncated:false,message:'Illustrative package versions from mock devices.',items:[{name:'curl',version:'8.14.1'},{name:'git',version:'2.49.0'},{name:'python3',version:'3.13.5'}]}}}));
  const jobs=[['demo-running-refresh','demo-mac-01','running',1],['demo-queued-refresh','demo-linux-02','queued',0]].map(([id,device,status,attempt])=>({id,device,status,attempt,kind:'refresh_inventory',created:now()-45,result:null,contract_version:attempt?1:0,receipt:null,completed:null,issued_by:'demo-administrator'}));
  const audit=[{id:1,time:now()-60,actor:'demo-administrator',action:'demo.started',target:'Mock fleet'}];
  const enrollments=[];
  const credentials=[];
  const record=(action,target)=>audit.unshift({id:++sequence,time:now(),actor:'demo-administrator',action,target});
  const status=(items)=>items.map(item=>({...item,status:item.status==='revoked'?'revoked':item.expires<=now()?'expired':item.rotation_deadline!=null?(item.rotation_deadline>now()?'rotating':'rotated'):item.status}));
  globalThis.protecDemo={async request(path,body){
    const [route,query='']=path.split('?');
    let result;
    if(body===undefined) {
      if(route==='dashboard') result={devices,jobs,audit,time:now(),pending:jobs.filter(job=>['queued','running'].includes(job.status)).length,fleet:{records:devices.length,active:devices.filter(d=>!d.revoked).length,online:devices.filter(d=>!d.revoked && now()-d.seen<90).length},identity:{id:'demo-administrator',name:'Demo administrator',role:'administrator',device_ids:null,permissions}};
      else if(route==='enrollments') result={enrollments:status(enrollments)};
      else if(route==='credentials') result={credentials:status(credentials),next_cursor:null};
      else if(route==='health') result={status:'simulated',database:'mock data in this tab',schema_version:5,uptime_seconds:0,counts:{devices:devices.length,jobs:jobs.length,enrollments:enrollments.length,audit:audit.length}};
      else if(route==='history') { const kind=new URLSearchParams(query).get('kind'); const items={devices,jobs,audit,enrollments:status(enrollments)}[kind]; if(!items) throw Error('Unknown history collection'); result={items,next_cursor:null,kind}; }
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
    else if(route==='jobs'||route==='revoke') {const device=devices.find(d=>d.id===body.device&&!d.revoked);if(!device) throw Error('Active mock device not found');if(route==='revoke'){device.revoked=1;for(const job of jobs.filter(job=>job.device===device.id&&['queued','running'].includes(job.status)))job.status='cancelled';record('device.revoked',device.id);}else{if(jobs.some(job=>job.device===device.id&&['queued','running'].includes(job.status)))throw Error('An inventory refresh is already pending');device.seen=now();device.inventory.packages.collected_at=now();const jobId=id();jobs.unshift({id:jobId,device:device.id,kind:'refresh_inventory',status:'completed',created:now(),result:'Simulated inventory received',contract_version:1,attempt:1,completed:now(),issued_by:'demo-administrator',receipt:{version:1,job:jobId,device:device.id,kind:'refresh_inventory',attempt:1,outcome:'succeeded',inventory_sha256:'d'.repeat(64),recorded_at:now()}});record('inventory.completed',device.id);}result={ok:true};}
    if(!result) throw Error('This operation is not available in the demo');
    return structuredClone(result);
  }};
})();
