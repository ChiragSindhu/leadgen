/* ============ SEND ============ */
let Q=[],qi=0,QM={items:[],used:0,limit:0};const OP=new Set();
const sendSkel=()=>`<div class="glass focus"><div class="pager">${sk('40px','42px','border-radius:12px')}${sk('90px','16px')}${sk('40px','42px','border-radius:12px')}</div><div class="who">${sk('52px','52px','border-radius:14px')}<div style="flex:1">${sk('55%','22px','display:block;margin-bottom:6px')}${sk('35%','13px','display:block')}</div></div>
 <div class="lbl">Message you will send</div>${sk('92%','86px','display:block;margin-left:auto;border-radius:18px')}<div class="steps">${[1,2,3].map(()=>`<div class="stp">${sk('30px','30px','border-radius:50%;display:block;margin:0 auto 6px')}${sk('64px','11px')}</div>`).join('')}</div>${sk('100%','52px','display:block;border-radius:14px')}</div>`;
function shSend(){$('#p-send').innerHTML=head('Send','Three taps per lead')+`<div class="glass pad" style="margin-bottom:14px;padding:14px 18px"><div class="top" style="margin:0"><b>Sent today</b><span class="sub" id="sn">${sk('64px','14px')}</span></div><div class="bar"><i id="sb" style="width:0"></i></div></div><div id="sq">${sendSkel()}</div>`}
function onQueue(q){const pid=Q[qi]&&Q[qi].id;QM=q;Q=q.items||[];const k=pid==null?-1:Q.findIndex(x=>x.id===pid);qi=k>=0?k:(qi>=Q.length?0:qi);QM.loaded=1;drawSend()}
let SV=null,SJV=-1,SHOWN=null;const STG=new Map(),BL=new Map(),stg=id=>STG.get(id)||0;

async function pollSend(sig){const j=await api('send/job?v='+SJV,'GET',null,{signal:sig});if(!j)return !!(SV&&SV.running);
 SJV=j.v;const was=SV&&SV.running,fl=SV&&j.last&&j.last!==SV.last;j.t0=(SV&&SV.t0)||Date.now();SV=j;
 if(fl){const f=document.querySelector('#sq .focus');f&&f.classList.add('fly');setTimeout(drawSend,380)}else drawSend();
 if(was&&!j.running){sendDone(j);pollStatus()}
 return j.running}
async function startSend(body){if(BUSY)return toast(busyMsg());
 try{await api('send','POST',body);SJV=-1;SV={running:true,t0:Date.now(),sent:0,failed:0,unconfirmed:0,done:0,total:body.ids?body.ids.length:body.n,current:'',step:'Starting'};stale(/^runs/);drawSend();poller(pollSend,SMS,true);setTimeout(pollStatus,1200)}
 catch(e){e&&toast(e.message);pollStatus()}}
async function stopSend(){if(SV)SV.stop=true;drawSend();try{await api('send/stop','POST');toast('Stopping after the current lead')}catch(e){if(SV)SV.stop=false;drawSend();e&&toast(e.message)}}
const runCard=j=>`<div class="glass focus cin"><div class="who"><div class="av pulse">${ic('send')}</div><div style="min-width:0"><h2>${esc(j.current||'Starting')}</h2><div class="sub" style="display:flex;gap:8px;align-items:center"><span class="spinner"></span>${esc(j.step||'Working')}</div></div></div>
 <div class="bar"><i style="width:${j.total?Math.round((j.done||0)/j.total*100):0}%"></i></div>
 <div class="grid" style="margin:14px 0 0;grid-template-columns:repeat(auto-fit,minmax(78px,1fr))">${[['Sent',j.sent||0],['Failed',j.failed||0],['Unconfirmed',j.unconfirmed||0],['Left',Math.max(0,(j.total||0)-(j.done||0))]].map(x=>`<div><b style="font-size:22px">${x[1]}</b><div class="sub">${x[0]}</div></div>`).join('')}</div>
 <div class="acts" style="margin-top:16px"><button class="btn soft" data-a="go" data-v="runs">${ic('history')}Live log</button><button class="btn ghost" data-a="stopsend" ${j.stop?'disabled':''}>${ic('square')}${j.stop?'Stopping...':'Stop'}</button></div></div>`;

