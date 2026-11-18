/* ============ HOME ============ */
/* 4th item = the Leads filter each card opens */
const DT=[['users','Total leads','total',{}],['phone','With phone','with_phone',{ph:1}],['send','Ready to message','ready',{rd:1}],['message-circle','Contacted','contacted',{ct:'1'}],['star','Replied or interested','warm',{st:'replied,interested'}]];
function shDash(){$('#p-dash').innerHTML=head('Overview','Your outreach at a glance')+`<div id="d-ban"></div><div class="glass pad" style="margin-bottom:14px"><div class="top" style="margin:0"><b>Sent today</b><span class="sub" id="d-st">${sk('70px','14px')}</span></div><div class="bar"><i id="d-bar" style="width:0"></i></div></div>
 <div class="grid">${DT.map((x,i)=>`<button class="glass stat link" data-a="statgo" data-i="${i}" aria-label="Show ${x[1]} in Leads"><div class="ico">${ic(x[0])}</div><b id="d${i}" class="sk" style="width:56px;height:30px;margin-bottom:4px"></b><span>${x[1]} ${ic('chevron-right')}</span></button>`).join('')}</div>
 <div class="tools"><button class="btn" data-a="go" data-v="send">${ic('send')}Start sending</button><button class="btn soft" data-a="go" data-v="find">${ic('search')}Find businesses</button></div>`;draw();paintBanner()}
function fillDash(s){DT.forEach((t,i)=>setv('d'+i,s[t[2]]));setv('d-st',`${s.sent_today} of ${s.limit}`);const b=$('#d-bar');if(b)b.style.width=(s.limit?Math.min(100,s.sent_today/s.limit*100):0)+'%'}
const loadDash=()=>swr('stats',{ttl:20000,render:fillDash});

