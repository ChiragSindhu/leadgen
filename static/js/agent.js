/* ============ BOSS (agent) ============ */
const AGS={msgs:[{role:'assistant',content:'yo Vansh Boss, what are we cooking today?',local:1}],busy:0,v:-1,plan:null,sug:[],think:'thinking'};
const AGQ=['How am I doing today?','Find 200 real estate leads in Gurugram','Write a short template for gyms','Stop the search'];
/* safety net: never show leaked "lead_in:" / "warning:" labels or tool-call text like propose_send(query="x") */
const AG_TOOLS='find_lead|plan_campaign|propose_send|queue_front|next_actions|search_status|remember|forget|get_overview|run_insights|search_leads|suggest_areas|start_multi_find|stop_search|list_templates|save_template|activate_template|delete_template|update_settings|ask_user';
const agClean=t=>String(t==null?'':t).replace(/\[ctx:[\s\S]*$/,'').replace(new RegExp('\\b('+AG_TOOLS+')\\s*\\([\\s\\S]*\\)\\s*$','gm'),'').replace(/^(lead_in|warning)\s*:\s*/gim,'').trim();
function shAgent(){$('#p-agent').innerHTML=head('Boss','Your AI chief of staff')+`<div id="agplan" class="agplan"></div>
 <div class="glass agchat"><div id="agmsgs" class="agmsgs"></div><div class="chips agq" id="agq">${AGQ.map(q=>`<button data-a="agchip" data-q="${esc(q)}">${esc(q)}</button>`).join('')}</div>
 <div id="agmem" style="padding:0 24px 8px;display:flex;justify-content:space-between;align-items:center"></div><div class="agin"><textarea id="agtx" rows="1" placeholder="e.g. Find 200 PGs in Gurugram"></textarea><button class="btn" data-a="agsend" aria-label="Send">${ic('arrow-up')}</button></div></div>`;agDraw()}
function md(s){s=esc(s);const L=s.split('\n'),o=[],LI=/^\s*([-*]|\d+\.)\s+/;let i=0;
 const inl=t=>t.replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<b>$1</b>').replace(/(^|[\s(])\*([^*\s][^*]*)\*/g,'$1<i>$2</i>').replace(/(https?:\/\/[^\s<)]+)/g,'<a href="$1" target="_blank" rel="noopener">$1</a>');
 const cells=r=>r.trim().replace(/^\||\|$/g,'').split('|').map(c=>inl(c.trim()));
 while(i<L.length){const l=L[i];
  if(/^\s*\|.*\|\s*$/.test(l)&&/^\s*\|[\s:|-]+\|\s*$/.test(L[i+1]||'')){const h=l,rs=[];i+=2;while(i<L.length&&/^\s*\|/.test(L[i]))rs.push(L[i++]);
   o.push('<div class="mdt"><table><thead><tr>'+cells(h).map(c=>`<th>${c}</th>`).join('')+'</tr></thead><tbody>'+rs.map(r=>'<tr>'+cells(r).map(c=>`<td>${c}</td>`).join('')+'</tr>').join('')+'</tbody></table></div>');continue}
  if(LI.test(l)){const ord=/^\s*\d+\./.test(l),it=[];while(i<L.length&&LI.test(L[i]))it.push('<li>'+inl(L[i++].replace(LI,''))+'</li>');o.push(`<${ord?'ol':'ul'}>${it.join('')}</${ord?'ol':'ul'}>`);continue}
  const h=l.match(/^#{1,4}\s+(.*)/);if(h)o.push('<h4>'+inl(h[1])+'</h4>');else if(l.trim())o.push('<p>'+inl(l)+'</p>');i++}
 return o.join('')}
const agBlock=b=>{
 if(b.t=='stats')return `<div class="agb stats">${b.items.map(x=>`<div><b>${esc(x[1])}</b><small>${esc(x[0])}</small></div>`).join('')}</div>`;
 if(b.t=='leads')return `<div class="agb"><div class="agbh">${b.total} match${b.total==1?'':'es'}${b.items.length<b.total?' · top '+b.items.length:''}</div>${b.items.map(l=>`<div class="lead" data-a="agopen" data-id="${esc(l.id)}"><div class="av">${initial(l.name)}</div><div class="t"><b>${esc(l.name)}</b><small>${esc(l.category)} · ${esc(l.phone||'No phone')} · ${esc(l.outreach)}</small></div><span class="score ${l.score>=70?'hi':''}">${esc(l.score)}</span></div>`).join('')}<div style="padding:10px 12px"><button class="btn soft sm" data-a="go" data-v="leads">${ic('users')}Open Leads</button></div></div>`;
 if(b.t=='coverage')return `<div class="agb" style="padding:14px">${Object.entries(b.data).map(([k,v])=>`<div class="agbh" style="padding:0">${esc(k)}</div><div class="agareas" style="margin:8px 0 14px">${v.map(x=>`<span class="${b.saturated.includes(k+' / '+x.area)?'sat':'ok'}" title="${x.runs} run(s), last ${esc(x.last)}">${esc(x.area)} · ${x.new}</span>`).join('')}</div>`).join('')||'<span class="sub">No searches yet.</span>'}${b.saturated.length?'<small class="sub">Struck-through areas look exhausted.</small>':''}</div>`;
 if(b.t=='ask')return `<div class="agb" style="padding:14px">${b.questions.map((q,qi)=>`<div class="agbh" style="padding:0 0 8px">${esc(q.question)}${q.multi?' <span style="text-transform:none;letter-spacing:0">(pick any)</span>':''}</div>${q.text?`<input data-agt="${esc(b.uid)}|${qi}" placeholder="Type here" value="${esc((b.txt&&b.txt[qi])||'')}" ${b.done?'disabled':''} style="margin:0 0 14px">`:''}<div class="chips" style="margin:0 0 14px">${(q.options||[]).map((o,oi)=>`<button class="${(b.sel&&b.sel[qi]||[]).includes(oi)?'on':''}" data-a="agpick" data-u="${esc(b.uid)}" data-q="${qi}" data-o="${oi}" ${b.done?'disabled':''}>${esc(o)}</button>`).join('')}</div>`).join('')}<div class="tools" style="margin:0">${b.done?`<span class="tag">${esc(b.done)}</span>`:`<button class="btn sm" data-a="agcont" data-u="${esc(b.uid)}" ${agReady(b)?'':'disabled'}>Continue</button><button class="btn soft sm" data-a="agother">Something else...</button>`}</div></div>`;
 if(b.t=='confirm')return `<div class="agb" style="padding:14px"><div class="agbh" style="padding:0 0 8px">${esc(b.title)}</div>${b.lines.map(l=>`<div class="sub" style="margin:2px 0">${esc(l)}</div>`).join('')}<div class="tools" style="margin:12px 0 0">${b.done?`<span class="tag">${esc(b.done)}</span>`:`<button class="btn sm" data-a="agok" data-u="${esc(b.uid)}">${ic('check')}Approve</button><button class="btn soft sm" data-a="agno" data-u="${esc(b.uid)}">Cancel</button>`}</div></div>`;
 if(b.t=='tpl')return `<div class="agb" style="padding:14px"><div class="agbh" style="padding:0 0 8px;display:flex;justify-content:space-between">${esc(b.name)}${b.active?'<span class="tag">Active</span>':''}</div><div class="bubble" style="max-width:100%;margin:0 0 12px">${esc(b.body)}</div><div class="tools" style="margin:0">${b.active?'':`<button class="btn sm" data-a="agtpl" data-id="${esc(b.id)}">${ic('check')}Use this template</button>`}<button class="btn soft sm" data-a="go" data-v="set">${ic('pencil')}Edit in Settings</button></div></div>`;
 return ''};
function agDraw(){const el=$('#agmsgs');if(!el)return;
 el.innerHTML=AGS.msgs.map(m=>m.role=='user'?`<div class="agm u">${esc(m.content)}</div>`:`<div class="agm b${m.err?' err':''}">${md(m.err?m.content:agClean(m.content))}${(m.blocks||[]).map(agBlock).join('')}</div>`).join('')+(AGS.busy?`<div class="agm b think"><span class="dots"><i></i><i></i><i></i></span><span id="agthink">${esc(AGS.think||'thinking')}</span></div>`:'');
 draw();el.scrollTop=el.scrollHeight;agChips();const b=document.querySelector('[data-a=agsend]');b&&b.toggleAttribute('disabled',!!AGS.busy)}
function agPlanCard(p){if(!p||!p.running)return '';
 const pct=p.target?Math.min(100,Math.round(p.added/p.target*100)):0,dn=new Map((p.done||[]).map(d=>[d.area,d]));
 return `<div class="glass pad"><div class="top" style="margin:0 0 10px"><div style="display:flex;gap:10px;align-items:center">${p.running?'<div class="spinner"></div>':ic('check-circle-2')}<b>${esc(p.category)} in ${esc(p.city)}</b></div><span class="sub">${p.added} / ${p.target} new</span></div>
 <div class="bar"><i style="width:${pct}%"></i></div><p class="sub" style="margin:8px 0 0">${esc(p.msg)}</p>
 <div class="agareas">${p.areas.map((a,i)=>{const d=dn.get(a);return `<span class="${d?(d.ok?'ok':''):(p.running&&i==p.i?'now':'')}">${esc(a)}${d?' · '+d.new:''}</span>`}).join('')}</div>
 <div class="tools" style="margin:12px 0 0">${p.running?`<button class="btn soft sm" data-a="agstop">${ic('square')}Stop after this area</button>`:''}<button class="btn soft sm" data-a="go" data-v="runs">${ic('history')}Run log</button></div></div>`}
async function agPoll(sig){const j=await api('agent/plan?v='+AGS.v,'GET',null,{signal:sig});if(!j)return !!(AGS.plan&&AGS.plan.running);
 const was=AGS.plan&&AGS.plan.running;AGS.v=j.v;AGS.plan=j;paint($('#agplan'),agPlanCard(j));if(was&&!j.running){afterJob();pollStatus();
  AGS.msgs.push({role:'assistant',local:1,content:`search wrapped bro. **${j.added}** new leads across ${j.done.length} areas. ${j.added<j.target?'missed the '+j.target+' target tho, areas ran dry. try another city or type?':'target hit, go cook in Send.'}`});agDraw()}return j.running}
function loadAgent(){AGS.v=-1;poller(agPoll,3000,true);
 return api('agent/history').then(h=>{if(h.messages.length)AGS.msgs=h.messages.map(m=>Object.assign(m,{blocks:(m.blocks||[]).map(b=>(b.t=='confirm'||b.t=='ask')?Object.assign(b,{done:'expired',uid:'x'}):b)}));AGS.mem=h.memory||[];agDraw();agMem()})}
const agMem=()=>{const e=$('#agmem');if(e)e.innerHTML=`<small class="sub">${AGS.mem&&AGS.mem.length?'Boss remembers '+AGS.mem.length+' thing'+(AGS.mem.length>1?'s':''):'Boss has no memories yet'}</small><span><button class="btn ghost sm" data-a="agreset">New chat</button><button class="btn ghost sm" data-a="agwipe">Forget all</button></span>`}
/* chips row: Boss's "I can do that for you" suggestions when there are any, otherwise the rotating ideas */
function agChips(){const q=$('#agq');if(!q)return;
 if(AGS.sug&&AGS.sug.length&&!AGS.busy){q.innerHTML='<small class="sub" style="align-self:center">Boss can do:</small>'+AGS.sug.map(s=>`<button class="sug" data-a="agsug" data-q="${esc(s.msg)}">${esc(s.label)}</button>`).join('');return}
 const p=agPool();q.innerHTML=[...new Set([0,1,2,3].map(k=>p[(agI+k*2)%p.length]))].map(x=>`<button data-a="agchip" data-q="${esc(x)}">${esc(x)}</button>`).join('')}
async function agSend(t){const tx=$('#agtx');t=(t||(tx&&tx.value)||'').trim();if(!t||AGS.busy)return;
 AGS.msgs.push({role:'user',content:t});AGS.busy=1;AGS.sug=[];AGS.think='thinking';if(tx)tx.value='';agDraw();
 /* live status: what Boss is doing right now (reading templates, building the send card...) */
 const tp=setInterval(async()=>{try{const j=await api('agent/thinking');if(j&&j.on&&j.step){AGS.think=j.step;const e=$('#agthink');if(e)e.textContent=j.step}}catch(x){}},600);
 try{const r=await api('agent/chat','POST',{message:t});
  if(r.trace){console.groupCollapsed('Boss debug · '+r.trace.length+' events');console.table(r.trace);console.groupEnd()}
  AGS.msgs.push({role:'assistant',content:r.reply||'done.',acts:r.actions,blocks:(r.blocks||[]).map(b=>Object.assign(b,{uid:Math.random().toString(36).slice(2)}))});
  AGS.sug=r.suggest||[];
  if((r.refresh||[]).length){stale(new RegExp('^('+r.refresh.join('|')+'|wa)'));
   if(r.refresh.includes('settings')){C.delete('wa/config');if(INIT.set){TL.edit='';loadSet()}}
   if(INIT.dash)swr('stats',{ttl:0,render:fillDash}).catch(()=>{});if(INIT.send)swr('queue',{ttl:0,render:onQueue}).catch(()=>{});
   if(INIT.runs)stale(/^runs/);toast('Boss updated your app')}
  if((r.actions||[]).includes('start_multi_find')){AGS.v=-1;poller(agPoll,3000,true);setTimeout(pollStatus,800)}
  api('agent/history').then(h=>{AGS.mem=h.memory;agMem()}).catch(()=>{})}
 catch(e){e&&AGS.msgs.push({role:'assistant',content:e.message||'Boss hit an error, try again',err:1})}
 finally{clearInterval(tp);AGS.busy=0;agDraw()}}
const agFind=u=>{for(const m of AGS.msgs)for(const b of m.blocks||[])if(b.uid==u)return b};
const agentActions=()=>({agno:e=>{const b=agFind(e.dataset.u);if(b){b.done='cancelled';agDraw()}},
 agok:e=>{const b=agFind(e.dataset.u);if(!b||b.done)return;b.done='approved';agDraw();
  if(b.kind=='send'){go('send');setTimeout(()=>startSend(b.payload),300);return}
  api('agent/approve','POST',{id:b.id}).then(r=>{b.done='done';
   if(b.kind=='act'){agRefresh(r.refresh);if(r.block)AGS.msgs.push({role:'assistant',local:1,content:'done.',blocks:[Object.assign(r.block,{uid:Math.random().toString(36).slice(2)})]})}
   if(b.kind=='find'||(r.result&&r.result.started)){AGS.v=-1;poller(agPoll,3000,true);setTimeout(pollStatus,800);toast('Search started')}
   agDraw()}).catch(x=>{b.done='failed';agDraw();x&&toast(x.message)})},
 agpick:e=>{const b=agFind(e.dataset.u);if(!b||b.done)return;const q=+e.dataset.q,o=+e.dataset.o;b.sel=b.sel||[];const cur=b.sel[q]||[];b.sel[q]=b.questions[q].multi?(cur.includes(o)?cur.filter(x=>x!=o):cur.concat(o)):[o];agDraw()},
 agcont:e=>{const b=agFind(e.dataset.u);if(!b||b.done||!agReady(b))return;b.done='answered';agSend(b.questions.map((q,i)=>q.question+' '+(q.text?b.txt[i].trim():b.sel[i].map(o=>q.options[o]).join(', '))).join('\n'))},
 agother:()=>{const t=$('#agtx');if(t){t.placeholder='Type your answer...';t.focus()}},
 agwipe:()=>{if(!confirm('Wipe this chat AND everything Boss remembers?'))return;api('agent/reset','POST',{memory:true}).then(()=>{AGS.msgs=[{role:'assistant',content:'clean slate bro. memory wiped.',local:1}];AGS.mem=[];AGS.sug=[];agDraw();agMem()})},agreset:()=>api('agent/reset','POST').then(()=>{AGS.msgs=[{role:'assistant',content:'fresh chat bro. i still remember the important stuff.',local:1}];AGS.sug=[];agDraw()}),homeask:()=>{const q=$('#hq'),t=q&&q.value.trim();if(!t)return;q.value='';go('agent');setTimeout(()=>agSend(t),150)},agsend:()=>agSend(),agchip:e=>{const t=$('#agtx');if(t){t.value=e.dataset.q;t.focus()}},agsug:e=>agSend(e.dataset.q),agopen:e=>openLead(e.dataset.id),agtpl:e=>useTpl(e.dataset.id),agstop:()=>api('agent/stop','POST').then(()=>toast('Stopping after this area')).catch(e=>e&&toast(e.message))});
document.addEventListener('keydown',e=>{if(e.target.id=='hq'&&e.key=='Enter'){e.preventDefault();A.homeask()}if(e.target.id=='agtx'&&e.key=='Enter'&&!e.shiftKey){e.preventDefault();agSend()}});


/* ============ SETTINGS: sections (patch shSet + add action) ============ */
const SSEC=[['msg','Messages'],['media','Media'],['wa','WhatsApp'],['pipe','Pipeline'],['acct','Account']];
let SSK='msg';
const setSeg=()=>`<div class="seg" id="sset">${SSEC.map(x=>`<button data-a="stab" data-v="${x[0]}" class="${x[0]==SSK?'on':''}">${x[1]}</button>`).join('')}</div>`;
/* shSet: put setSeg() right after head(...) and set dataset: $('#p-set').dataset.s=SSK; */
const stabAction=e=>{SSK=e.dataset.v;$('#p-set').dataset.s=SSK;document.querySelectorAll('#sset button').forEach(b=>b.classList.toggle('on',b.dataset.v==SSK))};

/* rotating ideas: placeholder + chips change every 4s, context-aware (suggestion chips win when present) */
const AGP={idle:['Find 100 gyms in Noida','Write a template for clinics','What areas are saturated?','Show my warm leads','Who should I message first?','Set daily limit to 30','What should I do next?','Make my template funnier','Find 50 PGs in Gurugram','How am I doing today?'],run:['How is the search going?','Stop the search','Which areas are done?','Any new leads yet?']};
let agI=0;const agPool=()=>AGS.plan&&AGS.plan.running?AGP.run.concat(AGP.idle.slice(0,4)):AGP.idle;
function agRot(){if(tab!='agent'||document.hidden)return;const tx=$('#agtx');if(!tx)return;const p=agPool();agI=(agI+1)%p.length;
 if(document.activeElement===tx||tx.value)return;tx.placeholder='Try: '+p[agI];
 if(!AGS.busy&&!(AGS.sug&&AGS.sug.length))agChips()}
if(!AGS.ti)AGS.ti=setInterval(agRot,4000);

const agReady=b=>b.questions.every((q,i)=>q.text?!!(b.txt&&(b.txt[i]||'').trim()):!!(b.sel&&b.sel[i]&&b.sel[i].length));
function agRefresh(list){list=list||[];if(!list.length)return;stale(new RegExp('^('+list.join('|')+'|wa)'));
 if(list.includes('settings')){C.delete('wa/config');if(INIT.set){TL.edit='';loadSet()}}
 if(INIT.dash)swr('stats',{ttl:0,render:fillDash}).catch(()=>{});if(INIT.send)swr('queue',{ttl:0,render:onQueue}).catch(()=>{});toast('Done. App updated')}

document.addEventListener('input',e=>{const d=e.target.dataset&&e.target.dataset.agt;if(!d)return;const[u,qi]=d.split('|'),b=agFind(u);if(!b)return;
 b.txt=b.txt||[];b.txt[+qi]=e.target.value;const btn=e.target.closest('.agb').querySelector('[data-a=agcont]');btn&&btn.toggleAttribute('disabled',!agReady(b))});