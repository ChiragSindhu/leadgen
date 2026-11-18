/* ============ GLOBAL STATUS (WhatsApp + busy) ============ */
let BUSY=null,WST={loaded:0},SPT=0,SPB=0,SPQ=0,JT=0,WB=0,PB=0,RF=0,RD=null,WS='';
const SMS=()=>document.hidden?15000:1500;
const busyMsg=()=>BUSY=='send'?'A WhatsApp send is running. Wait or stop it first.':BUSY=='find'?'A search is running. Wait for it to finish first.':'';
const stMs=()=>document.hidden?30000:(BUSY||(WS!='ready'&&WS!='disabled'))?4000:10000;
function pollStatus(){clearTimeout(SPT);if(!$('#login').hidden)return;if(SPB){SPQ=1;return}SPB=1;
 api('wa/status').then(applyStatus).catch(()=>{}).finally(()=>{SPB=0;if(SPQ){SPQ=0;pollStatus();return}if($('#login').hidden)SPT=setTimeout(pollStatus,stMs())})}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)pollStatus()});
const drawIf=()=>{if(tab=='send'&&QM.loaded)drawSend()};
function applyStatus(s){if(!s)return;WST=Object.assign({},s,{loaded:1});WS=s.status;BUSY=s.busy||null;
 if(SV&&SV.running&&BUSY!='send'&&Date.now()-(SV.t0||0)>6000)endSend();
 if(JR&&!BUSY&&Date.now()-JT>6000){JR=false;afterJob();if(tab=='find')poller(poll,3000,true)}
 if(tab=='find'&&BUSY=='find'&&!JR)poller(poll,3000,true);
 if(tab=='send'&&BUSY=='send'&&!(SV&&SV.running)){SJV=-1;poller(pollSend,SMS,true)}
 paintPill();paintBanner();drawIf();if(tab=='set')paintConn();if(tab=='find')updFind()}
function paintPill(){const p=$('#wpill');if(!p)return;if(!WST.loaded||!$('#login').hidden){p.hidden=true;return}
 const m={ready:'Connected',qr:'Scan QR',starting:'Starting',error:'Error',disabled:'Off'};
 p.hidden=false;p.className=WST.status=='ready'?'':'warn';
 paint(p,`<span class="dot"></span><span class="wk">WhatsApp</span><span class="ws">${esc(m[WST.status]||'Checking')}${BUSY=='find'?' · searching':BUSY=='send'?' · sending':''}</span>`,1)}
function paintBanner(){const b=$('#d-ban');if(!b)return;if(!WST.loaded){paint(b,'',1);return}
 const ok=WST.status=='ready',L={ready:'WhatsApp connected',qr:'WhatsApp needs a QR scan',starting:'WhatsApp is starting',error:'WhatsApp error',disabled:'WhatsApp is off on this server'}[WST.status]||'Checking WhatsApp',
 t=BUSY=='send'?'Sending messages':BUSY=='find'?'Search running':L,
 sub=BUSY?L:ok?'':WST.status=='disabled'?'Manual sending still works':'Open Settings to fix',dst=BUSY=='send'?'send':BUSY=='find'?'find':'set';
 paint(b,`<div class="ban${ok||BUSY?'':' warn'}">${BUSY?'<span class="spinner sm"></span>':'<span class="dot"></span>'}<span class="bt"><b>${esc(t)}</b>${sub?` <span>· ${esc(sub)}</span>`:''}</span><button data-a="go" data-v="${dst}">${BUSY?'View':ok?'Settings':'Fix'}</button></div>`,1)}
function endSend(){SV=Object.assign({},SV,{running:false});drawIf();
 api('send/job?v=-1').then(j=>{if(j)SV=Object.assign({},j,{running:false});sendDone(SV);drawIf()}).catch(()=>sendDone(SV))}
function sendDone(j){j=j||{};afterMut();stale(/^runs/);
 toast(`Send finished: ${j.sent||0} sent, ${j.unconfirmed||0} unconfirmed, ${j.failed||0} failed`);
 swr('queue',{ttl:0,render:onQueue}).catch(()=>{});swr('stats',{ttl:0,render:fillDash}).catch(()=>{})}

