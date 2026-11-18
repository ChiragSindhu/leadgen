/* ============ LEADS (paged + multi-select) ============ */
const LF0=()=>({q:'',st:'',cat:'',m:0,ph:0,web:0,em:0,rd:0,ct:'',sc:0,rt:0,sort:'score'});
const SORTS=[['score','Best score'],['new','Newest first'],['old','Oldest first'],['name','Name A to Z'],['rating','Highest rating'],['reviews','Most reviews'],['contacted','Recently contacted']];
const TOGS=[['m','Mobile only','smartphone'],['ph','Has phone','phone'],['web','Has website','globe'],['em','Has email','mail'],['rd','Ready to message','send']];
const STX=[['','All statuses'],['replied,interested','Replied or interested'],...ST.map(x=>[x,x])];
const PS=50;let LF=LF0(),LS=0,LC=null,QT=0,SELM=0,SELALL=0,LBUSY=0;
const SEL=new Set(),LP={items:[],total:0,more:false,key:'',busy:false};
const lfp=()=>({q:LF.q,status:LF.st,category:LF.cat,mobile:LF.m,phone:LF.ph,website:LF.web,email:LF.em,ready:LF.rd,contacted:LF.ct,min_score:LF.sc,min_rating:LF.rt,sort:LF.sort});
const lk=(q=LF.q,off=0)=>'leads?'+Object.entries(Object.assign(lfp(),{q})).map(([k,v])=>k+'='+enc(v)).join('&')+`&limit=${PS}&offset=${off}`;
const lfCount=()=>['q','st','cat','m','ph','web','em','rd','ct','sc','rt'].filter(k=>LF[k]).length;
const isSel=id=>SELALL||SEL.has(String(id)),dropListCaches=()=>{for(const k of[...C.keys()])if(k.startsWith('leads?'))C.delete(k)};
function shLeads(){$('#p-leads').innerHTML=head('Leads','Everything you have collected',`<div style="display:flex;gap:8px"><button class="btn soft" id="lselb" data-a="selmode">${ic('check-square')}Select</button><button class="btn" data-a="add">${ic('plus')}Add</button></div>`)+
 `<div class="tools"><div class="grow">${ic('search')}<input id="q" placeholder="Search name, phone, area or type" autocomplete="off"></div>
 <button id="lfb" class="btn soft" data-a="lfpanel">${ic('filter')}Filters<span id="lfn" class="lfn" hidden></span></button>
 <select id="lsort" class="chip" data-lf="sort" aria-label="Sort leads" style="height:42px">${SORTS.map(o=>`<option value="${o[0]}">${o[1]}</option>`).join('')}</select></div>
 <div id="lfp" class="glass pad lfp" hidden>
  <div class="r2"><div class="field"><label for="lf-st">Status</label><select id="lf-st" data-lf="st">${STX.map(o=>`<option value="${esc(o[0])}">${esc(o[1])}</option>`).join('')}</select></div>
  <div class="field"><label for="lf-cat">Business type</label><select id="lf-cat" data-lf="cat"><option value="">All types</option></select></div></div>
  <div class="r2"><div class="field"><label for="lf-ct">Contact</label><select id="lf-ct" data-lf="ct"><option value="">Any</option><option value="1">Already contacted</option><option value="0">Not contacted yet</option></select></div>
  <div class="field"><label for="lf-sc">Minimum score</label><select id="lf-sc" data-lf="sc"><option value="0">Any</option><option value="40">40 and up</option><option value="70">70 and up</option><option value="90">90 and up</option></select></div></div>
  <div class="field"><label for="lf-rt">Minimum rating</label><select id="lf-rt" data-lf="rt"><option value="0">Any</option><option value="3">3 stars and up</option><option value="4">4 stars and up</option><option value="4.5">4.5 stars and up</option></select></div>
  <label>Must have</label><div class="chips" id="lftog" style="margin:0 0 12px">${TOGS.map(t=>`<button data-a="lftog" data-k="${t[0]}">${ic(t[2])}${t[1]}</button>`).join('')}</div>
  <div class="tools" style="margin:0;justify-content:space-between"><button class="btn ghost sm" data-a="lfall">${ic('x')}Clear all filters</button><button class="btn soft sm" data-a="lfpanel">Done</button></div></div>
 <div id="lchips" class="chips lchips"></div>
 <div id="lk" class="glass list">${skRows(7)}</div><div id="ll" class="glass list" hidden></div><div id="lft" style="padding:14px 0;text-align:center"></div>`;draw();
 $('#q').addEventListener('input',()=>{clearTimeout(QT);QT=setTimeout(()=>{const v=$('#q').value.trim();if(v==LF.q)return;LF.q=v;lfSync(1);loadLeads()},250)});
 new IntersectionObserver(es=>{if(es[0].isIntersecting)loadMore()},{rootMargin:'500px'}).observe($('#lft'));
 lfSync();swr('leads/facets',{ttl:60000,render:fillCats}).catch(()=>{})}

