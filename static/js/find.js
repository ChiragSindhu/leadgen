/* ============ FIND ============ */
const FTS=[['scrape','Maps scraper'],['osm','OpenStreetMap'],['google','Google API']],FD={scrape:'Free. Opens Google Maps in a hidden browser. Most complete, takes a few minutes.',osm:'Free. Open map data, fast, but many shops have no phone listed.',google:'Official Google Places. Free tier each month, then paid. Needs an API key.'};
let FS='scrape',FV={},JV=-1,JR=false,FB=0;const SKJ=`<div class="glass pad" style="margin-top:14px"><div class="top" style="margin:0 0 12px"><div style="display:flex;gap:10px;align-items:center">${sk('18px','18px','border-radius:50%')}${sk('110px','16px')}</div></div>${sk('100%','8px','display:block;border-radius:9px')}<div class="grid" style="margin:14px 0 0;grid-template-columns:repeat(3,1fr)">${[1,2,3].map(()=>`<div>${sk('38px','24px','display:block;margin-bottom:6px')}${sk('56px','11px','display:block')}</div>`).join('')}</div></div>`;
const keep=()=>{const g=id=>{const e=$('#'+id);return e?e.value:undefined};FV={c:g('fc')??FV.c,l:g('fl')??FV.l,n:g('fn')??FV.n,r:g('fr')??FV.r,k:g('fk')??FV.k}};
function shFind(){$('#p-find').innerHTML=head('Find businesses','Pick a source, then search')+`<div class="seg" id="fseg">${FTS.map(t=>`<button data-a="src" data-v="${t[0]}" class="${t[0]==FS?'on':''}">${t[1]}</button>`).join('')}</div><div class="glass pad" id="ff"></div><div id="jm"></div>`;renderForm()}
function renderForm(){const s=(C.get('settings')||{}).d||{};
 $('#ff').innerHTML=`<p class="sub" style="margin:0 0 16px">${FD[FS]}</p><div class="field"><label>Business type</label><input id="fc" placeholder="${FS=='osm'?'real estate, pg, gym or shop=bakery':'e.g. real estate'}" value="${esc(FV.c||'')}">
 <div class="chips">${['real estate','pg','gym','clinic','salon'].map(c=>`<button data-a="fill" data-t="fc" data-v="${c}">${c}</button>`).join('')}</div></div>
 <div class="field"><label>Area and city</label><input id="fl" placeholder="Indiranagar, Bengaluru" value="${esc(FV.l??s.last_location??'')}"></div>
 <div class="field"><label>How many to keep (1 to 2000)</label><input id="fn" type="number" inputmode="numeric" min="1" max="2000" value="${esc(FV.n||20)}"><div class="chips">${[10,20,30,50].map(n=>`<button data-a="fill" data-t="fn" data-v="${n}">${n}</button>`).join('')}</div></div>
 ${FS!='scrape'?`<div class="field"><label>Search radius in km (1 to 50)</label><input id="fr" type="number" inputmode="numeric" min="1" max="50" value="${esc(FV.r||5)}"><div class="chips">${[2,5,10,20].map(n=>`<button data-a="fill" data-t="fr" data-v="${n}">${n} km</button>`).join('')}</div></div>`:''}
 ${FS=='google'?'<div id="gx"></div>':''}<div id="fbz"></div><button class="btn block" id="fgo" data-a="find">${ic('search')}Start search</button>`;draw();fillGx();updFind()}
function updFind(){const b=$('#fgo');if(!b)return;b.toggleAttribute('disabled',!!(FB||BUSY));
 paint($('#fbz'),BUSY?`<div class="wl" style="margin:0 0 12px">${esc(busyMsg())}</div>`:'',1)}
function fillGx(){const g=$('#gx');if(!g)return;const k=$('#fk');if(k)FV.k=k.value;const s=((C.get('settings')||{}).d);
 g.innerHTML=`<div class="field"><label>Google API key</label><input id="fk" type="password" autocomplete="off" placeholder="${s&&s.has_google_key?'Saved. Leave empty to keep it':'Paste your key'}" value="${esc(FV.k||'')}">
 ${s?`<div class="bar"><i style="width:${s.google_cap?Math.min(100,s.google_used/s.google_cap*100):0}%"></i></div><p class="sub" style="margin:6px 0 0">${esc(s.google_used)} of ${esc(s.google_cap)} calls used this month. Search stops at the cap.</p>`:`<div style="margin-top:10px">${sk('100%','8px','display:block;border-radius:9px')}</div>`}</div>`}
function fillFind(s){const l=$('#fl');if(l&&FV.l==null&&!l.value&&s.last_location)l.value=s.last_location;fillGx()}
async function startFind(){const n=parseInt($('#fn').value);if(!(n>=1&&n<=2000))return toast('Enter a number from 1 to 2000');if(BUSY)return toast(busyMsg());if(FB)return;FB=1;updFind();
 try{await api('find','POST',{source:FS,category:$('#fc').value,location:$('#fl').value,n,radius_km:$('#fr')?.value,api_key:$('#fk')?.value});
  stale(/^settings/);JV=-1;JT=Date.now();paint($('#jm'),SKJ,1);poller(poll,3000,true);setTimeout(pollStatus,1000)}
 catch(e){e&&toast(e.message);pollStatus()}finally{FB=0;updFind()}}
async function poll(sig){const b=$('#jm');if(!b)return false;const j=await api('job?v='+JV,'GET',null,{signal:sig});
 if(!j){if(b._h===SKJ)paint(b,'',1);return JR}
 JV=j.v;const was=JR;JR=j.running;if(was&&!JR){afterJob();pollStatus()}
 if(j.msg=='idle'){paint(b,'',1);return false}
 const pct=j.total?Math.round(j.done/j.total*100):0;
 paint(b,`<div class="glass pad" style="margin-top:14px"><div class="top" style="margin:0 0 12px"><div style="display:flex;gap:10px;align-items:center">${j.running?'<div class="spinner"></div>':ic('check-circle-2')}<b>${esc(j.running?j.phase||'Working':'Finished')}</b></div><span class="sub">${j.running&&j.total?pct+'%':''}</span></div>
 <div class="bar"><i style="width:${j.running?(j.total?pct:6):100}%"></i></div><div class="grid" style="margin:14px 0 0;grid-template-columns:repeat(3,1fr)">${[['Collected',j.collected||0],['Skipped',j.skipped||0],['Checked',(j.done||0)+'/'+(j.total||'-')]].map(x=>`<div><b style="font-size:22px">${x[1]}</b><div class="sub">${x[0]}</div></div>`).join('')}</div>
 <p class="sub" style="margin:12px 0 0">${esc(j.msg)}</p>${j.run_id?`<button class="btn soft sm" style="margin-top:10px" data-a="go" data-v="runs">${ic('history')}View run log</button>`:''}</div>`);
 return j.running}
async function loadFind(){JV=-1;const b=$('#jm');if(!b._h)paint(b,SKJ,1);poller(poll,3000,true);pollStatus();swr('settings',{ttl:60000,render:fillFind}).catch(()=>{})}

