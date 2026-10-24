'use strict';
(() => {
  const tg = window.Telegram && window.Telegram.WebApp;
  const fragment = new URLSearchParams(location.hash.slice(1));
  let intent = fragment.get('intent');
  const watch = fragment.get('watch');
  const entrySymbol = fragment.get('entry');
  const initData = tg && tg.initData; // Signed raw string, never initDataUnsafe.
  const byId = id => document.getElementById(id);
  let history = [], currentMark = null, activeReview = null, polling = false;
  const prices = value => value === null || value === undefined ? '—' : '$' + Number(value).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 6});
  const money = value => value === null || value === undefined ? '—' : '$' + Number(value).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const states = {WORKING:'Orden simulada pendiente', PARTIALLY_FILLED:'Compra parcialmente ejecutada', FILLED:'Compra ejecutada en simulación', CANCELED:'Compra cancelada', REJECTED:'Compra rechazada', UNKNOWN:'Resultado incierto: conciliación pendiente', UNCERTAIN:'Resultado incierto: no se repetirá la compra', BLOCKED_OR_UNCERTAIN:'Compra bloqueada o pendiente de conciliación. Vuelve a preparar la ficha en Telegram.'};
  function message(text, error = false) { byId('status').textContent = text; byId('status').classList.toggle('error', error); }
  async function api(path, extras = {}) {
    const response = await fetch('api/' + path, {method:'POST', credentials:'omit', cache:'no-store', headers:{'Content-Type':'application/json'}, body:JSON.stringify({init_data:initData, intent, ...extras})});
    if (!response.ok) throw new Error('REQUEST_FAILED');
    return response.json();
  }
  function draw() {
    const canvas = byId('chart'), ratio = window.devicePixelRatio || 1;
    canvas.width = Math.floor(canvas.clientWidth * ratio); canvas.height = 230 * ratio;
    const ctx = canvas.getContext('2d'); ctx.scale(ratio, ratio);
    const w = canvas.clientWidth, h = 230; ctx.clearRect(0,0,w,h);
    if (!history.length) {ctx.fillStyle='#a2b3cc'; ctx.fillText('Esperando observaciones vigentes…',16,35);return;}
    const levels = [['Prima',currentMark.average_fill,'#a2b3cc'],['Objetivo',currentMark.target,'#4ade80'],['Stop',currentMark.stop,'#fb7185']].filter(row => row[1] !== null && row[1] !== undefined);
    const values = history.map(p=>p.bid).concat(levels.map(row=>Number(row[1])));
    const lo = Math.min(...values), hi = Math.max(...values), span = Math.max(hi-lo,.02), first=history[0].time, last=history[history.length-1].time;
    const x = time => 42 + (time-first)/Math.max(last-first,1)*(w-66);
    const y = value => 195 - (value-lo+span*.1)/(span*1.2)*160;
    levels.forEach(([name,value,color])=>{ctx.strokeStyle=color;ctx.setLineDash([5,4]);ctx.beginPath();ctx.moveTo(42,y(Number(value)));ctx.lineTo(w-12,y(Number(value)));ctx.stroke();ctx.fillStyle=color;ctx.fillText(name+' '+prices(value),44,y(Number(value))-5);});
    ctx.setLineDash([]);ctx.strokeStyle='#38bdf8';ctx.fillStyle='#38bdf8';ctx.beginPath();
    history.forEach((point,index)=>{if(!index || point.time-history[index-1].time>30000)ctx.moveTo(x(point.time),y(point.bid));else ctx.lineTo(x(point.time),y(point.bid));});ctx.stroke();
    history.forEach(point=>{ctx.beginPath();ctx.arc(x(point.time),y(point.bid),2,0,Math.PI*2);ctx.fill();});
  }
  function render(data) {
    message(states[data.status] || 'Consulta de estado simulada', ['UNKNOWN','UNCERTAIN','BLOCKED_OR_UNCERTAIN'].includes(data.status));
    const s=data.selection;document.querySelector('h1').textContent='Mi operación simulada'; byId('selection').hidden=false;byId('contract').textContent=s.symbol+' · '+s.side+' · '+s.contract;
    byId('summary').textContent=s.quantity+' contratos · Ask revisado '+prices(s.ask)+' · Ganancia '+(s.target==='MANUAL'?'manual':s.target+'%')+' · Stop '+s.stop+'%';
    byId('fill').textContent=data.filled_quantity===undefined?'Solicitud sin ejecución confirmada':'Ejecutados '+data.filled_quantity+' / '+data.quantity;
    const sale=data.sale_report;
    byId('sale-result').hidden=!sale;
    if(sale){
      const complete=sale.status==='CLOSED';
      if(complete)message('Posición cerrada · Venta confirmada en simulación');
      byId('sale-title').textContent=complete?'Venta confirmada · Simulación':'Venta parcial confirmada · Simulación';
      byId('sale-quantity').textContent='Vendidos '+sale.sold_quantity+' / '+sale.opened_quantity+' · Restantes '+sale.remaining_quantity;
      byId('sale-prices').textContent='Entrada media '+prices(sale.entry_average)+' · Venta media '+prices(sale.exit_average);
      byId('sale-gross').textContent='Resultado bruto confirmado: '+money(sale.gross_pnl)+' ('+Number(sale.gross_pct).toFixed(2)+'%)';
      byId('sale-net').textContent=sale.fees_known===false?'Costos no verificados · Neto no disponible':'Neto confirmado: '+money(sale.net_pnl)+' · Costos registrados '+money(sale.fees);
      const reasons={TARGET:'Objetivo de ganancia',LOSS_LIMIT:'Stop loss',MANUAL_CLOSE:'Cierre manual',TIME_LIMIT:'Límite de tiempo'};
      byId('sale-reason').textContent=sale.reasons.map(reason=>reasons[reason]||'Otro cierre confirmado').join(' · ')+' · '+new Date(sale.closed_at).toLocaleTimeString('es-US',{timeZone:'America/New_York'})+' ET';
    }
    const m=data.mark, live=m && m.status==='LIVE';currentMark=m;
    ['average','bid','pnl','net','target','stop'].forEach(id=>byId(id).textContent='—'); byId('pct').textContent='';byId('pnl').className='';
    if(m){byId('average').textContent=prices(m.average_fill);byId('bid').textContent=prices(m.bid);byId('bid-label').textContent=live?'Bid actual':'Último Bid · no vigente';byId('target').textContent=m.target===null?'Cierre manual':prices(m.target);byId('stop').textContent=prices(m.stop);
      byId('quote-age').textContent=(live?'Cotización vigente':'Sin resultado actual: '+m.status)+(m.quote_timestamp?' · '+new Date(m.quote_timestamp).toLocaleTimeString('es-US',{timeZone:'America/New_York'})+' ET · '+Number(m.age_seconds).toFixed(1)+' s':'');
      if(live){byId('pnl').textContent=money(m.gross_pnl);byId('pct').textContent=Number(m.gross_pct).toFixed(2)+'% bruto';byId('pnl').className=Number(m.gross_pnl)>=0?'positive':'negative';byId('net').textContent=money(m.net_estimate);
        const stamp=Date.parse(m.quote_timestamp);if(!history.length || stamp>history[history.length-1].time){history.push({time:stamp,bid:Number(m.bid)});history=history.slice(-300);}}
    }else{byId('quote-age').textContent=data.position_open===false?'Sin posición abierta. El estado de la compra no implica que siga abierta.':'Esperando datos y conciliación de la posición.';history=[];}
    byId('actions').hidden=false;byId('close').hidden=!data.position_open;byId('pending').replaceChildren();
    (data.pending || []).forEach(order=>{const text=document.createElement('p');text.textContent=(order.instruction==='BUY_TO_OPEN'?'Compra':'Salida')+' · '+order.status+' · '+order.filled_quantity+'/'+order.quantity;byId('pending').append(text);
      const button=document.createElement('button');button.textContent='Cancelar remanente simulado';button.className='secondary';button.disabled=!['WORKING','PARTIALLY_FILLED'].includes(order.status);button.onclick=()=>prepare('cancel',order.key);byId('pending').append(button);});draw();
  }
  async function prepare(action, orderKey = null) {
    try {activeReview=await api('prepare',{action,order_key:orderKey});byId('review-text').textContent=(action==='close'?'Cerrar '+activeReview.quantity+' contratos · Límite mínimo '+prices(activeReview.minimum_price):'Cancelar la cantidad pendiente: '+activeReview.quantity)+' · Simulación local';byId('confirm').textContent=action==='close'?'Confirmar cierre simulado':'Confirmar cancelación simulada';byId('confirm').disabled=false;byId('review').hidden=false;}
    catch(_){message('No se pudo preparar la acción. Comprueba datos y estado; no se envió otra solicitud.',true);}
  }
  byId('close').onclick=()=>prepare('close');byId('dismiss').onclick=()=>{activeReview=null;byId('review').hidden=true;};
  byId('confirm').onclick=async()=>{if(!activeReview)return;byId('confirm').disabled=true;const review=activeReview;activeReview=null;try{await api('confirm',{review_id:review.id});byId('review').hidden=true;await refresh();}catch(_){message('Resultado pendiente de comprobación. No se repetirá la solicitud.',true);}};
  async function refresh(){if(polling)return;polling=true;try{render(await api('state'));}catch(_){['bid','pnl','net'].forEach(id=>byId(id).textContent='—');byId('pct').textContent='';byId('pnl').className='';byId('close').hidden=true;message('Actualización no disponible. No se reenvía la compra.',true);}finally{polling=false;}}
  window.addEventListener('resize',draw);
  if(entrySymbol && !intent){
    ['position-metrics','position-chart','quote-age'].forEach(id=>byId(id).hidden=true);
    byId('entry-panel').hidden=false;document.querySelector('h1').textContent='Compra simulada';
    if(!initData){message('Abre la preparación desde Telegram para verificar tu sesión. No se ha comprado nada.',true);return;}
    tg.ready();tg.expand();
    const reference={symbol:entrySymbol,side:fragment.get('side'),candle:fragment.get('candle')};
    const reasons={NO_CURRENT_SIGNAL:'La estrategia no se cumple ahora. Puedes conservar tu selección; no se comprará automáticamente.',
      TRADE_NOT_CURRENT:'El último trade IEX no está vigente. No se ha confirmado una retracción: faltan datos actuales.',
      DETECTOR_STATE_INVALID:'Estado del detector no válido.',COLLECTOR_NOT_CURRENT:'El colector no tiene datos vigentes.',
      MONITOR_NOT_READY:'El monitor de salidas no está listo.',SIGNAL_CHANGED:'La vela de este aviso cambió. Usa la señal actual.',
      SIGNAL_DIRECTION_CHANGED:'La dirección cambió. Usa la señal actual.',OUTSIDE_OFFICIAL_SESSION:'Sesión regular cerrada.',
      NO_ELIGIBLE_CONTRACTS:'La señal y el contrato se evalúan por separado: no hay contrato que cumpla ITM u OTM hasta el quinto strike, rango de Ask, spread, vencimiento y frescura.',
      CONTRACT_NO_LONGER_ELIGIBLE:'El contrato dejó de cumplir ITM u OTM hasta el quinto strike, rango de Ask, spread o vigencia en la comprobación final. La compra no se envió. Revisa la cotización actual antes de confirmar otra vez.',
      SECURE_REQUEST_ID_UNAVAILABLE:'No se pudo preparar la solicitud segura. No se envió ninguna compra. Cierra y abre de nuevo la MiniApp.',
      OPTION_QUOTES_UNAVAILABLE:'Schwab no entregó contratos que superen la validación.',PRICE_CHANGED:'El Ask, costo o plan cambió. Revisa la cotización antes de otra compra.',
      MARKET_DATA_COOLDOWN:'Esperando el intervalo indicado por el proveedor.',RATE_LIMITED:'El proveedor requiere esperar.',
      ASK_CHANGED_PREPARE_AGAIN:'El Ask cambió durante la comprobación. No se envió la compra; revisa el precio y confirma de nuevo.',
      MANUAL_CONFIRMATION_ASK_CHANGED:'El Ask cambió durante la comprobación. No se envió la compra; revisa el precio y confirma de nuevo.',
      MANUAL_CONFIRMATION_COST_CHANGED:'El costo cambió. Revisa el importe y confirma otra vez; no se envió la compra.',
      EXIT_REVIEW_NOT_CURRENT:'La revisión caducó antes del envío. Revisa los datos actuales y confirma otra vez.',
      UNDERLYING_QUOTE_NOT_CURRENT:'La cotización de la acción en Schwab no está vigente para preparar contratos.',
      OPTIMAL_PREMIUM_RANGE_MISSING:'Esta compañía no tiene rango de prima configurado. Falta definirlo; no es un fallo de la estrategia.',
      DELIVERED_ALERT_REQUIRED:'Falta verificar el aviso original entregado para esta compañía y dirección.',
      ALERT_WINDOW_ENDED:'Terminó la sesión de este aviso. La selección queda visible, sin compra con precios antiguos.',
      ALERT_REFERENCE_QUARANTINED:'El proveedor corrigió datos de referencia; requieren revisión.',
      TELEGRAM_AUTH_REQUIRED:'El acceso de compra caducó. Vuelve a Telegram y abre otra vez el botón del aviso; esto no es una retracción de la estrategia.'};
    let catalog=null,submitting=false,refreshing=false,selectedContract='',selectedSnapshot=null,outcome=null,chainPage=0;
    const contractReasons={OUTSIDE_ALLOWED_MONEYNESS:'Fuera de ITM o primeros 5 strikes OTM',NOT_ITM:'No es ITM (regla anterior)',ASK_OUTSIDE_RANGE:'Ask fuera de tu rango',SPREAD_EXCEEDS_MAX:'Spread superior a $0.08',SPREAD_EXCEEDS_005:'Spread superior a $0.05 (regla anterior)',
      QUOTE_NOT_CURRENT:'Cotización no vigente',UNDERLYING_NOT_CURRENT:'Precio de la acción no vigente',INVALID_OPTION_MARKET:'Mercado no válido',
      UNVERIFIED_FEED:'Fuente no verificada',NOT_SELECTED_BY_CANONICAL_CHECKS:'No supera la validación del contrato',
      EXPIRATION_NOT_SELECTED:'El vencimiento ya no corresponde a la regla horaria',CONTRACT_UNAVAILABLE:'Schwab no devolvió una cotización válida de este contrato'};
    const chainContracts=()=>catalog&&catalog.contract_diagnostics&&(catalog.contract_diagnostics.contracts||catalog.contract_diagnostics.itm_contracts)||[];
    const observedContracts=()=>chainContracts().length?chainContracts():catalog&&catalog.contract_diagnostics&&catalog.contract_diagnostics.itm_contracts||[];
    const describeContract=c=>(c.reasons||[]).map(code=>contractReasons[code]||'Requiere revisión').join(' · ');
    // Preparation only: no credentials, authorization, intents or fills. Restored
    // quotes are display-only; choice() always uses the current server catalog.
    const draftPrefix='jjtrade.manual.preparation.v1:',draftKey=()=>draftPrefix+reference.symbol+':'+reference.side+':'+reference.candle;
    function remember(){
      try{localStorage.setItem(draftKey(),JSON.stringify({saved:Date.now(),contract:selectedContract,snapshot:selectedSnapshot,
        quantity:byId('entry-quantity').value,target:byId('entry-target').value}));}catch(_){}
    }
    function restore(){
      try{
        const saved=JSON.parse(localStorage.getItem(draftKey()));
        if(saved&&Date.now()-saved.saved>=0&&Date.now()-saved.saved<86400000&&typeof saved.contract==='string'){
          selectedContract=saved.contract;selectedSnapshot=saved.snapshot;
          byId('entry-quantity').value=saved.quantity||'';byId('entry-target').value=saved.target||'';
        }
        for(const key of Object.keys(localStorage)){if(key.startsWith(draftPrefix)){
          try{const item=JSON.parse(localStorage.getItem(key));if(!item||Date.now()-item.saved>=86400000)localStorage.removeItem(key);}catch(_){localStorage.removeItem(key);}
        }}
      }catch(_){}
    }
    restore();
    function feedback(kind,reason=null,details=[]){
      outcome={kind,reason,details};const box=byId('entry-feedback');
      if(!box||!byId('entry-feedback-title')||!byId('entry-feedback-detail')){message('Comprobando la compra simulada. '+(reasons[reason]||'No se repetirá la solicitud.'),true);return;}
      box.hidden=false;
      byId('entry-feedback-title').textContent=kind==='pending'?'Procesando compra simulada':kind==='uncertain'?'Comprobando el resultado':'Compra no enviada';
      byId('entry-feedback-detail').textContent=kind==='pending'?'Validando el precio y el contrato. Si se acepta, aquí se abrirá el seguimiento de tu operación.':
        kind==='uncertain'?'Todavía no hay confirmación. Consultaremos el recibo sin repetir la compra.':
        reasons[reason]||'La validación detuvo la compra antes del envío. Revisa los datos actuales y confirma de nuevo si decides continuar.';
      if(kind==='blocked'&&details.length)byId('entry-feedback-detail').textContent+=' Motivo del contrato: '+details.map(code=>contractReasons[code]||'Requiere revisión').join(' · ')+'. No existe una posición creada por este intento.';
      byId('entry-buy-state').textContent=byId('entry-feedback-detail').textContent;
      try{box.scrollIntoView({block:'nearest',behavior:'smooth'});}catch(_){}
    }
    const accessCurrent=()=>!catalog || !catalog.access_expires_utc || Date.now()<=Date.parse(catalog.access_expires_utc);
    byId('entry-reopen').onclick=()=>{if(tg.close)tg.close();};
    byId('entry-current').onclick=()=>{
      if(!catalog||!catalog.current_candle||submitting)return;
      reference.candle=catalog.current_candle;catalog=null;selectedContract='';selectedSnapshot=null;
      byId('entry-contract').value='';byId('entry-quantity').value='';byId('entry-target').value='';
      byId('entry-current').hidden=true;refreshEntry();
    };
    async function entryApi(path,extra={}){
      const response=await fetch('api/'+path,{method:'POST',credentials:'omit',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify({init_data:initData,...extra})});
      const data=await response.json();if(!response.ok){const error=new Error(data.error||'ENTRY_CHECK_FAILED');error.beforeDispatch=[400,403].includes(response.status);throw error;}return data;
    }
    function choice(){
      const contract=(catalog&&catalog.contracts||[]).find(c=>c.symbol===selectedContract);
      const quantity=Number(byId('entry-quantity').value),target=byId('entry-target').value;
      const valid=contract&&Number.isInteger(quantity)&&quantity>0&&quantity<=100000&&target;
      const total=valid?(Number(contract.ask)*100*quantity+Number(catalog.fee_per_contract||0)*quantity).toFixed(6):null;
      return {contract,quantity,target,total,valid};
    }
    function updateChoice(){
      const c=choice();byId('entry-buy').disabled=!(c.valid&&catalog&&catalog.buy_ready&&accessCurrent()&&!submitting);
      let pending='Listo para confirmar tu compra simulada. Revisa el importe antes de pulsar.';
      if(submitting)pending='Solicitud en comprobación. No se repetirá la compra automáticamente.';
      else if(!catalog)pending='Comprobando datos para preparar tu compra.';
      else if(!accessCurrent())pending=reasons.TELEGRAM_AUTH_REQUIRED;
      else if(!catalog.buy_ready)pending=reasons[catalog.reason]||'Esperando datos y autorización para esta preparación.';
      else if(!c.contract)pending='Falta seleccionar un contrato ITM u OTM apto.';
      else if(!Number.isInteger(c.quantity)||c.quantity<1||c.quantity>100000)pending='Falta indicar una cantidad entera de contratos, entre 1 y 100000.';
      else if(!c.target)pending='Falta elegir un objetivo de ganancia o «Cierre manual».';
      byId('entry-buy-state').textContent=outcome&&outcome.kind==='blocked'?'Último intento: compra no enviada. Lee el resultado debajo del botón. '+pending:pending;
      byId('entry-cost').textContent=c.total?'Importe de primas '+money(c.total)+(catalog.fees_known===false?' · Costos no verificados':''):'Elige contrato, cantidad y objetivo.';
      byId('entry-reopen').hidden=accessCurrent();
      const observed=observedContracts().find(row=>row.symbol===selectedContract),shown=c.contract||observed||selectedSnapshot;
      byId('entry-quote').textContent=shown?(c.contract?'Cotización actual · ':observed?(observed.itm?'ITM':'OTM')+' observado · No apto para comprar · ':'Última cotización conservada · No utilizable para comprar · ')+'Strike '+shown.strike+' · Bid '+prices(shown.bid)+' · Ask '+prices(shown.ask)+' · Tamaños '+shown.bid_size+'/'+shown.ask_size+' · '+new Date(shown.quote_timestamp).toLocaleTimeString('es-US',{timeZone:'America/New_York'})+' ET'+(observed&&!c.contract?' · '+describeContract(observed):''):'';
      if(selectedContract&&!c.contract&&!submitting)byId('entry-buy-state').textContent='Contrato seleccionado para revisar. '+(observed?describeContract(observed):reasons[catalog&&catalog.reason]||'No cumple los controles actuales o falta cotización vigente.')+' No se ha enviado ninguna compra.';
    }
    function adopt(data){
      if(!data.intent)return false;
      intent=data.intent;byId('entry-panel').hidden=true;
      document.querySelector('h1').textContent='Mi operación simulada';
      message('Compra aceptada en simulación · Cargando estado y seguimiento.');
      try{if(window.history&&window.history.replaceState)window.history.replaceState(null,'','#intent='+encodeURIComponent(intent));}catch(_){}
      try{localStorage.removeItem(draftKey());}catch(_){}
      ['position-metrics','position-chart','quote-age'].forEach(id=>byId(id).hidden=false);
      let rendered=false;
      try{if(data.selection){render(data);rendered=true;}}catch(_){message('Compra aceptada · Comprobando el recibo. No se repetirá la compra.',true);}
      if(!rendered)refresh();
      // Bring the new position view into the phone viewport after the entry
      // form disappears; don't leave the user at the old button's scroll offset.
      try{document.querySelector('h1').scrollIntoView({block:'start',behavior:'smooth'});}catch(_){}
      return true;
    }
    function renderContractDiagnostics(data){
      const d=data.contract_diagnostics,show=!!(d&&d.read_only&&!(data.contracts||[]).length);
      byId('entry-diagnostics').hidden=!show;byId('entry-observed-contracts').replaceChildren();
      if(!show)return;
      byId('entry-diagnostic-summary').textContent='Acción '+prices(d.underlying_price)+' · Vence '+d.expiration+
        ' · '+d.counts.observed+' observados / '+d.counts.eligible+' aptos · Ask requerido '+prices(d.premium_low)+'–'+prices(d.premium_high)+' · Spread máximo '+prices(d.max_spread);
      const observed=[...(d.observed||[])];
      if(d.nearest_itm&&!observed.some(c=>c.symbol===d.nearest_itm.symbol))observed.unshift(d.nearest_itm);
      observed.forEach(c=>{
        const row=document.createElement('p');
        row.textContent=(c.itm?'ITM ':'No ITM ')+c.strike+' · Bid '+prices(c.bid)+' · Ask '+prices(c.ask)+' · Spread '+prices(c.spread)+
          ' · '+describeContract(c)+
          (c.quote_timestamp?' · '+new Date(c.quote_timestamp).toLocaleTimeString('es-US',{timeZone:'America/New_York'})+' ET':'');
        byId('entry-observed-contracts').append(row);
      });
    }
    function renderChain(){
      const all=chainContracts().filter(c=>typeof c.symbol==='string');
      const rows=all.filter(c=>byId('entry-chain-all').checked||c.itm||(catalog.contracts||[]).some(q=>q.symbol===c.symbol));
      const pages=Math.max(1,Math.ceil(rows.length/20));chainPage=Math.min(chainPage,pages-1);
      const visible=rows.slice(chainPage*20,chainPage*20+20),table=byId('entry-chain-rows');
      const same=table.children.length===visible.length&&visible.every((c,i)=>table.children[i].dataset.symbol===c.symbol);
      if(!same)table.replaceChildren();
      visible.forEach((c,i)=>{
        const row=same?table.children[i]:document.createElement('tr');row.dataset.symbol=c.symbol;
        if(!same){for(let n=0;n<6;n++)row.append(document.createElement('td'));const cell=document.createElement('td');cell.append(document.createElement('button'));row.append(cell);table.append(row);}
        const age=Math.max(0,(Date.now()-Date.parse(c.quote_timestamp))/1000);
        const valid=(catalog.contracts||[]).some(q=>q.symbol===c.symbol);
        [c.strike,c.itm?'ITM':(c.otm_position?'OTM '+c.otm_position+'º':'OTM'),prices(c.bid),prices(c.ask),prices(c.spread),(valid?'Apto':describeContract(c))+' · '+age.toFixed(1)+' s'].forEach((text,j)=>row.children[j].textContent=text);
        const button=row.children[6].children[0];button.textContent=c.symbol===selectedContract?'Seleccionado':'Elegir';button.disabled=submitting;
        button.onclick=()=>{if(submitting)return;byId('entry-contract').value=c.symbol;selectContract();renderChain();};
      });
      byId('entry-chain-time').textContent=catalog&&catalog.checked_utc?'Última consulta '+new Date(catalog.checked_utc).toLocaleTimeString('es-US',{timeZone:'America/New_York'})+' ET · '+all.length+' contratos observados · Precios con su hora de proveedor':'Esperando cadena actual.';
      byId('entry-chain-page').textContent=(chainPage+1)+' / '+pages+' · '+rows.length+' contratos';
      byId('entry-chain-prev').disabled=chainPage===0;byId('entry-chain-next').disabled=chainPage+1>=pages;
    }
    byId('entry-chain-all').onchange=()=>{chainPage=0;renderChain();};
    byId('entry-chain-prev').onclick=()=>{chainPage=Math.max(0,chainPage-1);renderChain();};
    byId('entry-chain-next').onclick=()=>{chainPage++;renderChain();};
    byId('entry-refresh').onclick=()=>refreshEntry(true);
    async function refreshEntry(forceQuote=false){
      if(intent){await refresh();return;}if(refreshing)return;refreshing=true;
      try{
        const force=forceQuote===true&&selectedContract&&!submitting;
        const data=await entryApi(submitting?'entry-result':force?'entry-refresh':'entry-catalog',submitting?{}:force?{...reference,contract:selectedContract}:reference);
        if(adopt(data))return;
        if(submitting&&data.status==='ENTRY_BLOCKED'){
          submitting=false;if(catalog)catalog.buy_ready=false;byId('entry-buy').disabled=true;
          feedback('blocked',data.reason,data.contract_reasons||[]);message(reasons[data.reason]||'El recibo confirma que no se envió la compra. Revisa los datos antes de otro intento.',true);return;
        }
        if(submitting){feedback('uncertain');message('Solicitud en comprobación. No se repetirá la compra automáticamente.',true);return;}
        catalog=data;
        if(data.last_entry_result&&!outcome)feedback('blocked',data.last_entry_result.reason,data.last_entry_result.contract_reasons||[]);
        renderContractDiagnostics(data);
        byId('entry-title').textContent=data.symbol+' · '+data.side+' · SIMULACIÓN';
        byId('entry-range').textContent='Spot '+prices(data.underlying_price)+' · Ask en rango '+prices(data.premium_low)+'–'+prices(data.premium_high)+(data.expiration?' · Vence '+data.expiration:'');
        byId('entry-stop').textContent='Stop '+data.stop+'% de la prima ejecutada · Cierre manual disponible';
        const options=byId('entry-contract'),rows=[{symbol:'',label:'Selecciona un contrato ITM u OTM (hasta 5.º)'}];
        // Choose once, never replace a pinned contract when spot/quotes move.
        if(!selectedContract&&(data.contracts||[]).length){
          selectedContract=data.recommended_contract||data.contracts[0].symbol;
        }
        (data.contracts||[]).forEach(c=>{rows.push({symbol:c.symbol,label:(c.itm===false?'OTM '+(c.otm_position?c.otm_position+'º ':''):'ITM ')+c.strike+' · Ask '+prices(c.ask)});if(c.symbol===selectedContract)selectedSnapshot=c;});
        const observed=observedContracts().filter(c=>!rows.some(r=>r.symbol===c.symbol));
        // Reviewable identities never enter choice()'s actionable catalog.
        if(!selectedContract&&observed.length)selectedContract=(observed.find(c=>c.itm)||observed[0]).symbol;
        observed.forEach(c=>{rows.push({symbol:c.symbol,label:(c.itm?'ITM ':'OTM ')+c.strike+' · Ask '+prices(c.ask)+' · Solo revisión: '+describeContract(c)});if(c.symbol===selectedContract)selectedSnapshot=c;});
        if(selectedContract&&!rows.some(r=>r.symbol===selectedContract))rows.push({symbol:selectedContract,label:'Contrato conservado · Strike '+(selectedSnapshot?selectedSnapshot.strike:'—')+' · Esperando cotización apta',disabled:true});
        // Keep the native dropdown open while quotes change. Replace only when
        // its contract identities change, not on every three-second poll.
        const same=options.options.length===rows.length&&rows.every((r,i)=>options.options[i].value===r.symbol);
        if(!same)options.replaceChildren();
        rows.forEach((r,i)=>{const option=same?options.options[i]:document.createElement('option');option.value=r.symbol;option.textContent=r.label;option.disabled=!!r.disabled;if(!same)options.append(option);});
        options.value=selectedContract;
        byId('entry-signal').textContent=data.entry_authorized?
          'Aviso detectado · Preparación manual conservada durante esta sesión. Un retroceso o cambio de vela no cancela el aviso.':
          data.signal_ready?'Estrategia vigente ahora.':'Estrategia en espera: '+(reasons[data.signal_reason]||reasons[data.reason]||'comprobando datos');
        byId('entry-contract-status').textContent=data.contracts&&data.contracts.length?(data.preparation_ready?'Contratos disponibles para preparar; se revalidan al comprar.':'Contratos observados.'):(reasons[data.contract_reason]||'Sin contratos actuales para esta preparación.');
        byId('entry-current').hidden=!data.current_candle;
        byId('entry-reason').textContent=data.buy_ready?(data.entry_authorized?'Aviso verificado y contratos actuales. Elige y confirma la compra.':'Señal y contratos vigentes. Elige y confirma la compra.'):reasons[data.reason]||'Compra bloqueada: '+(data.reason||'datos pendientes');
        message(data.buy_ready?'Preparación manual · Datos reales':data.reason==='NO_ELIGIBLE_CONTRACTS'?'Preparación abierta · Sin contrato apto':'Preparación abierta · Compra bloqueada',!data.buy_ready);updateChoice();remember();renderChain();
      }catch(error){
        if(catalog){catalog.buy_ready=false;catalog.contracts=[];if(catalog.contract_diagnostics){catalog.contract_diagnostics.itm_contracts=[];catalog.contract_diagnostics.contracts=[];}catalog.reason=error.message;updateChoice();}
        byId('entry-diagnostics').hidden=true;byId('entry-buy').disabled=true;
        byId('entry-buy-state').textContent=submitting?'Solicitud en comprobación. No se repetirá la compra automáticamente.':reasons[error.message]||'No se pudieron verificar los datos actuales. Conservamos tu preparación; espera la actualización antes de comprar.';
        message(reasons[error.message]||'No se pudo actualizar la preparación. No se ha comprado nada.',true);
      }
      finally{refreshing=false;}
    }
    ['entry-quantity','entry-target'].forEach(id=>{byId(id).onchange=()=>{updateChoice();remember();};byId(id).oninput=()=>{updateChoice();remember();};});
    function selectContract(){
      const next=byId('entry-contract').value,changed=next!==selectedContract,previous=selectedContract;
      selectedContract=next;selectedSnapshot=[...(catalog&&catalog.contracts||[]),...observedContracts()].find(c=>c.symbol===selectedContract)||null;
      // Native pickers may emit input before change. Track both without wiping
      // explicit choices twice; only replacing an existing contract resets them.
      if(changed&&previous){byId('entry-quantity').value='';byId('entry-target').value='';}
      updateChoice();remember();
    }
    byId('entry-contract').oninput=selectContract;byId('entry-contract').onchange=selectContract;
    byId('entry-buy').onclick=async()=>{
      const c=choice();if(!c.valid||!catalog.buy_ready||!accessCurrent()||submitting)return;
      submitting=true;byId('entry-buy').disabled=true;feedback('pending');
      let dispatched=false;
      try{
        let requestId;
        try{
          const random=window.crypto;
          if(!random||typeof random.getRandomValues!=='function')throw new Error();
          requestId=typeof random.randomUUID==='function'?random.randomUUID():Array.from(random.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');
        }catch(_){const error=new Error('SECURE_REQUEST_ID_UNAVAILABLE');error.beforeDispatch=true;throw error;}
        dispatched=true;
        const data=await entryApi('entry-buy',{...reference,contract:c.contract.symbol,quantity:c.quantity,target:c.target,
          ask:c.contract.ask,total:c.total,stop:catalog.stop,request_id:requestId});
        if(adopt(data))return;
        if(data.status==='ENTRY_BLOCKED'){submitting=false;catalog.buy_ready=false;feedback('blocked',data.reason,data.contract_reasons||[]);message(reasons[data.reason]||'Compra bloqueada. Revisa los datos antes de un nuevo intento.',true);}
        else {feedback('uncertain');message('Resultado pendiente de comprobación; no se reenvía la compra.',true);}
      }catch(error){if(error.beforeDispatch||!dispatched){submitting=false;catalog.buy_ready=false;feedback('blocked',error.message);}else feedback('uncertain');message(reasons[error.message]||'Resultado sin confirmar. Solo se consultará el estado; no se repetirá la compra.',true);}
    };
    refreshEntry();setInterval(refreshEntry,3000);return;
  }
  if(watch && !intent){
    ['position-metrics','position-chart','quote-age'].forEach(id=>byId(id).hidden=true);
    byId('signal-watch').hidden=false;document.querySelector('h1').textContent='Estado de la señal';
    byId('watch-back').onclick=()=>{if(tg && tg.close)tg.close();};
    byId('watch-entry').onclick=()=>{fragment.delete('watch');fragment.set('entry',watch);location.hash=fragment.toString();location.reload();};
    if(!initData){message('Abre esta vista desde el botón de Telegram para verificar tu sesión. No se ha comprado nada.',true);return;}
    tg.ready();tg.expand();
    const reasons={NO_CURRENT_SIGNAL:'La estrategia no se cumple ahora. La compra está bloqueada.',
      TRADE_NOT_CURRENT:'El último trade IEX no está vigente; falta confirmar el estado actual, no necesariamente hubo retracción.',
      DETECTOR_STATE_INVALID:'El estado del detector no es válido.',
      COLLECTOR_NOT_CURRENT:'Los datos del colector no están vigentes. La compra está bloqueada.',
      OUTSIDE_OFFICIAL_SESSION:'La sesión regular está cerrada.',SIGNAL_CHANGED:'La vela de la señal cambió.',
      SIGNAL_DIRECTION_CHANGED:'La dirección de la señal cambió.',SIGNAL_STATE_UNAVAILABLE:'Estado de la señal no disponible.'};
    async function refreshWatch(){
      if(polling)return;polling=true;
      try{
        const response=await fetch('api/watch',{method:'POST',credentials:'omit',cache:'no-store',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({init_data:initData,symbol:watch,side:fragment.get('side'),candle:fragment.get('candle')})});
        if(!response.ok)throw new Error('WATCH_FAILED');
        const data=await response.json(),live=data.status==='CURRENT_SIGNAL';
        message(data.entry_authorized?'Aviso disponible para entrada manual · Solo visualización':live?'Señal vigente · Solo visualización':'Sin autorización de compra · Solo visualización',!live&&!data.entry_authorized);
        byId('watch-title').textContent=data.symbol+' · '+data.side+' · SIMULACIÓN';
        byId('watch-reason').textContent=data.entry_authorized?'El aviso detectado sigue siendo tu referencia de entrada manual. Puedes preparar y confirmar sin esperar otra salida.':live?'La señal cumple los controles ahora. Esta vista no prepara ni ejecuta compras.':reasons[data.reason]||'No se pudo confirmar la señal vigente.';
        const et=value=>new Date(value).toLocaleTimeString('es-US',{timeZone:'America/New_York'})+' ET';
        byId('watch-time').textContent='Comprobación '+et(data.checked_utc)+(data.source_timestamp?' · Último trade observado '+et(data.source_timestamp):'');
        byId('watch-price').textContent=live?'Precio de la acción en la señal IEX: '+prices(data.signal_price):data.entry_authorized?'Abre la preparación para ver el contrato y el Ask actuales.':'Sin precio de entrada autorizado.';
      }catch(_){message('No se pudo actualizar el estado. No se ha comprado nada.',true);byId('watch-price').textContent='—';byId('watch-reason').textContent='Datos no disponibles; no hay autorización de compra.';}
      finally{polling=false;}
    }
    refreshWatch();setInterval(refreshWatch,3000);return;
  }
  if(!initData || !intent){message('Abre esta vista con «Ejecutar compra» desde tu ficha de Telegram. Abrir un enlace normal no compra.',true);draw();return;}
  tg.ready();tg.expand();
  // Exactly one automatic execution POST per launch; refreshes only read status.
  api('execute').then(render).catch(()=>message('No se pudo confirmar el resultado. La compra no se reenvía automáticamente.',true));
  setInterval(refresh,3000);
})();