/* ----- filters: one state object (LF), mirrored into the controls, chips and badge ----- */
function fillCats(d){const el=$('#lf-cat');if(!el)return;const names=(d.categories||[]).map(c=>c.name);if(LF.cat&&!names.some(n=>n.toLowerCase()==LF.cat.toLowerCase()))names.unshift(LF.cat);
 el.innerHTML='<option value="">All types</option>'+(d.categories||[]).map(c=>`<option value="${esc(c.name)}">${esc(c.name)} (${esc(c.n)})</option>`).join('')+(names.length>(d.categories||[]).length?`<option value="${esc(LF.cat)}">${esc(LF.cat)}</option>`:'');el.value=LF.cat}
function chipList(){const L=[],tl=Object.fromEntries(TOGS.map(t=>[t[0],t[1]])),sx=Object.fromEntries(STX);
 if(LF.q)L.push(['q','Search: '+LF.q]);if(LF.st)L.push(['st','Status: '+(sx[LF.st]||LF.st)]);if(LF.cat)L.push(['cat','Type: '+LF.cat]);
 if(LF.ct)L.push(['ct',LF.ct=='1'?'Already contacted':'Not contacted yet']);if(LF.sc)L.push(['sc','Score '+LF.sc+'+']);if(LF.rt)L.push(['rt','Rating '+LF.rt+'+']);
 for(const k of['m','ph','web','em','rd'])if(LF[k])L.push([k,tl[k]]);return L}
function lfSync(skipInput){if(!$('#p-leads')||!$('#lfp'))return;
 if(!skipInput){const q=$('#q');if(q&&q.value!==LF.q)q.value=LF.q}
 $('#lsort').value=LF.sort;[['st','lf-st'],['cat','lf-cat'],['ct','lf-ct'],['sc','lf-sc'],['rt','lf-rt']].forEach(p=>{const e=$('#'+p[1]);if(e)e.value=String(LF[p[0]])});
 document.querySelectorAll('#lftog button').forEach(b=>b.classList.toggle('on',!!LF[b.dataset.k]));
 const n=lfCount(),badge=$('#lfn');badge.hidden=!n;badge.textContent=n;$('#lfb').className='btn '+(n?'sage':'soft');
 const ch=chipList();paint($('#lchips'),ch.length?ch.map(c=>`<button class="lfchip" data-a="lfclr" data-k="${c[0]}" title="Remove filter">${esc(c[1])}${ic('x')}</button>`).join('')+`<button class="lfchip clear" data-a="lfall">Clear all</button>`:'')}
function lfChanged(){lfSync();loadLeads()}
function lfClear(k){const z=LF0();LF[k]=z[k];lfChanged()}
function lfClearAll(){const sort=LF.sort;LF=Object.assign(LF0(),{sort});lfChanged()}
/* open the Leads tab with a preset filter (used by the Home cards) */
function goLeads(p){LF=Object.assign(LF0(),{sort:LF.sort},p||{});SEL.clear();SELALL=0;go('leads');lfSync()}
const rowSig=l=>[l.id,l.name,l.category,l.phone,l.outreach,l.score,SELM?(isSel(l.id)?2:1):0].join('|');
const rowHTML=l=>{const id=esc(l.id);return (SELM?`<span class="cb ${isSel(l.id)?'on':''}"></span>`:'')+`<div class="av">${initial(l.name)}</div><div class="t"><b>${esc(l.name)}</b><small>${esc(l.category)} · ${esc(l.phone||'No phone')} · ${esc(l.outreach)}</small></div>
 <span class="score ${l.score>=70?'hi':''}">${esc(l.score)}</span>`+(SELM?'':`<select class="chip rowact" data-a="st" data-id="${id}">${ST.map(s=>`<option ${s==l.outreach?'selected':''}>${s}</option>`).join('')}</select>
 <button class="btn ghost sm rowact" aria-label="Delete" data-a="del" data-id="${id}">${ic('trash-2')}</button><span class="chev">${ic('chevron-right')}</span>`)};
