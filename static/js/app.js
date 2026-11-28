/* ============ events (delegated, registered once) ============ */
const A={
 go:e=>go(e.dataset.v),add:()=>openAdd(),open:e=>SELM?toggleSel(e.dataset.id):openLead(e.dataset.id),
 selmode:()=>SELM?selOff():selOn(),selall:()=>{const all=LP.items.length&&SEL.size>=LP.items.length&&!SELALL;if(all||SELALL){SEL.clear();SELALL=0}else LP.items.forEach(l=>SEL.add(String(l.id)));renderLeads()},selmatch:()=>{SELALL=1;renderLeads()},bulkdel:()=>bulk('delete'),del:e=>del(e.dataset.id),
 reload:()=>loadLeads(),statgo:e=>{const t=DT[+e.dataset.i];t&&goLeads(t[3])},
 lfpanel:()=>{const p=$('#lfp');p.hidden=!p.hidden},lftog:e=>{const k=e.dataset.k;LF[k]=LF[k]?0:1;lfChanged()},lfclr:e=>lfClear(e.dataset.k),lfall:()=>lfClearAll(),
 close:e=>closeDlg(e.closest('dialog')),ldel:e=>{closeDlg(D2);del(e.dataset.id)},lsave:e=>saveLead(e.dataset.id,e),
 run:e=>openRun(e.dataset.id),
 src:e=>{keep();FS=e.dataset.v;document.querySelectorAll('#fseg button').forEach(b=>b.classList.toggle('on',b.dataset.v==FS));renderForm()},
 fill:e=>{const t=$('#'+e.dataset.t);if(t){t.value=e.dataset.v;keep()}},find:()=>startFind(),
 step:e=>{if(Q.length){qi=(qi+ +e.dataset.v+Q.length)%Q.length;drawSend()}},
 mk:e=>mark(e.dataset.id,e.dataset.v),edit:()=>go('set'),
 tsave:e=>saveTpl(e,0),tuse:e=>saveTpl(e,1),tdup:()=>dupTpl(),tdel:()=>delTpl(),tpick:e=>pickTpl(e.dataset.id),tnew:()=>{TNEW=!TNEW;paintTpl(1)},tadd:e=>addTpl(+e.dataset.i),savlim:e=>saveLimit(e),logout:()=>api('logout','POST').then(()=>location.reload()).catch(()=>{}),
 undo:()=>{const u=window._u;window._u=null;if(u){u();toast('Restored')}},
 adtab:e=>{if(AD.busy||AD.m==e.dataset.v)return;AD.m=e.dataset.v;document.querySelectorAll('#adseg button').forEach(b=>b.classList.toggle('on',b.dataset.v==AD.m));adBody();adUpdate()},
 adadd:()=>{AD.rows.push({});adRows();adUpdate();const f=document.querySelector('#adrows .brow:last-child input');f&&f.focus()},
 adrm:e=>{AD.rows.splice(+e.dataset.i,1);if(!AD.rows.length)AD.rows.push({});adRows();adUpdate()},
 adgo:()=>adGo(),admore:()=>{AD.res=null;adBuild()}};
