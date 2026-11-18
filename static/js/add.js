/* ============ ADD BUSINESSES ============ */
const AD={m:'m',rows:[{}],bulk:'',skip:1,busy:0,res:null,err:'',pg:0,pgt:0,L:[],jerr:0,built:0};
const norm=p=>String(p||'').replace(/\D/g,'').slice(-10);
let EX=null,EXT=-1,AU=0;
function existing(){const c=C.get('leads/phones');if(!c)return EX||new Set();if(EXT!==c.t){EX=new Set();for(const p of c.d){const n=norm(p);if(n.length>=7)EX.add(n)}EXT=c.t}return EX}
function mk(o,x){const g=k=>String(o[k]??'').trim();return Object.assign({raw:o,name:g('name'),phone:g('phone'),category:g('category'),website:g('website'),address:g('address'),tags:[],dup:0,err:0},x)}
function parseBulk(t){AD.jerr=0;t=t.trim();if(!t)return[];let j=null;try{j=JSON.parse(t)}catch(e){}
 if(j&&typeof j=='object'){return(Array.isArray(j)?j:[j]).map((o,i)=>{o=o&&typeof o=='object'?o:{};return mk(o,{json:1,src:i})})}
 if(/^[\[{]/.test(t))AD.jerr=1;
 return t.split(/\r?\n/).map(s=>s.trim()).filter(Boolean).map((line,i)=>{const p=line.split(/[,|\t]/).map(x=>x.trim());const o={name:p[0],phone:p[1]||''};
  if(p[2])o.category=p[2];if(p[3])o.website=p[3];if(p.length>4){const a=p.slice(4).join(', ');if(a)o.address=a}return mk(o,{line,src:i})})}
function entries(){
 if(AD.m=='m'){const L=[];AD.rows.forEach((r,i)=>{const o={name:(r.name||'').trim(),phone:(r.phone||'').trim()};['category','website','address'].forEach(k=>{const v=(r[k]||'').trim();if(v)o[k]=v});
  if(o.name||o.phone||o.category||o.website||o.address)L.push(mk(o,{src:i}))});return L}
 return parseBulk(AD.bulk)}
function annotate(L){const seen=new Set(),ex=existing();
 L.forEach(e=>{e.tags=[];e.dup=0;e.err=0;
  if(!e.name){e.err=1;e.tags.push(['e','Missing name']);return}
  const n=norm(e.phone);
  if(!e.phone)e.tags.push(['w','No phone']);else if(n.length<10)e.tags.push(['w','Check phone']);
  const key=n.length>=7?n:'nm:'+e.name.toLowerCase();
  if(seen.has(key)){e.dup=1;e.tags.push(['w','Repeated in list'])}else seen.add(key);
  if(n.length>=7&&ex.has(n)){e.dup=1;e.tags.push(['w','Already in leads'])}
  if(!e.tags.length)e.tags.push(['','Ready'])})}
const adValid=e=>!e.err&&!(AD.skip&&e.dup);
function pvHTML(L){
 const jb=AD.jerr?`<div class="err" style="margin:10px 14px">This looks like JSON but could not be read. Check brackets, commas and quotes.</div>`:'';
 if(!L.length)return `<div class="pv"><div class="ph"><span>Preview</span><span class="sub">Nothing detected yet</span></div>${jb}<div class="pr sub" style="padding:18px 14px">${AD.m=='m'?'Fill in a business above to see it here.':'Paste your list above to see what was detected.'}</div></div>`;
 const ok=L.filter(adValid).length,wn=L.filter(e=>e.tags.some(t=>t[0])).length;
 return `<div class="pv"><div class="ph"><span>${L.length} detected · ${ok} will be added</span><span class="sub">${wn?wn+' with warnings':'All good'}</span></div>${jb}<div class="pl">${L.slice(0,100).map(e=>`<div class="pr"><div class="av" style="width:32px;height:32px;border-radius:10px;font-size:13px">${initial(e.name)}</div><div class="t"><b>${esc(e.name||'(no name)')}</b><small>${esc([e.phone,e.category].filter(Boolean).join(' · ')||'No details')}</small></div><div class="tg">${e.tags.map(t=>`<span class="tag ${t[0]}">${t[1]}</span>`).join('')}</div></div>`).join('')}${L.length>100?`<div class="pr sub">+ ${L.length-100} more</div>`:''}</div></div>`}
const rowF=(r,i)=>`<div class="brow" data-i="${i}"><div class="bh"><b>Business ${i+1}</b><button class="btn ghost sm" aria-label="Remove business" data-a="adrm" data-i="${i}">${ic('trash-2')}</button></div>
 <div class="r2"><div class="field"><label>Name *</label><input data-f="name" value="${esc(r.name)}" autocomplete="off" placeholder="Ravi Realty"></div><div class="field"><label>Phone</label><input data-f="phone" value="${esc(r.phone)}" inputmode="tel" autocomplete="off" placeholder="98450 12345"></div></div>
 <div class="r2"><div class="field"><label>Category</label><input data-f="category" list="cats" value="${esc(r.category)}" autocomplete="off" placeholder="real estate"></div><div class="field"><label>Website</label><input data-f="website" value="${esc(r.website)}" inputmode="url" autocomplete="off" placeholder="https://"></div></div>
 <div class="field" style="margin:0"><label>Address</label><input data-f="address" value="${esc(r.address)}" autocomplete="off" placeholder="Area, city"></div></div>`;
function adRows(){const el=$('#adrows');if(el){el.innerHTML=AD.rows.map(rowF).join('');draw()}}
function adBody(){const b=$('#adbody');
 if(AD.m=='m'){b.innerHTML=`<div id="adrows"></div><button class="btn soft block" data-a="adadd">${ic('plus')}Add another business</button>`;adRows()}
 else{b.innerHTML=`<textarea id="adbulk" rows="7" placeholder="Ravi Realty, 98450 12345, real estate&#10;Green PG | 98765 43210 | pg">${esc(AD.bulk)}</textarea><p class="sub" style="margin:8px 0 0">One per line: <b>Name, phone, type</b> (optionally add , website, address). Commas, pipes or tabs work. You can also paste a JSON array.</p>`;draw()}}
function adFoot(){const f=$('#adft');if(!f)return;
 if(AD.busy){paint(f,`<div class="bar"><i style="width:${AD.pgt?Math.round(AD.pg/AD.pgt*100):0}%"></i></div><p class="sub" style="margin:8px 0 0">Adding ${AD.pg} of ${AD.pgt}...</p>`,1);return}
 const n=AD.L.filter(adValid).length,dc=AD.L.filter(e=>e.dup).length;
 paint(f,`${AD.err?`<div class="err">${esc(AD.err)}</div>`:''}${dc?`<label class="ck"><input type="checkbox" id="adskip" ${AD.skip?'checked':''}>Skip duplicates (${dc})</label>`:''}
 <div class="tools" style="margin:14px 0 0;justify-content:flex-end"><button class="btn soft" data-a="close">Cancel</button><button class="btn" data-a="adgo" ${n?'':'disabled'}>${ic('plus')}Add ${n} ${n==1?'business':'businesses'}</button></div>`)}
function adUpdate(){AD.L=entries();annotate(AD.L);
 const nm=AD.rows.filter(r=>ADK.some(k=>(r[k]||'').trim())).length;
 const a=$('#adn-m'),b=$('#adn-b');if(a)a.textContent=nm?'('+nm+')':'';if(b)b.textContent=AD.m=='b'?(AD.L.length?'('+AD.L.length+')':''):(AD.bulk.trim()?'•':'');
 paint($('#adpv'),pvHTML(AD.L),1);adFoot()}
const ADK=['name','phone','category','website','address'];
const adSched=()=>{if(!AU)AU=requestAnimationFrame(()=>{AU=0;adUpdate()})};
function adBuild(){
 if(AD.res){const r=AD.res;$('#adc').innerHTML=GRAB+`<div class="empty" style="padding:24px 10px 10px">${ic('check-circle-2')}<h1 style="font-size:20px;margin:0 0 6px">Done</h1><div class="sub">${r.added} added · ${r.updated} updated${r.skipped?' · '+r.skipped+' left in the form':''}</div></div>
  ${r.warnings.length?`<div class="wl"><b>${r.warnings.length} warning${r.warnings.length==1?'':'s'}</b><br>${r.warnings.slice(0,5).map(w=>esc(typeof w=='string'?w:JSON.stringify(w))).join('<br>')}${r.warnings.length>5?'<br>and more...':''}</div>`:''}
  <div class="tools" style="margin:16px 0 0;justify-content:flex-end"><button class="btn soft" data-a="admore">${ic('plus')}Add more</button><button class="btn sage" data-a="close">Done</button></div>`;draw();return}
 AD.built=1;
 $('#adc').innerHTML=GRAB+`<div class="top" style="margin-bottom:12px"><div><h1 style="font-size:20px">Add businesses</h1><div class="sub">Add them by hand or paste a list.</div></div><button class="btn ghost sm" data-a="close" aria-label="Close">${ic('x')}</button></div>
 <div class="seg" id="adseg"><button data-a="adtab" data-v="m" class="${AD.m=='m'?'on':''}">Add manually <span id="adn-m"></span></button><button data-a="adtab" data-v="b" class="${AD.m=='b'?'on':''}">Bulk paste <span id="adn-b"></span></button></div>
 <div id="adbody"></div><div id="adpv"></div><div id="adft"></div>`;
 $('#adpv')._h=null;$('#adft')._h=null;draw();adBody();adUpdate()}
function openAdd(){if(AD.res||!AD.built){AD.res=null;adBuild()}else adUpdate();openDlg(D1);
  const k='leads/phones';if(!C.has(k)||C.get(k).x)fetchC(k).then(()=>{if(D1.open&&!AD.res)adUpdate()}).catch(()=>{});
 if(!C.has(k))fetchC(k).then(()=>{if(D1.open&&!AD.res)adUpdate()}).catch(()=>{});
 const f=D1.querySelector('input[data-f],textarea');f&&f.focus({preventScroll:true})}
function adRemove(sent,L0){if(!sent.size)return;
 if(AD.m=='m'){const s=new Set([...sent].map(e=>e.src));AD.rows=AD.rows.filter((r,i)=>!s.has(i));if(!AD.rows.length)AD.rows.push({})}
 else{const rest=L0.filter(e=>!sent.has(e));AD.bulk=!rest.length?'':rest[0].json?JSON.stringify(rest.map(e=>e.raw),null,1):rest.map(e=>e.line).join('\n')}}
async function adGo(){if(AD.busy)return;AD.L=entries();annotate(AD.L);const L0=AD.L,L=L0.filter(adValid);if(!L.length)return;
 AD.busy=1;AD.err='';AD.pgt=L.length;AD.pg=0;const body=$('#adbody');body.inert=true;adFoot();
 const agg={added:0,updated:0,warnings:[],skipped:0},sent=new Set();let failed=false;
 try{for(let i=0;i<L.length;i+=20){const ch=L.slice(i,i+20),r=await api('leads','POST',ch.map(e=>e.raw));
   agg.added+=(r&&r.added)||0;agg.updated+=(r&&r.updated)||0;((r&&r.warnings)||[]).forEach(w=>agg.warnings.push(w));ch.forEach(e=>sent.add(e));AD.pg=Math.min(L.length,i+20);adFoot()}}
 catch(e){failed=true;AD.err=(e&&e.message)||'';if(e)AD.err+=(sent.size?` ${sent.size} saved before the error.`:'')+' Your remaining entries were kept.'}
 adRemove(sent,L0);AD.busy=0;body.inert=false;
 if(sent.size){afterMut();INIT.leads&&loadLeads()}
 if(!failed){agg.skipped=Math.max(0,L0.length-sent.size);AD.res=agg;toast(`Added ${agg.added}, updated ${agg.updated}`+(agg.warnings.length?`, ${agg.warnings.length} warning(s)`:''));adBuild()}
 else{adBody();$('#adft')._h=null;adUpdate()}}