function renderLeads(){const ll=$('#ll'),lkx=$('#lk'),M=ll._m||(ll._m=new Map()),d=LP.items;ll.classList.remove('busy');
 if(!d.length){M.clear();ll.textContent='';ll.hidden=true;lkx.hidden=false;lkx.innerHTML=`<div class="empty">${ic('inbox')}<div>${lfCount()?'No leads match these filters':'No leads match yet'}</div>${lfCount()?'<button class="btn soft sm" style="margin-top:12px" data-a="lfall">Clear all filters</button>':''}</div>`;draw();paintFoot();selBar();return}
 lkx.hidden=true;ll.hidden=false;const seen=new Set();
 d.forEach((l,i)=>{const k=String(l.id),sig=rowSig(l);let r=M.get(k);
  if(!r){const el=document.createElement('div');el.dataset.a='open';el.dataset.id=k;r={el,sig:null};M.set(k,r)}
  if(r.sig!==sig){r.el.className='lead'+(SELM&&isSel(l.id)?' sel':'');r.el.innerHTML=rowHTML(l);r.sig=sig}
  seen.add(k);const cur=ll.children[i];if(cur!==r.el)ll.insertBefore(r.el,cur||null)});
 for(const[k,r]of M)if(!seen.has(k)){r.el.remove();M.delete(k)}
 draw();paintFoot();selBar()}
function paintFoot(){const f=$('#lft');if(!f)return;const n=LP.items.length;
 paint(f,!n?'':LP.more?`<button class="btn soft" data-a="more" ${LP.busy?'disabled':''}>${LP.busy?'Loading...':`Load more (${n} of ${LP.total})`}</button>`:`<span class="sub">${LP.total==1?'1 lead':'All '+LP.total+' leads shown'}</span>`,1)}
function applyFirst(d,key){
 if(LP.key===key&&LP.items.length>PS){const seen=new Set(d.items.map(l=>String(l.id)));LP.items=d.items.concat(LP.items.slice(PS).filter(l=>!seen.has(String(l.id))))}   // keep pages already scrolled in
 else LP.items=d.items.slice();
 if(LP.key!==key){SEL.clear();SELALL=0}
 LP.key=key;LP.total=d.total;LP.more=LP.items.length<d.total;renderLeads()}
function loadLeads(){
 const key=lk(),my=++LS;if(LC)LC.abort();LC=new AbortController();const ll=$('#ll');
 if(!C.has(key)){if(ll._m&&ll._m.size)ll.classList.add('busy');else{ll.hidden=true;$('#lk').hidden=false;$('#lk').innerHTML=skRows(7)}}
 return swr(key,{ttl:15000,signal:LC.signal,ok:()=>my===LS,render:d=>{if(my===LS)applyFirst(d,key)}}).catch(e=>{
  if(e&&my===LS){ll.classList.remove('busy');toast(e.message);if(!ll._m||!ll._m.size){ll.hidden=true;$('#lk').hidden=false;$('#lk').innerHTML=`<div class="empty">${ic('alert-circle')}<div>Couldn't load leads</div><button class="btn soft sm" style="margin-top:12px" data-a="reload">Try again</button></div>`;draw()}}})}
async function loadMore(){if(LP.busy||!LP.more||LP.key!==lk())return;LP.busy=true;paintFoot();const my=LS,key=LP.key,off=LP.items.length;
 try{const d=await api(lk(LF.q,off));if(my!==LS||LP.key!==key)return;
  const seen=new Set(LP.items.map(l=>String(l.id))),add=d.items.filter(l=>!seen.has(String(l.id)));
  LP.items=LP.items.concat(add);LP.total=d.total;LP.more=add.length>0&&LP.items.length<d.total;renderLeads()}
 catch(e){e&&toast(e.message)}finally{LP.busy=false;paintFoot();setTimeout(nearEnd,50)}}
function nearEnd(){const f=$('#lft');if(f&&tab=='leads'&&LP.more&&f.getBoundingClientRect().top<innerHeight+500)loadMore()}

