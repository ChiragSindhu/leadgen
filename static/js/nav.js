/* ============ navigation ============ */
$('nav').insertAdjacentHTML('beforeend',TABS.map(t=>`<button data-t="${t[0]}" data-a="go" data-v="${t[0]}">${ic(t[1])}<span>${t[2]}</span></button>`).join(''));
const NB=[...document.querySelectorAll('nav button')],PG=[...document.querySelectorAll('.pg')];
function go(t){if(tab)SC[tab]=scrollY;tab=t;stopPoll();if(t!='leads')selOff();
 NB.forEach(b=>b.classList.toggle('on',b.dataset.t==t));PG.forEach(p=>p.hidden=p.id!='p-'+t);
 if(!INIT[t]){INIT[t]=1;SH[t]()}scrollTo(0,SC[t]||0);
 LDR[t]().catch(e=>e&&toast(e.message))}
const PP={dash:()=>'stats',leads:()=>lk(),agent:()=>'stats',runs:()=>'runs',send:()=>'queue',set:()=>'settings',find:()=>'settings'};
function prefetch(t){const p=PP[t]();const c=C.get(p);if(c&&!c.x&&Date.now()-c.t<15000)return;fetchC(p).catch(()=>{})}
$('nav').addEventListener('pointerover',e=>{const b=e.target.closest('button[data-t]');if(b&&b.dataset.t!=tab)prefetch(b.dataset.t)});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&INIT[tab])LDR[tab]().catch(()=>{})});

/* ============ dialogs ============ */
function openDlg(d){if(!d.open)d.showModal()}
function closeDlg(d){if(!d||!d.open||d.classList.contains('out'))return;DS++;clearTimeout(RT);d.classList.add('out');setTimeout(()=>{d.classList.remove('out');d.close()},170)}
[D1,D2].forEach(d=>{let dn=false;d.addEventListener('pointerdown',e=>{dn=e.target===d});d.addEventListener('click',e=>{if(dn&&e.target===d)closeDlg(d);dn=false});d.addEventListener('cancel',e=>{e.preventDefault();closeDlg(d)})});
function showSheet(h,keep){const s=$('#pdc'),y=s.scrollTop;s.innerHTML=h;draw();s.scrollTop=keep?y:0}
const errSheet=m=>GRAB+`<div class="empty">${ic('alert-circle')}<div>${esc(m||'Something went wrong')}</div></div><button class="btn soft block" data-a="close">Close</button>`;

