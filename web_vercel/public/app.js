let snapshot=null;
const byId=id=>document.getElementById(id);
const time=value=>value?new Date(value).toLocaleString('es',{timeZone:'America/New_York'})+' ET':'Sin registro';
function textNode(tag,text){const node=document.createElement(tag);node.textContent=text;return node;}
function renderMedias(card,context){
 if(!context?.frames)return;
 const details=document.createElement('details');details.append(textNode('summary','Medias SMA de Hora y Diario'));
 for(const frame of context.frames){for(const pair of frame.pairs||[]){
  const state=pair.validated?`${pair.sessions_since_cross} sesiones desde el cruce`:'Tendencia pendiente de validar';
  details.append(textNode('p',`${frame.timeframe} ${pair.periods.join('/')} · ${pair.direction} · ${state}`));
 }}
 for(const level of context.levels||[])details.append(textNode('p',`${level.timeframe} SMA${level.period}: ${level.value.toFixed(2)} · distancia ${level.distance_pct.toFixed(3)}% · ${(level.role||'Contexto pendiente').replaceAll('_',' ').toLowerCase()}`));
 for(const level of context.price_levels?.levels||[])details.append(textNode('p',`${level.label}: ${level.value.toFixed(2)} · ${level.distance_pct.toFixed(3)}% ${level.ahead?'por delante':'por detrás'}`));
 details.append(textNode('p','Posibles pisos, techos y continuidad; no garantizan recorrido ni aprueban una entrada.'));
 card.append(details);
}
function renderResults(){
 const table=byId('results');table.replaceChildren();if(!snapshot)return;
 const study=snapshot.study;
 byId('study-time').textContent=study?`Actualizado: ${time(study.generated_at)}${Date.now()-Date.parse(study.generated_at)>600000?' · INFORME ATRASADO':''}`:'Estudio todavía no disponible con la regla actual.';
 const rows=(study?.summary||[]).filter(r=>r.origin===byId('origin').value&&r.horizon===Number(byId('horizon').value));
 for(const r of rows){const tr=document.createElement('tr');for(const value of [r.symbol,r.side==='SUPERIOR'?'Superior · alza':'Inferior · baja',r.sample,r.positive,r.negative,r.positive_pct===null?'—':r.positive_pct+'%',r.status==='MUESTRA_INSUFICIENTE'?'Faltan casos':'Descriptivo'])tr.append(textNode('td',String(value)));table.append(tr);}
 if(!rows.length){const tr=document.createElement('tr');const td=textNode('td','Todavía no hay resultados para esta selección.');td.colSpan=7;tr.append(td);table.append(tr);}
}
function render(data){
 snapshot=data;byId('dashboard').hidden=false;byId('login').hidden=true;byId('logout').hidden=Boolean(data.local_preview);
 byId('market').textContent=data.market_open?'Abierta':'Cerrada / sin calendario';
 byId('radar').textContent=data.radar_healthy?'Activo':'Sin respuesta reciente';
 byId('coverage').textContent=`${data.current.length} / ${data.configured.length}`;
 byId('notice').textContent=!data.market_open?'Esperando sesión regular. Las detecciones guardadas son historial.':!data.radar_healthy?'El radar no responde: no hay señales vigentes.':'Datos del radar remoto · avisos tempranos, sin garantía de continuidad.';
 if(data.local_preview)byId('notice').textContent='VISTA LOCAL DE REVISIÓN · todavía depende de tu PC. '+byId('notice').textContent;
 const signals=byId('signals');signals.replaceChildren();
 const active=data.radar_healthy?data.current.filter(item=>item.signal):[];
 for(const item of active){const card=document.createElement('article');card.className='signal'+(item.signal.side==='INFERIOR'?' down':'');card.append(textNode('strong',`${item.symbol} · ${item.signal.side==='SUPERIOR'?'ALCISTA / CALL':'BAJISTA / PUT'} · En formación`),textNode('p',`Precio observado: ${item.signal.price.toFixed(2)} · ${time(item.source_timestamp)}`));renderMedias(card,item.signal.ma_context);signals.append(card);}
 if(!active.length)signals.append(textNode('p',data.market_open?'Sin salidas vigentes que cumplan la regla.':'No hay señales activas fuera de la sesión regular.'));
 const history=byId('history');history.replaceChildren();for(const item of data.events.slice(0,15))history.append(textNode('p',`${item.symbol} · ${item.side} · ${time(item.detected_at)} · observación guardada`));
 byId('updated').textContent='Consulta: '+time(data.generated_at);renderResults();
}
async function refresh(){try{const response=await fetch('/api/dashboard',{cache:'no-store'});const data=await response.json();if(response.status===401){snapshot=null;byId('dashboard').hidden=true;byId('login').hidden=false;byId('logout').hidden=true;byId('notice').textContent=data.error;return;}if(!response.ok)throw Error(data.error||'No se pudo consultar el radar.');render(data);}catch(error){snapshot=null;byId('dashboard').hidden=true;byId('notice').textContent=error.message+' No hay datos vigentes disponibles.';}}
byId('login-form').addEventListener('submit',async event=>{event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;try{const response=await fetch('/api/dashboard',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:byId('password').value})});byId('password').value='';const data=await response.json();if(!response.ok)throw Error(data.error);await refresh();}catch(error){byId('notice').textContent=error.message;}finally{button.disabled=false;}});
byId('logout').addEventListener('click',async()=>{await fetch('/api/dashboard',{method:'DELETE'});await refresh();});
byId('origin').addEventListener('change',renderResults);byId('horizon').addEventListener('change',renderResults);
refresh();setInterval(refresh,30000);
