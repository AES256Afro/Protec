/* Browser-only fixture transport. This file is absent from the management image. */
(() => {
  const now = () => Date.now()/1000;
  let sequence=20;
  const id=()=>`demo-${++sequence}`;
  const permissions=['inventory.read','jobs.read','health.read','jobs.write','devices.revoke','enrollments.read','enrollments.write','audit.read','credentials.read','credentials.write'];
  const devices=[['demo-linux-01','lab-ubuntu','Linux','Ubuntu 24.04','x86_64',12],['demo-mac-01','studio-mac','macOS','27.0','arm64',25],['demo-linux-02','lab-debian','Linux','Debian 13','x86_64',7200]].map(([id,hostname,os,version,architecture,age])=>({id,seen:now()-age,revoked:0,inventory:{hostname,os,version,architecture,agent_version:'0.2.0',privilege:'standard',packages:{status:'ok',scope:os==='macOS'?'Homebrew formulae':'Debian packages',manager:os==='macOS'?'homebrew':'dpkg',collected_at:now()-age,total:3,truncated:false,message:'Illustrative package versions from mock devices.',items:[{name:'curl',version:'8.14.1'},{name:'git',version:'2.49.0'},{name:'python3',version:'3.13.5'}]}}}));
  const jobs=[];
  const audit=[{id:1,time:now()-60,actor:'demo-administrator',action:'demo.started',target:'Mock fleet'}];
  const enrollments=[];
  const credentials=[];
  const record=(action,target)=>audit.unshift({id:++sequence,time:now(),actor:'demo-administrator',action,target});
  const status=(items)=>items.map(item=>({...item,status:item.status==='revoked'?'revoked':item.expires<now()?'expired':item.status}));
  globalThis.protecDemo={async request(path,body){
    const [route,query='']=path.split('?');
    let result;
    if(body===undefined) {
      if(route==='dashboard') result={devices,jobs,audit,time:now(),pending:0,fleet:{records:devices.length,active:devices.filter(d=>!d.revoked).length,online:devices.filter(d=>!d.revoked && now()-d.seen<90).length},identity:{id:'demo-administrator',name:'Demo administrator',role:'administrator',permissions}};
      else if(route==='enrollments') result={enrollments:status(enrollments)};
      else if(route==='credentials') result={credentials:status(credentials),next_cursor:null};
      else if(route==='health') result={status:'simulated',database:'mock data in this tab',schema_version:2,uptime_seconds:0,counts:{devices:devices.length,jobs:jobs.length,enrollments:enrollments.length,audit:audit.length}};
      else if(route==='history') { const kind=new URLSearchParams(query).get('kind'); const items={devices,jobs,audit,enrollments:status(enrollments)}[kind]; if(!items) throw Error('Unknown history collection'); result={items,next_cursor:null,kind}; }
    } else if(route==='enrollments') {const item={id:id(),expires:now()+900,status:'active'};enrollments.unshift(item);record('enrollment.created',item.id);result={token:'DEMO_ONLY_NOT_A_REAL_ENROLLMENT_TOKEN',expires_in:900};}
    else if(route==='enrollments/revoke'||route==='credentials/revoke') {const list=route.startsWith('enrollments')?enrollments:credentials;const item=list.find(i=>i.id===body.id && i.status==='active');if(!item) throw Error('Active mock credential not found');item.status='revoked';record(route.startsWith('enrollments')?'enrollment.revoked':'credential.revoked',item.id);result={ok:true};}
    else if(route==='credentials') {if(!['viewer','operator','administrator'].includes(body.role)||!body.name?.trim()||!Number.isInteger(body.hours)||body.hours<1||body.hours>720) throw Error('Enter a name, role, and lifetime of 1 to 720 hours'); const item={id:id(),name:body.name,role:body.role,created:now(),expires:now()+body.hours*3600,status:'active'};credentials.unshift(item);record('credential.issued',item.id);result={...item,token:'DEMO_ONLY_NOT_A_REAL_ACCESS_TOKEN'};}
    else if(route==='jobs'||route==='revoke') {const device=devices.find(d=>d.id===body.device&&!d.revoked);if(!device) throw Error('Active mock device not found');if(route==='revoke'){device.revoked=1;record('device.revoked',device.id);}else{device.seen=now();device.inventory.packages.collected_at=now();jobs.unshift({id:id(),device:device.id,kind:'refresh_inventory',status:'completed',created:now(),result:'Simulated inventory received'});record('inventory.completed',device.id);}result={ok:true};}
    if(!result) throw Error('This operation is not available in the demo');
    return structuredClone(result);
  }};
})();
