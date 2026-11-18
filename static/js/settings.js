/* ============ SETTINGS ============ */
const setSkel=()=>`${sk('120px','13px','display:block;margin-bottom:8px')}${sk('100%','120px','display:block;margin-bottom:14px;border-radius:12px')}${sk('90px','13px','display:block;margin-bottom:8px')}${sk('100%','44px','display:block;margin-bottom:14px;border-radius:12px')}<div class="tools" style="margin:0">${sk('120px','42px','border-radius:12px')}${sk('100px','42px','border-radius:12px')}</div>`;
function shSet(){$('#p-set').innerHTML=head('Settings','Templates, media, limits and WhatsApp')+`<div class="glass pad" id="sf">${setSkel()}</div><div class="glass pad" id="df" style="margin-top:14px">${sk('120px','13px','display:block;margin-bottom:10px')}${sk('100%','44px','display:block;border-radius:12px')}</div><div class="glass pad" id="mf" style="margin-top:14px">${setSkel()}</div><div class="glass pad" id="wf" style="margin-top:14px">${setSkel()}</div><div class="glass pad" id="pf" style="margin-top:14px">${setSkel()}</div>`}
const loadSet=()=>{paintConn();pollStatus();loadPipe();if(!C.has('queue'))fetchC('queue').then(()=>updTpl()).catch(()=>{});swr('media',{ttl:20000,render:fillMedia}).catch(()=>{});return swr('settings',{ttl:60000,render:fillSet})};
const loadSend=()=>{swr('settings',{ttl:60000,render:()=>drawIf()}).catch(()=>{});SJV=-1;poller(pollSend,SMS,true);pollStatus();
 swr('media',{ttl:20000,render:fillMedia}).catch(()=>{});
 return swr('queue',{ttl:6000,render:onQueue})};
const VARS=[['name','Business name'],['type','Business type, e.g. gym'],['category','Same as {type}'],['phone','Phone number'],['address','Address'],['rating','Google rating'],['reviews','Number of reviews'],['website','Website'],['date','Today, e.g. 15 Nov']];
const PRE=[
 ['Friendly','Hi {name}! 👋 This is [Your name]. I came across your {type} business and liked what I saw. I help local businesses get more customers online. Would you be open to a quick chat?\n\nReply STOP to opt out.'],
 ['Short','Hi {name}, this is [Your name]. Quick question about your {type} business: can I share an idea that may bring you more customers?\n\nReply STOP to opt out.'],
 ['Use rating','Hi {name}, I saw your {rating}-star rating from {reviews} reviews on Google. Great work! I am [Your name] and I have an idea to help you get even more customers. Interested?\n\nReply STOP to opt out.']];
const TSAMPLE={name:'Ravi Realty',type:'real estate',category:'real estate',phone:'98450 12345',address:'Indiranagar, Bengaluru',rating:'4.5',reviews:'120',website:'ravirealty.in'},KNOWN=VARS.map(v=>v[0]);let TPS='sample',TNEW=false,TBZ=false;
const TL={items:[],active:'',edit:''};
const tplDate=()=>new Date().toLocaleDateString([],{day:'numeric',month:'short'}),renderTpl=(t,v)=>t.replace(/\{(\w+)\}/g,(m,k)=>k in v?String(v[k]??''):m);
const newId=()=>'t'+Date.now().toString(36)+Math.random().toString(36).slice(2,5),curT=()=>TL.items.find(t=>t.id==TL.edit)||TL.items[0];
function tplVars(){const q=(C.get('queue')||{}).d,l=TPS=='lead'&&q&&q.items&&q.items[0];
 return l?{name:l.name,type:l.category,category:l.category,phone:l.phone,address:l.address,rating:l.rating,reviews:l.reviews,website:l.website,date:tplDate(),_lead:1}:Object.assign({date:tplDate()},TSAMPLE)}
