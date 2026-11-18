/* ============ MEDIA ============ */
const MT={'image/jpeg':5,'image/png':5,'image/webp':5,'video/mp4':16,'video/3gpp':16},MAXF=10,MAXT=100*1048576;let MU=0;
const mb=n=>(n/1048576).toFixed(1)+' MB',setMC=fn=>{const c=C.get('media');c&&put('media',fn(c.d))};
let ML=[],MO=0;const mon=()=>ML.filter(m=>m.on);
function fillMedia(L){ML=L||[];if(tab=='send'&&QM.loaded)drawSend();if(tab=='set')updTpl();if(tab=='send'||tab=='leads')warmMedia();const el=$('#mf');if(!el||MU)return;
 const tot=ML.reduce((a,m)=>a+m.size,0);
 paint(el,`<details id="mdet" ${MO?'open':''}><summary class="msum">${ic('images')}<b>Media</b><span class="sub">${ML.length?`${mon().length} of ${ML.length} on · ${mb(tot)}`:'None yet'}</span><span class="chev" style="display:block;margin-left:auto">${ic('chevron-down')}</span></summary>
 <div class="mg">${ML.map(m=>`<div class="mt ${m.on?'':'off'}" data-a="mprev" data-id="${esc(m.id)}">${m.type.startsWith('video')?`<div class="vd">${ic('play-circle')}</div>`:`<img loading="lazy" src="/api/media/${esc(m.id)}/file" alt="">`}<span class="cb ${m.on?'on':''}" data-a="mtog" data-id="${esc(m.id)}"></span><button class="x" data-a="rmmedia" data-id="${esc(m.id)}" aria-label="Delete">${ic('x')}</button></div>`).join('')}
 ${ML.length<MAXF?`<label class="mt add">${ic('plus')}<input id="mfile" type="file" multiple hidden accept="image/jpeg,image/png,image/webp,video/mp4,video/3gpp"></label>`:''}</div>
 <div id="mup" hidden style="margin-top:12px"><div class="bar"><i id="mbar" style="width:0"></i></div><p class="sub" id="mtx" style="margin:6px 0 0"></p></div>
 <p class="sub" style="margin:10px 0 0">Ticked files go with every message. Tap one to preview.</p></details>`)}
function upOne(f,onp){return new Promise((res,rej)=>{const fd=new FormData();fd.append('file',f);const x=new XMLHttpRequest();x.open('POST','/api/media');
 x.upload.onprogress=e=>e.lengthComputable&&onp(e.loaded/e.total);x.onerror=()=>rej(new Error('Network error'));
 x.onload=()=>{let j={};try{j=JSON.parse(x.responseText)}catch(e){}if(x.status==401){$('#login').hidden=false;return rej(0)}x.status>=400?rej(new Error(j.error||'Upload failed')):res(j)};x.send(fd)})}
const upMedia=async files=>{files=[...files];if(!files.length||MU)return;const L=(C.get('media')||{d:[]}).d;let n=L.length,tot=L.reduce((a,m)=>a+m.size,0),ok=[];for(const f of files){const lim=MT[f.type];if(!lim){toast(`${f.name}: use JPG, PNG, WebP, MP4 or 3GP`);continue}if(f.size>lim*1048576){toast(`${f.name}: must be under ${lim} MB`);continue}if(n>=MAXF){toast(`Limit is ${MAXF} files`);break}if(tot+f.size>MAXT){toast('Library is full (100 MB)');break}ok.push(f);n++;tot+=f.size}if(!ok.length)return;MU=MO=1;const dt=$('#mdet');dt&&(dt.open=true);$('#mup').hidden=false;let added=0;for(let i=0;i<ok.length;i++){const f=ok[i];$('#mtx').textContent=`Uploading ${i+1} of ${ok.length}: ${f.name}`;$('#mbar').style.width='0';try{const m=await upOne(f,p=>$('#mbar').style.width=p*100+'%');setMC(a=>a.concat(m));added++}catch(e){e&&toast(`${f.name}: ${e.message}`)}}MU=0;stale(/^queue/);added&&toast(`Uploaded ${added} file${added>1?'s':''}`);const c=C.get('media');c&&fillMedia(c.d)};

/* media toggle / delete: ONE version of each. Re-render from the cache every time. */
const afterMedia=()=>{const c=C.get('media');if(c)fillMedia(c.d)},TSEQ=new Map();
async function togMedia(id,on){const c=C.get('media');if(!c)return;
 const old=!!(c.d.find(m=>m.id==id)||{}).on,k=(TSEQ.get(id)||0)+1;TSEQ.set(id,k);
 const set=v=>{setMC(a=>a.map(m=>m.id==id?Object.assign({},m,{on:v}):m));afterMedia()};
 set(on);
 try{const r=await api('media/'+enc(id),'PATCH',{on});if(TSEQ.get(id)!==k)return;
  if(r&&typeof r.on=='boolean'&&r.on!==on)set(r.on);stale(/^queue/)}
 catch(e){if(TSEQ.get(id)===k)set(old);e&&toast(e.message)}}
async function rmMedia(id){if(!confirm('Delete this file? It will be removed from storage.'))return;
 try{await api('media/'+enc(id),'DELETE');setMC(a=>a.filter(m=>m.id!=id));BL.delete(id);TSEQ.delete(id);stale(/^queue/);afterMedia();toast('Deleted')}
 catch(e){e&&toast(e.message)}}
