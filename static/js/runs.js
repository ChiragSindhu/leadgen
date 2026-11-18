/* ============ RUNS ============ */
const RN={first:[],old:[],total:0,busy:false},RPS=30;
function shRuns(){$('#p-runs').innerHTML=head('Runs','Every search and what happened')+`<div id="rl" class="glass list">${skRows(5)}</div><div id="rft" style="padding:14px 0;text-align:center"></div>`;
 new IntersectionObserver(es=>{if(es[0].isIntersecting)runMore()},{rootMargin:'500px'}).observe($('#rft'))}
const runRow=r=>`<div class="lead" data-a="run" data-id="${esc(r.id)}"><div class="av">${ic(r.source=='whatsapp'?'send':'search')}</div><div class="t"><b>${esc(r.query)}${r.location?' in '+esc(r.location):''}</b><small>${esc(when(r.at))} · ${esc(r.status||'done')}</small></div><span class="score">${esc(r.source=='whatsapp'?r.added:r.fetched)}</span><span class="chev" style="display:block">${ic('chevron-right')}</span></div>`;
 function fillRuns(d,older){
 if(!older){RN.first=d.items;RN.total=d.total;const ids=new Set(d.items.map(r=>r.id));RN.old=RN.old.filter(r=>!ids.has(r.id))}
 const all=RN.first.concat(RN.old),more=all.length<RN.total;
 paint($('#rl'),all.length?all.map(runRow).join(''):`<div class="empty">${ic('history')}<div>No runs yet. Start one from Find.</div></div>`);
 paint($('#rft'),more?`<button class="btn soft" data-a="runmore" ${RN.busy?'disabled':''}>${RN.busy?'Loading...':`Load more (${all.length} of ${RN.total})`}</button>`:all.length?`<span class="sub">All ${RN.total} runs shown</span>`:'',1)}
async function runMore(){const n=RN.first.length+RN.old.length;if(RN.busy||n>=RN.total||tab!='runs')return;RN.busy=true;fillRuns(null,1);
 try{const d=await api(`runs?limit=${RPS}&offset=${n}`),ids=new Set(RN.first.concat(RN.old).map(r=>r.id));
  RN.old=RN.old.concat(d.items.filter(r=>!ids.has(r.id)));RN.total=d.total}
 catch(e){e&&toast(e.message)}finally{RN.busy=false;fillRuns(null,1);setTimeout(()=>{const f=$('#rft');f&&f.getBoundingClientRect().top<innerHeight+500&&runMore()},50)}}
async function loadRuns(){const live=d=>d.items.some(r=>r.status=='running');
 const d=await swr('runs',{ttl:4000,render:d=>fillRuns(d)});
 if(tab=='runs'&&live(d))poller(async sig=>{const r=await fetchC('runs',{signal:sig});if(r.changed)fillRuns(r.d);return live(r.d)},5000)}
const runSkel=()=>GRAB+`<div>${sk('70%','22px','display:block;margin-bottom:8px')}${sk('45%','13px','display:block')}</div><div class="grid" style="margin:16px 0;grid-template-columns:repeat(4,1fr)">${[1,2,3,4].map(()=>`<div>${sk('36px','24px','display:block;margin-bottom:6px')}${sk('48px','11px','display:block')}</div>`).join('')}</div><label>Events</label>${[1,2,3,4,5].map(()=>sk('100%','14px','display:block;margin:12px 0')).join('')}<button class="btn soft block" style="margin-top:12px" data-a="close">Close</button>`;
/* event class: ok = confirmed, unc = unconfirmed, fail = failed (WhatsApp runs); w = plain warning */
const evCls=(x,wa)=>!wa?(x.kind=='warn'?'w':''):/^Sent to .*\(confirmed\)/i.test(x.text)?'ok':/never confirmed/i.test(x.text)?'unc':x.kind=='warn'?'fail':'';
const EVT={ok:'<span class="tag">Sent</span> ',unc:'<span class="tag w">Unconfirmed</span> ',fail:'<span class="tag e">Failed</span> '};
function fillRun(d){RD=d;const r=d.run,e=d.events||[],wa=r.source=='whatsapp',cl=e.map(x=>evCls(x,wa)),unc=cl.filter(c=>c=='unc').length,bad=cl.filter(c=>c&&c!='ok').length;
 const rows=e.map((x,i)=>[x,cl[i]]).filter(p=>!RF||(p[1]&&p[1]!='ok')).slice(-200).reverse();
 showSheet(GRAB+`<h1 style="font-size:20px">${esc(r.query)}${r.location?' in '+esc(r.location):''}</h1><div class="sub">${esc(when(r.at))} · ${esc(r.status||'done')}${r.finished_at?' · finished '+esc(when(r.finished_at)):''}</div>
 <div class="grid" style="margin:16px 0;grid-template-columns:repeat(4,1fr)">${(wa?[['Asked',r.requested||'-'],['Queued',r.fetched],['Sent',r.added],['Failed',r.changed]]:[['Asked',r.requested||'-'],['Found',r.fetched],['New',r.added],['Updated',r.changed]]).map(x=>`<div><b style="font-size:22px">${esc(x[1])}</b><div class="sub">${x[0]}</div></div>`).join('')}</div>
 ${wa&&unc?`<p class="sub" style="color:#9a5b12;margin:-6px 0 12px">${unc} sent but not confirmed by WhatsApp</p>`:''}
 ${r.error?`<p class="sub" style="color:var(--tom)">${esc(r.error)}</p>`:''}<div class="top" style="margin:14px 0 6px"><label style="margin:0">Events</label>${e.length?`<button class="btn ${RF?'sage':'soft'} sm" data-a="rfilt">${ic('alert-triangle')}${RF?'Showing problems':'Problems only'}${bad?' ('+bad+')':''}</button>`:''}</div>
 <ul class="tl">${rows.length?rows.map(p=>`<li><time>${hm(p[0].at)}</time><span class="${p[1]=='fail'||p[1]=='w'?'w':p[1]=='unc'?'u':''}">${EVT[p[1]]||''}${esc(p[0].text)}</span></li>`).join(''):`<li class="sub">${e.length?'No problems in this run.':'No events recorded for this run.'}</li>`}</ul>
 <button class="btn soft block" style="margin-top:12px" data-a="close">Close</button>`,1)}
function openRun(id){RF=0;const my=++DS;clearTimeout(RT);showSheet(runSkel(),0);openDlg(D2);const p='runs/'+id;
 const loop=async()=>{if(my!==DS||!D2.open)return;let more=false;
  try{if(document.hidden)more=true;else{const r=await fetchC(p);if(my!==DS)return;if(r.changed)fillRun(r.d);more=r.d.run.status=='running'}}catch(e){}
  if(more&&my===DS)RT=setTimeout(loop,4000)};
 swr(p,{ttl:3000,ok:()=>my===DS,render:d=>{if(my===DS)fillRun(d)}}).then(d=>{if(my===DS&&d&&d.run&&d.run.status=='running')RT=setTimeout(loop,4000)}).catch(e=>{if(e&&my===DS)showSheet(errSheet(e.message))})}