function tplDirty(){const t=curT(),n=$('#tn'),b=$('#tp');return !!(t&&n&&b&&(n.value!==t.name||b.value!==t.body))}
function fillSet(s){
 if(!tplDirty()){TL.items=(s.templates||[]).map(t=>({id:t.id,name:t.name,body:t.body}));TL.active=s.active_template;if(!TL.items.some(t=>t.id==TL.edit))TL.edit=TL.active||(TL.items[0]||{}).id;paintTpl()}
 const dl=$('#dl');if(!dl||dl.value===dl.defaultValue)paint($('#df'),`<label for="dl">Daily sending limit</label><div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap"><input id="dl" type="number" min="1" max="100" value="${esc(s.daily_limit)}" style="width:110px"><button class="btn sm" data-a="savlim">Save</button><span class="sub" style="flex:1;min-width:180px">New or rarely used numbers are safer at 20 to 40 a day.</span></div>
  <div class="tools" style="margin:14px 0 0"><button class="btn ghost sm" data-a="logout">${ic('log-out')}Log out</button></div>`)}
function paintTpl(force){const el=$('#sf');if(!el)return;if(force)el._h=null;const t=curT();if(!t)return;const act=t.id==TL.active;
 paint(el,`<div class="tph"><div><label style="margin:0">Message templates</label><div class="sub">The active template is sent to every lead.</div></div><button class="btn ${TNEW?'sage':'soft'} sm" data-a="tnew">${ic('plus')}New</button></div>
 ${TNEW?`<div class="chips" style="margin:0 0 12px"><span class="sub" style="align-self:center">Start from:</span><button data-a="tadd" data-i="-1">Blank</button>${PRE.map((p,i)=>`<button data-a="tadd" data-i="${i}">${p[0]}</button>`).join('')}</div>`:''}
 <div class="tlist">${TL.items.map(x=>`<div class="titem${x.id==TL.edit?' sel':''}" data-a="tpick" data-id="${esc(x.id)}"><span class="tradio${x.id==TL.active?' on':''}"></span><div class="t"><b>${esc(x.name)}</b><small>${esc(x.body.replace(/\s+/g,' ').slice(0,80))}</small></div>${x.id==TL.active?'<span class="tag">Active</span>':''}</div>`).join('')}</div>
 <div class="ted"><div class="field"><label for="tn">Template name</label><input id="tn" maxlength="40" value="${esc(t.name)}" placeholder="e.g. Real estate intro"></div>
 <div class="field" style="margin-bottom:6px"><label for="tp">Message</label><textarea id="tp" rows="7" maxlength="1500">${esc(t.body)}</textarea>
 <div class="sub" style="display:flex;justify-content:space-between;margin-top:6px"><span id="tcnt"></span><span id="tdirty" style="color:var(--tom)"></span></div></div>
 <div class="chips" style="margin:0 0 4px">${VARS.map(v=>`<button data-a="ins" data-v="${v[0]}" title="${esc(v[1])}">{${v[0]}}</button>`).join('')}<button data-a="tstop">+ STOP line</button></div>
 <details style="margin:6px 0 0"><summary class="sub" style="cursor:pointer">What do these do?</summary><ul class="sub" style="margin:6px 0 0;padding-left:18px">${VARS.map(v=>`<li><b>{${v[0]}}</b> ${esc(v[1])}</li>`).join('')}</ul></details>
 <div class="seg" id="tseg" style="margin:16px 0 10px"><button data-a="tps" data-v="sample">Sample business</button><button data-a="tps" data-v="lead">First lead in queue</button></div>
 <div id="tpv"></div><div id="tchk" style="margin-bottom:4px"></div>
 <div class="tools" style="margin:14px 0 0"><button class="btn" data-a="tsave" ${TBZ?'disabled':''}>Save</button>${act?'<span class="tag" style="align-self:center">In use</span>':`<button class="btn soft" data-a="tuse" ${TBZ?'disabled':''}>${ic('check')}Save and use</button>`}<button class="btn ghost sm" data-a="tdup" ${TL.items.length>=20?'disabled':''}>${ic('copy')}Duplicate</button><button class="btn ghost sm" data-a="tdel" ${TL.items.length<2?'disabled':''}>${ic('trash-2')}Delete</button></div></div>`);updTpl()}