Object.assign(A,{
 wa:()=>{const l=Q[qi];if(l){STG.set(l.id,Math.max(1,stg(l.id)));setTimeout(drawSend,500)}},
 media:e=>shareMedia(e.dataset.id,e),auto:e=>{if(e.closest('dialog')){closeDlg(D2);go('send')}startSend({ids:[e.dataset.id]})},sendall:()=>openSendAll(),
 sendgo:()=>{const n=+$('#san').value;closeDlg(D2);startSend({n})},stopsend:()=>stopSend(),
 rmmedia:e=>rmMedia(e.dataset.id),
 tstop:()=>{const tp=$('#tp');if(!tp)return;if(/\bstop\b/i.test(tp.value))return toast('A STOP line is already there');tp.value=tp.value.replace(/\s+$/,'')+'\n\nReply STOP to opt out.';updTpl()},
 tps:e=>{TPS=e.dataset.v;updTpl()},
 copytxt:async e=>{const c=C.get('leads/'+enc(e.dataset.id)),lk=(c&&c.d&&c.d.link)||'';let t='';try{t=decodeURIComponent(lk.split('text=')[1]||'')}catch(x){}if(!t)return toast('No message to copy');try{await navigator.clipboard.writeText(t);toast('Message copied')}catch(x){toast('Could not copy. Your browser blocked it.')}},front:async e=>{try{await api('leads/'+enc(e.dataset.id)+'/front','POST');afterMut();await swr('queue',{ttl:0,render:onQueue});toast('Moved to front of the queue')}catch(x){x&&toast(x.message)}},
 rfilt:()=>{RF=RF?0:1;RD&&fillRun(RD)},wsync:()=>waSync(),wreset:()=>waReset(),psave:e=>savePipe(e),
 mtog:e=>{const m=ML.find(x=>x.id==e.dataset.id);m&&togMedia(m.id,!m.on)},
 mprev:e=>{const m=ML.find(x=>x.id==e.dataset.id);if(!m)return;const u='/api/media/'+enc(m.id)+'/file';
  showSheet(GRAB+`<div style="border-radius:14px;overflow:hidden;background:#000">${m.type.startsWith('video')?`<video src="${u}" controls playsinline style="width:100%;max-height:60vh"></video>`:`<img src="${u}" alt="" style="width:100%;max-height:60vh;object-fit:contain">`}</div><p class="sub" style="margin:10px 0">${esc(m.name)} · ${mb(m.size)}</p><button class="btn soft block" data-a="close">Close</button>`,0);openDlg(D2)},
 ins:e=>{const t=$('#tp');if(!t)return;const s=t.selectionStart??t.value.length;t.setRangeText('{'+e.dataset.v+'}',s,t.selectionEnd??s,'end');t.focus();updTpl()}});
 Object.assign(A,agentActions(),{rk:e=>{RK=e.dataset.v;document.querySelectorAll('#rseg button').forEach(b=>b.classList.toggle('on',b.dataset.v==RK));const c=C.get('runs');c&&fillRuns(c.d)},stab:stabAction})
document.addEventListener('change',e=>{const t=e.target;
 if(t.id=='mfile'){const f=[...t.files];t.value='';upMedia(f)}});
document.addEventListener('toggle',e=>{if(e.target.id=='mdet')MO=e.target.open},true);
document.addEventListener('change',e=>{if(e.target.id=='bst'&&e.target.value)bulk('status',e.target.value);if(e.target.id=='tsw')useTpl(e.target.value)});
document.addEventListener('change',e=>{const k=e.target.dataset&&e.target.dataset.lf;if(!k)return;const v=e.target.value;LF[k]=(k=='sc'||k=='rt')?Number(v):v;lfChanged()});
document.addEventListener('click',e=>{const el=e.target.closest('[data-a]');if(!el)return;const f=A[el.dataset.a];if(f)f(el,e)});
document.addEventListener('change',e=>{const t=e.target;
 if(t.matches&&t.matches('select[data-a="st"]'))upd(t.dataset.id,t.value);
 else if(t.id=='adskip'){AD.skip=t.checked?1:0;adUpdate()}});
document.addEventListener('input',e=>{const t=e.target;
 if(t.closest('#adc')){const row=t.closest('.brow');if(t.dataset.f&&row){const r=AD.rows[+row.dataset.i];if(r)r[t.dataset.f]=t.value;adSched()}else if(t.id=='adbulk'){AD.bulk=t.value;adSched()}}
 else if(t.closest('#p-find'))keep();else if(t.id=='tp'||t.id=='tn')updTpl()});


const SH={dash:shDash,leads:shLeads,agent:shAgent,find:shFind,runs:shRuns,send:shSend,set:shSet},LDR={dash:loadDash,leads:loadLeads,agent:loadAgent,find:loadFind,runs:loadRuns,send:loadSend,set:loadSet};
draw();go('dash');pollStatus()
