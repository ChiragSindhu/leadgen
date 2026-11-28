/* ============ helpers ============ */
const $=s=>document.querySelector(s),esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ic=n=>`<i data-lucide="${n}"></i>`,draw=()=>{try{lucide.createIcons()}catch(e){}},enc=encodeURIComponent,
ST=['new','messaged','replied','interested','not_interested','bad_number','do_not_contact'],GRAB='<div class="grab"></div>',D1=$('#dlg'),D2=$('#dlg2');
const TABS=[['dash','layout-dashboard','Home'],['leads','users','Leads'],['agent','sparkles','Boss'],['find','search','Find'],['runs','history','Runs'],['send','send','Send'],['set','settings','Settings']];
const sk=(w,h,x='')=>`<span class="sk" style="width:${w};height:${h};${x}"></span>`;
const skRows=n=>Array.from({length:n},(_,i)=>`<div class="skrow">${sk('42px','42px','border-radius:14px')}<div style="flex:1">${sk([62,48,70,55,66,44,58][i%7]+'%','14px','display:block;margin-bottom:6px')}${sk('38%','11px','display:block')}</div>${sk('34px','20px')}</div>`).join('');
const head=(t,s,a='')=>`<div class="top"><div><h1>${t}</h1><div class="sub">${s}</div></div>${a}</div>`;
function paint(el,h,nd){if(!el||el._h===h)return;el._h=h;el.innerHTML=h;if(!nd)draw()}
function setv(id,v){const e=$('#'+id);if(!e)return;e.classList.remove('sk');e.removeAttribute('style');e.textContent=v}
const initial=n=>esc(((n||'')[0]||'?').toUpperCase());
function toast(m,u){const t=$('#toast');window._u=u;t.innerHTML=esc(m)+(u?' <button data-a="undo">Undo</button>':'');t.classList.add('on');try{if(t.matches(':popover-open'))t.hidePopover();t.showPopover()}catch(e){}clearTimeout(t.h);t.h=setTimeout(()=>t.classList.remove('on'),u?6000:2600)}

/* ============ network + cache ============ */
let tab='',PT=0,PA=null,PK=0,DS=0,RT=0,LV=0;
const C=new Map(),INF=new Map(),SC={},INIT={};
async function api(p,m='GET',b,o={}){
 let r;try{r=await fetch('/api/'+p,{method:m,headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined,signal:o.signal})}
 catch(e){if(e&&e.name=='AbortError')throw 0;throw new Error('Network error. Check your connection.')}
 if(r.status==401){$('#login').hidden=false;$('#wpill').hidden=true;clearTimeout(SPT);stopPoll();throw 0}if(r.status==204)return null;
 let j=null;try{j=await r.json()}catch(e){}
 if(!r.ok)throw new Error((j&&j.error)||'Something went wrong');return j}
function fetchC(p,o={}){
 const run=async()=>{const d=await api(p,'GET',null,{signal:o.signal}),s=JSON.stringify(d),c=C.get(p),changed=!c||c.s!==s;C.set(p,{d,s,t:Date.now(),x:false});if(p.startsWith('leads?')){LV++;pruneLeads()}return{d,changed}};
 if(o.signal)return run();
 if(INF.has(p))return INF.get(p);
 const pr=run().finally(()=>INF.delete(p));INF.set(p,pr);return pr}
async function swr(p,o){
 const c=C.get(p);let shown=false;
 if(c){o.render(c.d,true);shown=true;if(!c.x&&Date.now()-c.t<(o.ttl??20000))return c.d}
 const r=await fetchC(p,{signal:o.signal});
 if(o.ok&&!o.ok())return r.d;
 if(!shown||r.changed)o.render(r.d,false);return r.d}
function put(p,d){const c=C.get(p);C.set(p,{d,s:JSON.stringify(d),t:c?c.t:Date.now(),x:c?c.x:false});if(p.startsWith('leads?'))LV++}
const stale=re=>{for(const[k,c]of C)if(re.test(k))c.x=true};
const afterMut=()=>stale(/^(stats|queue|leads)/),afterJob=()=>stale(/^(stats|queue|leads|runs|settings)/);
function pruneLeads(){const ks=[...C].filter(([k])=>k.startsWith('leads?')).sort((a,b)=>a[1].t-b[1].t);while(ks.length>12)C.delete(ks.shift()[0])}
function patchLeadCaches(id,patch){id=String(id);
 for(const[k,c]of C){if(k.startsWith('leads?')&&c.d&&c.d.items){let hit=0;const items=c.d.items.map(l=>String(l.id)==id?(hit=1,Object.assign({},l,patch)):l);if(hit)put(k,Object.assign({},c.d,{items}))}
  else if(k=='leads/'+enc(id)&&c.d)put(k,Object.assign({},c.d,patch))}
 const m=LP.items.findIndex(l=>String(l.id)==id);if(m>=0)LP.items[m]=Object.assign({},LP.items[m],patch)}
function dropLead(id){id=String(id);const snap=LP.items.slice(),tot=LP.total;LP.items=LP.items.filter(l=>String(l.id)!=id);LP.total=Math.max(0,LP.total-1);
 for(const k of[...C.keys()])if(k.startsWith('leads?'))C.delete(k);return[snap,tot]}
function findLead(id){id=String(id);return LP.items.find(l=>String(l.id)==id)||null}

/* ============ polling (single, abortable; ms may be a number or a function) ============ */
function stopPoll(){clearTimeout(PT);if(PA)PA.abort();PA=null;PK++}
function poller(fn,ms,now){stopPoll();const k=PK,ac=PA=new AbortController(),dl=()=>typeof ms=='function'?ms():ms;
 const tick=async()=>{if(k!==PK)return;if(document.hidden){PT=setTimeout(tick,Math.max(dl(),15000));return}let again=false;try{again=await fn(ac.signal)}catch(e){}if(k===PK&&again)PT=setTimeout(tick,dl())};
 PT=setTimeout(tick,now?0:dl())}

/* ============ auth ============ */
async function login(){try{await api('login','POST',{password:$('#pw').value});$('#login').hidden=true;C.clear();go('dash');pollStatus()}catch(e){$('#le').textContent=(e&&e.message)||'Could not sign in'}}