function updTpl(){const tp=$('#tp');if(!tp)return;const t=tp.value,v=tplVars(),n=mon().length,c=curT();
 document.querySelectorAll('#tseg button').forEach(b=>b.classList.toggle('on',b.dataset.v==TPS));
 $('#tcnt').textContent=t.length+' / 1500 characters';$('#tdirty').textContent=tplDirty()?'Unsaved changes':'';
 const note=TPS=='lead'?(v._lead?'Preview for '+esc(v.name):'No lead in the queue yet. Showing a sample.'):'Preview with a sample business';
 paint($('#tpv'),`<div class="sub" style="margin-bottom:6px">${note}</div>${t.trim()?`<div class="bubble">${esc(renderTpl(t,v))}</div>`:'<div class="sub">Type a message to see the preview.</div>'}${n?`<p class="sub" style="text-align:right;margin:6px 0 0">+ ${n} media file${n>1?'s':''} sent with it</p>`:''}`,1);
 const ck=[],unk=[...new Set([...t.matchAll(/\{(\w+)\}/g)].map(m=>m[1]))].filter(k=>!KNOWN.includes(k));
 if(!t.trim())ck.push([1,'The message is empty.']);
 else{if(!/\{name\}/.test(t))ck.push([1,'Add {name} so the message feels personal.']);
  if(!/\bstop\b/i.test(t))ck.push([1,'Add a "Reply STOP to opt out" line. It protects your number.']);
  if(/\[[^\]]+\]/.test(t))ck.push([1,'Replace the [bracketed] part, for example with your name.']);
  if(unk.length)ck.push([1,'Unknown variable: '+unk.map(k=>'{'+k+'}').join(', ')+'. It will not be filled in.']);
  if(t.length>600)ck.push([1,'This is long. Messages under 600 characters get more replies.']);
  if(!ck.length)ck.push([0,'Looks good.'])}
 paint($('#tchk'),ck.map(c=>`<div class="sub" style="display:flex;gap:8px;margin-top:6px;color:${c[0]?'#9a5b12':'#3f7a44'}">${ic(c[0]?'alert-triangle':'check-circle-2')}<span>${esc(c[1])}</span></div>`).join(''))}
/* ----- template actions: every change is one PUT of the whole list ----- */
function readEditor(){const t=curT(),n=$('#tn'),b=$('#tp');if(t&&n&&b){t.name=n.value.trim()||'Untitled';t.body=b.value}}
async function persistTpl(active,msg){TBZ=true;paintTpl(1);
 try{const r=await api('settings','PUT',{templates:TL.items,active});TL.items=r.templates.map(t=>({id:t.id,name:t.name,body:t.body}));TL.active=r.active_template;
  if(!TL.items.some(t=>t.id==TL.edit))TL.edit=TL.active;const c=C.get('settings');c&&put('settings',Object.assign({},c.d,r));stale(/^queue/);toast(msg);return true}
 catch(e){e&&toast(e.message);return false}finally{TBZ=false;paintTpl(1)}}
async function saveTpl(btn,use){const t=curT();if(!t)return;const b=$('#tp');if(!b||!b.value.trim())return toast('The message is empty');readEditor();
 await persistTpl(use?t.id:TL.active,use?'Saved. Now using "'+t.name+'"':'Template saved')}