/* ----- selection + bulk ----- */
function selOn(){SELM=1;SEL.clear();SELALL=0;renderLeads()}
function selOff(){if(!SELM)return;SELM=0;SEL.clear();SELALL=0;renderLeads()}
function toggleSel(id){if(SELALL){LP.items.forEach(l=>SEL.add(String(l.id)));SELALL=0}SEL.has(id)?SEL.delete(id):SEL.add(id);renderLeads()}
function selBar(){const b=$('#lsel'),btn=$('#lselb');if(btn)btn.className='btn '+(SELM?'sage':'soft');
 if(!SELM||tab!='leads'){b.hidden=true;return}
 const n=SELALL?LP.total:SEL.size,all=n>0&&n>=LP.items.length,canAll=!SELALL&&LP.more&&SEL.size>=LP.items.length&&n>0,dis=n&&!LBUSY?'':'disabled';
 b.hidden=false;paint(b,`<div class="selrow"><b>${n} selected</b>${canAll?`<button class="btn ghost sm" data-a="selmatch">Select all ${LP.total} matching</button>`:`<button class="btn ghost sm" data-a="selall">${all?'Clear':'Select all'+(LP.more?' loaded':'')}</button>`}</div>
 <div class="selrow"><select id="bst" class="chip" ${dis}><option value="">Set status...</option>${ST.map(s=>`<option>${s}</option>`).join('')}</select>
 <button class="btn sm" data-a="bulkdel" ${dis}>${ic('trash-2')}Delete</button><button class="btn soft sm" data-a="selmode">Done</button></div>`)}
async function bulk(action,val){const n=SELALL?LP.total:SEL.size;if(!n||LBUSY)return;
 if(action=='delete'&&!confirm(`Delete ${n} lead${n==1?'':'s'}? This cannot be undone.`))return;
 const body=SELALL?{action,outreach:val,all:true,filters:lfp()}:{action,outreach:val,ids:[...SEL]};
 LBUSY=1;selBar();$('#ll').classList.add('busy');
 try{const r=await api('leads/bulk','POST',body);afterMut();dropListCaches();toast(action=='delete'?`Deleted ${r.n}`:`Updated ${r.n}`);
  SEL.clear();SELALL=0;LP.key='';await loadLeads()}
 catch(e){e&&toast(e.message)}finally{LBUSY=0;$('#ll').classList.remove('busy');selBar()}}

/* ----- single-row actions ----- */
async function upd(id,o){patchLeadCaches(id,{outreach:o});renderLeads();
 try{await api('leads/'+enc(id),'PATCH',{outreach:o});afterMut();toast('Status updated')}catch(e){e&&toast(e.message);loadLeads()}}
async function del(id){if(!confirm('Delete this lead?'))return;const[snap,tot]=dropLead(id);renderLeads();
 try{await api('leads/'+enc(id),'DELETE');afterMut();C.delete('leads/'+enc(id));toast('Deleted')}
 catch(e){LP.items=snap;LP.total=tot;renderLeads();e&&toast(e.message)}}
 