function drawSend(){const q=QM,l=Q[qi],ready=WS=='ready',hm=mon().length,run=SV&&SV.running,bz=!!BUSY&&!run;
 $('#sn').textContent=`${q.used+(run?SV.sent||0:0)} of ${q.limit}`;$('#sb').style.width=(q.limit?Math.min(100,(q.used+(run?SV.sent||0:0))/q.limit*100):0)+'%';
  if(!run&&!QM.loaded)return;
 if(run){paint($('#sq'),runCard(SV));return}
 let prev='';if(l)try{prev=decodeURIComponent(l.link.split('text=')[1]||'')}catch(e){prev=''}
 const id=l?esc(l.id):'',labels=hm?['Open WhatsApp','Send media','Mark as sent']:['Open & press send','Mark as sent'],st=l?stg(l.id):0,fin=labels.length-1,fresh=l&&SHOWN!==l.id;SHOWN=l?l.id:null;
 const open=`<a href="${l?esc(l.link):''}" target="_blank" rel="noopener" style="color:var(--sd);font-weight:600">Open again</a>`;
 const main=!l?'':st==0?`<a class="btn block big" target="_blank" rel="noopener" href="${esc(l.link)}" data-a="wa" data-id="${id}">${ic('message-circle')}Open WhatsApp</a><p class="hint">The message is already typed for you.</p>`
  :st<fin?`<button class="btn block big" data-a="media" data-id="${id}" ${bz||MWP?'disabled':''}>${mlab()}</button><p class="hint">Phone: pick WhatsApp in the share sheet, then the same chat. Computer: files download, drag them into the chat. ${open}</p>`
  :`<button class="btn sage block big" data-a="mk" data-id="${id}" data-v="messaged">${ic('check')}Done, I sent it</button><p class="hint">Back from WhatsApp? Tap above. ${open}</p>${hm?`<div style="text-align:center;margin-top:8px"><button class="btn soft sm" data-a="media" data-id="${id}" ${bz||MWP?'disabled':''}>${ic('image')}Send media again</button></div>`:''}`;
 const sd=(C.get('settings')||{}).d,tl=(sd&&sd.templates)||[];
 paint($('#sq'),(tl.length>1?`<div class="tsw"><label for="tsw">Template</label><select id="tsw">${tl.map(t=>`<option value="${esc(t.id)}" ${t.id==sd.active_template?'selected':''}>${esc(t.name)}</option>`).join('')}</select></div>`:'')+`<div class="tools"><button class="btn sage" data-a="sendall" ${ready&&Q.length&&!bz?'':'disabled'}>${ic('zap')}Send all (${Q.length})</button><span class="sub" style="align-self:center">${ready?'WhatsApp connected':WS=='disabled'?'WhatsApp auto-send is off. Manual sending still works.':'WhatsApp not connected. Set up in Settings.'}</span></div>`+(bz?`<div class="wl" style="margin:0 0 12px">${esc(busyMsg())}</div>`:'')+
 (l?`<div class="glass focus${fresh?' cin':''}"><div class="pager"><button class="btn soft" aria-label="Previous" data-a="step" data-v="-1">${ic('chevron-left')}</button><b>Lead ${qi+1} of ${Q.length}</b><button class="btn soft" aria-label="Skip to next" data-a="step" data-v="1">${ic('chevron-right')}</button></div>
 <div class="who"><div class="av">${initial(l.name)}</div><div style="min-width:0"><h2>${esc(l.name)}</h2><div class="sub">${esc(l.category)} · ${esc(l.phone)}</div></div></div>
 <div class="lbl">Message you will send${hm?` + ${hm} media`:''}</div><div class="bubble">${esc(prev)}</div>${hm?`<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;justify-content:flex-end">${mon().map(m=>m.type.startsWith('video')?`<div class="mth" style="display:grid;place-items:center">${ic('play-circle')}</div>`:`<img class="mth" loading="lazy" src="/api/media/${esc(m.id)}/file" alt="">`).join('')}</div>`:''}<div style="text-align:right"><button class="btn ghost sm" data-a="edit">${ic('pencil')}Edit message</button></div>
 <div class="steps">${labels.map((t,i)=>`<div class="stp ${i<st?'ok':i==st?'on':''}"><div class="n">${i<st?ic('check'):i+1}</div>${t}</div>`).join('')}</div>${main}
 <button class="btn soft block" style="margin-top:12px" data-a="auto" data-id="${id}" ${ready&&!bz?'':'disabled'}>${ic('zap')}Auto send this lead</button>
 <p class="hint">Opens the chat, sends your text${hm?` and ${hm} media file${hm>1?'s':''}`:''}, then marks it sent.${ready?'':WS=='disabled'?' Auto-send is off on this server.':' Connect WhatsApp in Settings first.'}</p>
 <div class="alt">${qi>0?`<button class="btn ghost sm" data-a="front" data-id="${id}">${ic('arrow-up')}Move to front</button>`:''}<button class="btn ghost sm" data-a="mk" data-id="${id}" data-v="bad_number">${ic('phone-off')}Wrong number</button><button class="btn ghost sm" data-a="mk" data-id="${id}" data-v="do_not_contact">${ic('ban')}Don't contact</button></div></div>
 <p class="hint">Use the arrows to skip. Skipped leads come back around.</p>`
 :`<div class="glass empty">${ic('party-popper')}<div>${q.used>=q.limit&&q.limit?'Daily limit reached. Rest now and continue tomorrow.':'No leads ready. Use Find to get more.'}</div></div>`))}

function openSendAll(){if(BUSY)return toast(busyMsg());const max=Math.min(Q.length,Math.max(0,QM.limit-QM.used),100);
 showSheet(GRAB+`<h1 style="font-size:20px">Send all automatically</h1><div class="sub">Text${mon().length?` + ${mon().length} media file(s)`:''} to each lead in the queue.</div>
 <div class="wl" style="margin-top:14px"><b>Read before you start</b><br>This drives WhatsApp Web, which is not an official sending method. WhatsApp can restrict or ban a number that messages many people who haven't contacted it. Use a number you can afford to lose.<br><br>Each lead takes about 30 to 40 seconds because of a deliberate delay, so 50 leads is roughly 30 minutes. Your server must stay on and connected. You can close this page. Progress is in Runs, and you can stop at any time.</div>
 <div class="field" style="margin-top:14px"><label>How many leads (max ${max})</label><input id="san" type="number" min="1" max="${max}" value="${Math.min(max,20)}"></div>
 <label class="ck"><input type="checkbox" onchange="$('#sago').disabled=!this.checked">I understand the risk</label>
 <div class="tools" style="margin:16px 0 0;justify-content:flex-end"><button class="btn soft" data-a="close">Cancel</button><button class="btn" id="sago" data-a="sendgo" disabled>${ic('zap')}Start sending</button></div>`);openDlg(D2)}
/* Why the old code failed: navigator.share() must run inside the tap's "user activation" (about 5 seconds).
   It downloaded the files first, so 4 videos took too long and the browser refused with "Must be handling a user gesture".
   Fix: download the files in the background as soon as they are known (warmMedia), and on tap call share() immediately. */
let MWP=null;
const mrdy=()=>mon().every(m=>BL.has(m.id));
function warmMedia(){if(MWP)return MWP;const todo=mon().filter(m=>!BL.has(m.id));if(!todo.length)return Promise.resolve();
 MWP=Promise.all(todo.map(async m=>{try{const r=await fetch('/api/media/'+enc(m.id)+'/file');if(!r.ok)throw 0;BL.set(m.id,await r.blob())}catch(e){}})).finally(()=>{MWP=null;drawIf()});
 drawIf();return MWP}
const mlab=()=>MWP?'<span class="spinner"></span>Preparing media...':`${ic('image')}Send media (${mon().length} file${mon().length>1?'s':''})`;
function dlFiles(files){files.forEach((f,i)=>setTimeout(()=>{const a=document.createElement('a');a.href=URL.createObjectURL(f);a.download=f.name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),4000)},i*350));
 toast(`${files.length} file${files.length>1?'s':''} saved to your Downloads folder. Drag ${files.length>1?'them':'it'} into the chat.`)}
function shareMedia(id){            // intentionally NOT async: no await may happen before share()
 if(BUSY)return toast(busyMsg());
 const ms=mon();if(!ms.length)return toast('No media is switched on. Tick files in Settings > Media.');
 if(MWP)return toast('Still preparing your media. Tap again in a moment.');
 if(!mrdy()){warmMedia();return toast('Loading your media. Tap again in a moment.')}
 const files=ms.map(m=>new File([BL.get(m.id)],m.name||m.id,{type:m.type})),done=()=>{STG.set(id,2);drawIf()};
 if(navigator.canShare&&navigator.canShare({files})){
  navigator.share({files}).then(()=>{toast('Shared. Pick WhatsApp and the same chat.');done()})
   .catch(e=>{if(e&&e.name=='AbortError')return;dlFiles(files);done()})      // share refused: fall back to saving the files
 }else{dlFiles(files);done()}}

async function mark(id,o){const i=Q.findIndex(x=>String(x.id)==id),it=Q[i];
 if(i>=0){Q.splice(i,1);if(o=='messaged')QM.used++;if(qi>=Q.length)qi=0;put('queue',QM);drawSend()}
 try{await api('leads/'+enc(id),'PATCH',{outreach:o});patchLeadCaches(id,{outreach:o});afterMut();
  toast(o=='messaged'?'Marked as sent':'Updated',async()=>{try{await api('leads/'+enc(id),'PATCH',{outreach:'new'});patchLeadCaches(id,{outreach:'new'});afterMut();swr('queue',{ttl:0,render:onQueue}).catch(()=>{})}catch(e){e&&toast(e.message)}})}
 catch(e){if(i>=0){Q.splice(i,0,it);if(o=='messaged')QM.used--;put('queue',QM);drawSend()}e&&toast(e.message);return}
 swr('queue',{ttl:0,render:onQueue}).catch(()=>{})}