function pickTpl(id){if(id==TL.edit)return;if(tplDirty()&&!confirm('Discard your unsaved changes to this template?'))return;TL.edit=id;paintTpl(1)}
async function addTpl(i){if(TL.items.length>=20)return toast('You can keep up to 20 templates');TNEW=false;readEditor();const p=PRE[i],n=newId();
 TL.items.push({id:n,name:p?p[0]:'New template',body:p?p[1]:'Hi {name}, \n\nReply STOP to opt out.'});TL.edit=n;
 await persistTpl(TL.active,'Template added')}
async function dupTpl(){const t=curT();if(!t||TL.items.length>=20)return;readEditor();const n=newId();TL.items.push({id:n,name:(t.name+' copy').slice(0,40),body:t.body});TL.edit=n;await persistTpl(TL.active,'Template duplicated')}
async function delTpl(){const t=curT();if(!t||TL.items.length<2)return;if(!confirm('Delete "'+t.name+'"?'))return;
 TL.items=TL.items.filter(x=>x.id!=t.id);const was=TL.active==t.id;TL.edit=TL.items[0].id;await persistTpl(was?TL.items[0].id:TL.active,'Template deleted')}
/* quick switch from the Send tab */
async function useTpl(id){const old=TL.active;try{const r=await api('settings','PUT',{active:id});TL.active=r.active_template;const c=C.get('settings');c&&put('settings',Object.assign({},c.d,r));stale(/^queue/);
  toast('Now using "'+(r.templates.find(t=>t.id==id)||{}).name+'"');await swr('queue',{ttl:0,render:onQueue})}catch(e){e&&toast(e.message);drawIf()}}
async function saveLimit(btn){const d=$('#dl').value;btn.setAttribute('disabled','');
 try{await api('settings','PUT',{daily_limit:d});const c=C.get('settings');c&&put('settings',Object.assign({},c.d,{daily_limit:d}));$('#dl').defaultValue=d;stale(/^(queue|stats)/);toast('Limit saved')}
 catch(e){e&&toast(e.message)}finally{btn.removeAttribute('disabled')}}