/* ----- lead detail ----- */
const when=t=>t?new Date(String(t).replace(' ','T')).toLocaleString([],{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):'';
const safe=u=>/^https?:\/\//i.test(u||'')?u:'',hm=t=>t?new Date(t).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'';
const kvSk=()=>`<div class="kv">${sk('18px','18px')}<div style="flex:1">${sk('30%','10px','display:block;margin-bottom:6px')}${sk('62%','14px','display:block')}</div></div>`;
function leadSkel(pv){return GRAB+`<div style="display:flex;gap:14px;align-items:center"><div class="av" style="width:54px;height:54px;font-size:20px">${pv?initial(pv.name):sk('54px','54px','border-radius:14px')}</div><div style="min-width:0;flex:1">${pv?`<h1 style="font-size:20px">${esc(pv.name)}</h1><div class="sub">${esc(pv.category)} · score ${esc(pv.score)}</div>`:sk('60%','22px','display:block;margin-bottom:6px')+sk('40%','13px','display:block')}</div></div>
 <div class="qa">${sk('100%','42px','border-radius:12px')}${sk('100%','42px','border-radius:12px')}${sk('100%','42px','border-radius:12px')}</div>${sk('100%','44px','display:block;margin-bottom:14px;border-radius:12px')}${kvSk()}${kvSk()}${kvSk()}${kvSk()}
 <div class="tools" style="margin:14px 0 0"><button class="btn" disabled>Save</button><button class="btn soft" data-a="close">Close</button></div>`}
function openLead(id){const my=++DS;clearTimeout(RT);showSheet(leadSkel(findLead(id)),0);openDlg(D2);swr('media',{ttl:20000,render:fillMedia}).catch(()=>{});const p='leads/'+enc(id);
 swr(p,{ttl:15000,ok:()=>my===DS&&D2.open,render:d=>{if(my===DS&&D2.open)fillLead(d)}}).catch(e=>{if(e&&my===DS)showSheet(errSheet(e.message))})}
function fillLead(l){const w=safe(l.website),m=safe(l.maps_url),pn=$('#pn'),ps=$('#ps');
 const dn=pn&&pn.value!==pn.defaultValue?pn.value:null,dsv=ps&&ps.value!==ps.dataset.o?ps.value:null,id=esc(l.id);
 const kv=(i,k,v)=>v?`<div class="kv">${ic(i)}<div><small>${k}</small>${v}</div></div>`:'';
 showSheet(GRAB+`<div style="display:flex;gap:14px;align-items:center"><div class="av" style="width:54px;height:54px;font-size:20px">${initial(l.name)}</div><div style="min-width:0"><h1 style="font-size:20px">${esc(l.name)}</h1><div class="sub">${esc(l.category)} · score ${esc(l.score)}</div></div></div>
 <div class="qa">${l.phone?`<a class="btn soft" href="tel:${esc(l.phone)}">${ic('phone')}Call</a>`:''}${m?`<a class="btn soft" target="_blank" rel="noopener" href="${esc(m)}">${ic('map')}Map</a>`:''}${w?`<a class="btn soft" target="_blank" rel="noopener" href="${esc(w)}">${ic('globe')}Website</a>`:''}</div>
 ${l.phone?`<div class="lbl" style="margin:4px 0 8px">Send message</div><div class="mact">${l.link?`<a class="btn" target="_blank" rel="noopener" href="${esc(l.link)}">${ic('message-circle')}Send text on WhatsApp</a>`:''}<div class="two"><button class="btn soft" data-a="media" data-id="${id}">${ic('image')}Send media</button><button class="btn soft" data-a="copytxt" data-id="${id}">${ic('copy')}Copy text</button></div><button class="btn soft" data-a="auto" data-id="${id}" ${WS=='ready'&&!BUSY?'':'disabled'}>${ic('zap')}Auto send text + media</button></div><p class="hint" style="text-align:left;margin:0 0 14px">Send text opens WhatsApp with the message typed. Press send, come back, then tap Send media.${WS=='ready'?'':' Auto send needs WhatsApp connected.'}</p>`:''}
 <div class="field"><label>Status</label><select id="ps" data-o="${esc(l.outreach)}">${ST.map(s=>`<option ${s==l.outreach?'selected':''}>${s}</option>`).join('')}</select></div>
 ${kv('smartphone','Phone',l.phone?esc(l.phone)+(l.is_mobile?' (mobile, WhatsApp-ready)':' (landline)'):'')}${kv('mail','Email',l.email?`<a href="mailto:${esc(l.email)}">${esc(l.email)}</a>`:'')}${kv('globe','Website',w?`<a target="_blank" rel="noopener" href="${esc(w)}">${esc(w)}</a>`:'')}
 ${kv('map-pin','Address',esc(l.address))}${kv('star','Rating',l.rating?esc(l.rating)+' from '+esc(l.reviews||0)+' reviews':'')}${kv('database','Source',esc(l.source)+' · '+esc(l.status||'active'))}
 ${kv('calendar','First seen',esc(when(l.first_seen)))}${kv('refresh-cw','Last seen',esc(when(l.last_seen)))}${kv('message-circle','Last contacted',esc(when(l.contacted_at)))}
 <div class="field" style="margin-top:12px"><label>Notes</label><textarea id="pn" rows="3">${esc(l.notes)}</textarea></div>
 ${(l.changes||[]).length?`<label>Recent changes</label><ul class="tl">${l.changes.map(c=>`<li><time>${esc(when(c.at))}</time><span>${esc(c.field)}: ${esc(c.old||'empty')} to ${esc(c.new||'empty')}</span></li>`).join('')}</ul>`:''}
 <div class="tools" style="margin:14px 0 0"><button class="btn" data-a="lsave" data-id="${id}">Save</button>${l.phone?`<button class="btn soft" data-a="front" data-id="${id}">${ic('arrow-up')}Send first</button>`:''}<button class="btn soft" data-a="close">Close</button><button class="btn ghost" data-a="ldel" data-id="${id}">${ic('trash-2')}Delete</button></div>`,1);
 if(dn!=null)$('#pn').value=dn;if(dsv!=null)$('#ps').value=dsv}
async function saveLead(id,btn){const o=$('#ps').value,n=$('#pn').value;btn.setAttribute('disabled','');
 try{await api('leads/'+enc(id),'PATCH',{outreach:o,notes:n});patchLeadCaches(id,{outreach:o,notes:n});afterMut();closeDlg(D2);toast('Saved');INIT.leads&&loadLeads()}
 catch(e){btn.removeAttribute('disabled');e&&toast(e.message)}}