/* ----- WhatsApp connection panel (driven by the shared status) ----- */
const hhmm=t=>new Date(t*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
function paintConn(){const b=$('#wf');if(!b)return;
 if(!WST.loaded){paint(b,`${sk('160px','13px','display:block;margin-bottom:10px')}${sk('100%','44px','display:block;border-radius:12px')}`,1);return}
 const s=WST,ok=s.status=='ready',sy=s.sync,
 body=ok?`<p class="sub" style="margin:0">Connected${s.mem_mb?' · server memory '+esc(Math.round(s.mem_mb))+' MB':''}.</p>`
  :s.status=='disabled'?`<p class="sub" style="margin:0">WhatsApp is turned off on this server, so auto-send, backup and reset are unavailable. Manual sending from the Send tab still works. Enable WhatsApp in the server configuration and restart to use it.</p>`
  :s.status=='error'?`<div class="err" style="margin:0">${esc(s.err||'WhatsApp failed to start')}</div>`
  :`<p class="sub" style="margin:0 0 10px">${s.status=='qr'?'On your phone open WhatsApp, Linked devices, then scan this.':'Starting... this is what the server sees:'}</p>${s.qr?`<img src="${esc(s.qr)}" alt="" style="width:${s.status=='qr'?240:'100%'}px;max-width:100%;border-radius:12px">`:''}`,
 bk=!sy?'No backup made since this server started':sy.ok?'Last backup to storage: '+hhmm(sy.at):'Last backup failed: '+esc(sy.err||'unknown error');
 paint(b,`<label>WhatsApp connection</label>${body}${s.status=='disabled'?'':`<p class="sub" style="margin:10px 0 0">${bk}</p>`}${BUSY?`<div class="wl" style="margin-top:10px">${esc(busyMsg())}</div>`:''}
 <div class="tools" style="margin:14px 0 0"><button class="btn soft" data-a="wsync" ${ok&&!BUSY&&!WB?'':'disabled'}>${ic('database')}${WB==1?'Backing up...':'Back up now'}</button><button class="btn ghost" data-a="wreset" ${BUSY||WB||s.status=='disabled'?'disabled':''}>${ic('log-out')}Log out and reset</button></div>`)}
async function waSync(){if(WB||BUSY||WS!='ready')return;WB=1;paintConn();
 try{await api('wa/sync','POST');toast('Backup started');setTimeout(pollStatus,3000)}
 catch(e){e&&toast(e.message);pollStatus()}finally{WB=0;paintConn()}}
async function waReset(){if(WB||BUSY)return;
 if(!confirm('Log out of WhatsApp and reset this session?\n\nAlso open WhatsApp on your phone, go to Linked devices, and remove this device. A new QR code will appear so you can link again.'))return;
 WB=2;paintConn();
 try{await api('wa/reset','POST');toast('Session reset. A new QR code is coming.');pollStatus();setTimeout(pollStatus,2500)}
 catch(e){e&&toast(e.message);pollStatus()}finally{WB=0;paintConn()}}

/* ----- sending pipeline panel ----- */
const PO=[['caption','Media with text as caption'],['text_first','Text first, then media'],['media_first','Media first, then text']];
function pipeDirty(){const o=$('#pord');if(!o)return false;const a=$('#palb');return o.value!==o.dataset.o||a.checked!==a.defaultChecked||['pstep','pgap','pjit'].some(i=>{const e=$('#'+i);return e.value!==e.defaultValue})}
function fillPipe(c){if(pipeDirty())return;
 paint($('#pf'),`<label>Sending pipeline</label>
 <div class="field"><label for="pord">Order</label><select id="pord" data-o="${esc(c.order)}">${PO.map(o=>`<option value="${o[0]}" ${o[0]==c.order?'selected':''}>${o[1]}</option>`).join('')}</select></div>
 <label class="ck" style="margin:0 0 14px"><input type="checkbox" id="palb" ${c.album?'checked':''}>Send all media in one go (album; faster, riskier)</label>
 <div class="r2"><div class="field"><label for="pstep">Pause between parts (s)</label><input id="pstep" type="number" inputmode="numeric" min="0" max="30" value="${esc(c.step_delay)}"></div><div class="field"><label for="pgap">Gap between leads (s)</label><input id="pgap" type="number" inputmode="numeric" min="10" max="300" value="${esc(c.gap)}"></div></div>
 <div class="field"><label for="pjit">Random extra delay (s)</label><input id="pjit" type="number" inputmode="numeric" min="0" max="120" value="${esc(c.jitter)}"></div>
 <button class="btn" data-a="psave">Save pipeline</button>`)}
const loadPipe=()=>swr('wa/config',{ttl:60000,render:fillPipe}).catch(e=>e&&toast(e.message));
async function savePipe(btn){const o=$('#pord'),al=$('#palb');if(!o||PB)return;
 const v=i=>{const s=$('#'+i).value.trim();return s===''?NaN:Number(s)},st=v('pstep'),gp=v('pgap'),jt=v('pjit'),ri=(x,a,b)=>Number.isInteger(x)&&x>=a&&x<=b;
 const bad=!ri(st,0,30)?'Pause between parts must be 0 to 30 seconds':!ri(gp,10,300)?'Gap between leads must be 10 to 300 seconds':!ri(jt,0,120)?'Random extra delay must be 0 to 120 seconds':'';
 if(bad)return toast(bad);
 const cfg={order:o.value,album:al.checked,step_delay:st,gap:gp,jitter:jt};PB=1;btn.setAttribute('disabled','');
 try{await api('wa/config','PUT',cfg);put('wa/config',cfg);
  o.dataset.o=cfg.order;al.defaultChecked=cfg.album;[['pstep',st],['pgap',gp],['pjit',jt]].forEach(p=>{$('#'+p[0]).defaultValue=String(p[1])});toast('Pipeline saved')}
 catch(e){e&&toast(e.message)}finally{PB=0;btn.removeAttribute('disabled')}}

