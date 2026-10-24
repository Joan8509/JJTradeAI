/* Synthetic browser harness; no Telegram SDK, vault, broker or real network. */
window.results = [];
window.calls = [];
window.intervals = [];
window.setInterval = fn => {window.intervals.push(fn); return 1;};
localStorage.clear(); // Isolated temporary browser profile only.
if(window.entryRestored)localStorage.setItem('jjtrade.manual.preparation.v1:AMZN:CALL:2026-10-16T14:00:00+00:00',JSON.stringify({saved:Date.now(),contract:'SYNTHETIC_OPTION',quantity:'3',target:'35',snapshot:{strike:100,bid:'1.95',ask:'2.00',bid_size:10,ask_size:10,quote_timestamp:'2026-10-16T14:00:03Z'}}));
const check = (value, name) => {if(!value) throw Error(name);window.results.push(name);};
const selection = {symbol:'AMZN', side:'CALL',contract:'SYNTHETIC_OPTION',quantity:3,ask:'2.00',entry_cost:'601.95',target:'35',stop:'10'};
const pending = {status:'WORKING',selection,quantity:3,filled_quantity:0,position_open:false,pending:[{key:'SYNTHETIC_KEY',instruction:'BUY_TO_OPEN',status:'WORKING',quantity:3,filled_quantity:0}]};
let stateCount=0, failed=false;
window.fetch = async (path, request) => {
  const body=JSON.parse(request.body);window.calls.push({path,body});
  check(request.method==='POST' && request.credentials==='omit','POST without ambient credentials');
  if(window.entryView && path.startsWith('api/entry-')){
    check(body.init_data==='SIGNED_SYNTHETIC' && !('intent' in body),'direct entry signed with no hidden execution intent');
    if(path==='api/entry-catalog'||path==='api/entry-refresh'){
      if(path==='api/entry-refresh')check(body.contract==='SYNTHETIC_OPTION','refresh requests only selected identity, never a purchase');
      const phase=window.entryPhase||0,waiting=window.entryBlocked||(window.entryRecovery&&phase===0);
      if(window.entryRefreshFailure&&phase===2)throw Error('SYNTHETIC_NETWORK_FAILURE');
      const absent=window.entryContractRejected||window.entryAlertExpired||((window.entryRecovery||window.entryAutoPin)&&phase===2),expired=window.entryExpired;
      const chainRows=Array.from({length:23},(_,i)=>({symbol:i===0?'SYNTHETIC_OPTION':'ROW_'+i,strike:100-i,itm:i<21,bid:'1.95',ask:'2.00',spread:'0.05',quote_timestamp:'2026-10-16T14:00:03Z',reasons:i===0?[]:['ASK_OUTSIDE_RANGE']}));
      return {ok:true,json:async()=>({status:'ENTRY_CATALOG',symbol:'AMZN',side:'CALL',
      buy_ready:(!waiting||window.entryAlert)&&!absent&&!expired,signal_ready:!waiting,
      entry_authorized:!!window.entryAlert,signal_reason:waiting?'NO_CURRENT_SIGNAL':null,
      preparation_ready:!absent,contract_reason:absent?'NO_ELIGIBLE_CONTRACTS':null,
      reason:window.entryAlertExpired?'ALERT_WINDOW_ENDED':expired?'TELEGRAM_AUTH_REQUIRED':waiting?'NO_CURRENT_SIGNAL':absent?'NO_ELIGIBLE_CONTRACTS':null,
      access_expires_utc:expired?'2000-01-01T00:00:00Z':null,premium_low:'1.40',premium_high:'2.30',
      stop:'10',expiration:'2026-10-23',fee_per_contract:'0',fees_known:false,
      contract_diagnostics:window.entryChain?{read_only:true,contracts:chainRows,counts:{observed:23,eligible:1}}:window.entryContractRejected?{read_only:true,underlying_price:'104',expiration:'2026-10-23',premium_low:'1.40',premium_high:'2.30',max_spread:'0.08',counts:{observed:2,eligible:0},itm_contracts:window.entryObservedItm?[
        {symbol:'OBSERVED_ITM',strike:'103',itm:true,bid:'2.81',ask:'2.88',bid_size:10,ask_size:10,reasons:['ASK_OUTSIDE_RANGE'],quote_timestamp:'2026-10-16T14:00:03Z'},
        {symbol:'OTHER_OBSERVED_ITM',strike:'102',itm:true,bid:'3.00',ask:'3.10',bid_size:10,ask_size:10,reasons:['ASK_OUTSIDE_RANGE','SPREAD_EXCEEDS_MAX'],quote_timestamp:'2026-10-16T14:00:03Z'}]:[],observed:[
        {strike:'103',itm:true,bid:'2.81',ask:'2.88',spread:'0.07',reasons:['ASK_OUTSIDE_RANGE'],quote_timestamp:'2026-10-16T14:00:03Z'},
        {strike:'105',itm:false,bid:'1.57',ask:'1.62',spread:'0.05',reasons:['NOT_ITM'],quote_timestamp:'2026-10-16T14:00:03Z'}]}:null,
      contracts:absent?[]:[{symbol:'SYNTHETIC_OPTION',strike:window.entryOtm5?109:100,itm:!window.entryOtm5,otm_position:window.entryOtm5?5:null,ask:'2.00',bid:'1.95',ask_size:10,bid_size:10,quote_timestamp:'2026-10-16T14:00:03Z'}].concat(window.entryInputSequence||window.entrySelectionOrder?
        [{symbol:'SECOND_SYNTHETIC_OPTION',strike:101,ask:'1.80',bid:'1.75',ask_size:10,bid_size:10,quote_timestamp:'2026-10-16T14:00:03Z'}]:[])})};
    }
    if(path==='api/entry-buy'){
      check(body.quantity===3 && body.target==='35' && body.ask==='2.00' && Number(body.total)===600 && body.stop==='10','explicit quantity target ask cost and stop sent');
      if(window.entryUncertain)throw Error('SYNTHETIC_LOST_RESPONSE');
      if(window.entryReceipt&&window.calls.filter(c=>c.path==='api/entry-buy').length===1)throw Error('SYNTHETIC_LOST_BLOCKED_RESPONSE');
      if(window.entryRetry&&window.calls.filter(c=>c.path==='api/entry-buy').length===1)
        return {ok:true,json:async()=>({status:'ENTRY_BLOCKED',reason:'NO_CURRENT_SIGNAL'})};
      return {ok:true,json:async()=>({...pending,intent:'synthetic_intent'})};
    }
    if(path==='api/entry-result')return {ok:true,json:async()=>window.entryReceipt?{status:'ENTRY_BLOCKED',reason:'NO_CURRENT_SIGNAL'}:({...pending,intent:'synthetic_intent'})};
    throw Error('UNKNOWN_ENTRY_REQUEST');
  }
  if(window.watchView){
    check(path==='api/watch' && body.init_data==='SIGNED_SYNTHETIC' && body.symbol==='AMZN' && !('intent' in body),'signed watch cannot submit an intent');
    if(failed)throw Error('SYNTHETIC_FAILURE');
    stateCount++;
    return {ok:true,json:async()=>({status:stateCount===2?'CURRENT_SIGNAL':'SIGNAL_BLOCKED',reason:stateCount===2?null:'NO_CURRENT_SIGNAL',symbol:'AMZN',side:'CALL',checked_utc:'2026-10-16T14:00:03Z',source_timestamp:'2026-10-16T14:00:02Z',signal_price:stateCount===2?104:null,view_only:true,real_orders_enabled:false})};
  }
  check(body.init_data==='SIGNED_SYNTHETIC' && body.intent==='synthetic_intent','signed data and fragment intent');
  if(failed)throw Error('SYNTHETIC_FAILURE');
  let data=pending;
  if(path==='api/state'){
    stateCount++;
    data={...pending,status:'FILLED',filled_quantity:3,position_open:true,pending:[],mark:{status:stateCount>1?'STALE':'LIVE',average_fill:'2.00',bid:'2.10',ask:'2.15',target:'2.70',stop:'1.80',gross_pnl:'30',gross_pct:'5',net_estimate:'26.10',quote_timestamp:'2026-10-16T14:00:03Z',age_seconds:stateCount>1?31:1}};
    if(stateCount>2)data={...data,position_open:false,mark:null,sale_report:{status:'CLOSED',opened_quantity:3,sold_quantity:3,remaining_quantity:0,entry_average:'2.00',exit_average:'2.70',gross_pnl:'210',gross_pct:'35',net_pnl:'206.10',fees:'3.90',reasons:['TARGET'],closed_at:'2026-10-16T14:00:06Z'}};
    if(window.unknownFees){if(data.mark)data.mark.net_estimate=null;if(data.sale_report)Object.assign(data.sale_report,{fees_known:false,fees:null,net_pnl:null});}
  }
  if(path==='api/prepare')data={id:'synthetic_review',quantity:3,minimum_price:'2.10'};
  if(path==='api/confirm')data={status:'WORKING',reason:'MANUAL_CLOSE'};
  return {ok:true,json:async()=>data};
};
window.Telegram={WebApp:{initData:window.unauth?'':'SIGNED_SYNTHETIC',ready:()=>{},expand:()=>{}}};

window.runChecks = async () => {
  try {
    await new Promise(resolve=>setTimeout(resolve,80));
    if(window.unauth){check(window.calls.length===0,'ordinary URL never executes');check(window.intervals.length===0,'no unauthenticated polling');}
    else if(window.entryView){
      check(!document.getElementById('entry-panel').hidden,'direct selection opens inside MiniApp');
      check(window.entryRestored||document.getElementById('entry-quantity').value==='' && document.getElementById('entry-target').value==='','no default quantity or target');
      check(window.calls.every(c=>c.path==='api/entry-catalog'),'opening never prepares or executes buy');
      check(window.entryRestored||document.getElementById('entry-buy').disabled,'buy requires explicit selection');
      if(window.entryOtm5){
        const contract=document.getElementById('entry-contract');
        check(contract.options[1].textContent.includes('OTM 5'),'fifth OTM labeled correctly in purchase selector');
        contract.value='SYNTHETIC_OPTION';contract.dispatchEvent(new Event('change'));
        document.getElementById('entry-quantity').value='3';document.getElementById('entry-quantity').dispatchEvent(new Event('input'));
        document.getElementById('entry-target').value='35';document.getElementById('entry-target').dispatchEvent(new Event('change'));
        check(!document.getElementById('entry-buy').disabled,'eligible fifth OTM allows explicit simulated purchase');
        document.getElementById('entry-buy').click();await new Promise(resolve=>setTimeout(resolve,80));
        check(window.calls.filter(c=>c.path==='api/entry-buy').length===1,'one simulated purchase dispatched');
        check(document.getElementById('entry-panel').hidden,'receipt opens operation view');
      }else if(window.entryChain){
        const rows=document.getElementById('entry-chain-rows'),all=document.getElementById('entry-chain-all');
        check(rows.children.length===20,'chain paginates twenty visible ITM quotes');
        document.getElementById('entry-chain-next').click();check(rows.children.length===1,'next page exposes remaining ITM quote');
        all.checked=true;all.dispatchEvent(new Event('change'));check(document.getElementById('entry-chain-page').textContent.includes('23 contratos'),'all quoted contracts including OTM visible for comparison');
        document.getElementById('entry-quantity').value='3';document.getElementById('entry-quantity').dispatchEvent(new Event('input'));
        document.getElementById('entry-target').value='35';document.getElementById('entry-target').dispatchEvent(new Event('change'));
        document.getElementById('entry-refresh').click();await new Promise(resolve=>setTimeout(resolve,80));
        check(window.calls.some(c=>c.path==='api/entry-refresh'),'selected quote refreshed explicitly');
        check(document.getElementById('entry-contract').value==='SYNTHETIC_OPTION'&&document.getElementById('entry-quantity').value==='3'&&document.getElementById('entry-target').value==='35','refresh retains contract quantity and target');
        check(!document.getElementById('entry-buy').disabled,'current eligible quote allows explicit purchase');
        check(!window.calls.some(c=>c.path==='api/entry-buy'),'viewing and refresh never buys');
      }else if(window.entryAutoPin||window.entryRestored||window.entryRefreshFailure){
        const contract=document.getElementById('entry-contract'),quantity=document.getElementById('entry-quantity'),target=document.getElementById('entry-target');
        check(contract.value==='SYNTHETIC_OPTION','nearest eligible contract selected automatically or restored');
        if(window.entryRestored)check(quantity.value==='3'&&target.value==='35','explicit preparation restored without execution');
        quantity.value='3';quantity.dispatchEvent(new Event('input'));target.value='35';target.dispatchEvent(new Event('change'));
        check(!document.getElementById('entry-buy').disabled,'fresh eligible contract plus explicit choices enables purchase');
        window.entryAutoPin=true;window.entryPhase=2;await window.intervals[0]();
        check(contract.value==='SYNTHETIC_OPTION'&&quantity.value==='3'&&target.value==='35','missing contract does not erase preparation');
        check(document.getElementById('entry-buy').disabled,'retained old quote cannot buy');
        check(document.getElementById('entry-quote').textContent.includes('No utilizable para comprar'),'historical quote clearly marked');
        const saved=JSON.parse(localStorage.getItem('jjtrade.manual.preparation.v1:AMZN:CALL:2026-10-16T14:00:00+00:00'));
        check(saved.contract==='SYNTHETIC_OPTION'&&saved.quantity==='3'&&saved.target==='35','preparation persisted without credentials');
        window.entryPhase=3;await window.intervals[0]();
        check(!document.getElementById('entry-buy').disabled&&contract.value==='SYNTHETIC_OPTION','current eligible quote restores purchase without erasing choices');
        check(window.calls.every(c=>c.path==='api/entry-catalog'),'restoration and autoselection never execute');
      }else if(window.entryCryptoFailure){
        const contract=document.getElementById('entry-contract');contract.value='SYNTHETIC_OPTION';contract.dispatchEvent(new Event('input'));
        document.getElementById('entry-quantity').value='3';document.getElementById('entry-quantity').dispatchEvent(new Event('input'));
        document.getElementById('entry-target').value='35';document.getElementById('entry-target').dispatchEvent(new Event('change'));
        Object.defineProperty(window,'crypto',{configurable:true,value:{getRandomValues(){throw Error('SYNTHETIC_RANDOM_FAILURE');}}});
        document.getElementById('entry-buy').click();await new Promise(resolve=>setTimeout(resolve,80));
        check(document.getElementById('entry-feedback-title').textContent==='Compra no enviada','pre-request failure shown visibly');
        check(document.getElementById('entry-feedback-detail').textContent.includes('solicitud segura'),'safe request preparation error explained');
        check(window.calls.every(c=>c.path==='api/entry-catalog'),'random failure never sends purchase or receipt request');
      }else if(window.entryInputSequence||window.entrySelectionOrder){
        const contract=document.getElementById('entry-contract');
        const quantity=document.getElementById('entry-quantity'),target=document.getElementById('entry-target');
        if(window.entrySelectionOrder){
          quantity.value='3';quantity.dispatchEvent(new Event('input'));
          target.value='35';target.dispatchEvent(new Event('change'));
          contract.value='SYNTHETIC_OPTION';contract.dispatchEvent(new Event('change'));
          check(quantity.value==='3'&&target.value==='35','initial contract selection preserves explicitly chosen quantity and target');
        }else{
          contract.value='SYNTHETIC_OPTION';contract.dispatchEvent(new Event('input'));
          quantity.value='3';quantity.dispatchEvent(new Event('input'));
          target.value='35';target.dispatchEvent(new Event('change'));
          check(!document.getElementById('entry-buy').disabled,'native input event updates selected contract without waiting for change');
          await window.intervals[0]();
          check(contract.value==='SYNTHETIC_OPTION','polling preserves native input selection');
          contract.dispatchEvent(new Event('change'));
          check(quantity.value==='3'&&target.value==='35','duplicate native change does not erase explicit selections');
        }
        check(!document.getElementById('entry-buy').disabled,'all explicit selections enable purchase with eligible current catalog');
        check(document.getElementById('entry-buy-state').textContent.includes('Listo'),'readiness explanation appears beside purchase button');
        contract.value='SECOND_SYNTHETIC_OPTION';contract.dispatchEvent(new Event('input'));contract.dispatchEvent(new Event('change'));
        check(quantity.value===''&&target.value===''&&document.getElementById('entry-buy').disabled,'replacing an existing contract still requires explicit quantity and target');
        check(document.getElementById('entry-buy-state').textContent.includes('cantidad entera'),'missing quantity explained next to button');
        quantity.value='1.5';quantity.dispatchEvent(new Event('input'));
        check(document.getElementById('entry-buy').disabled,'fractional quantity never enables purchase');
        quantity.value='3';quantity.dispatchEvent(new Event('input'));
        check(document.getElementById('entry-buy-state').textContent.includes('objetivo de ganancia'),'missing target explained next to button');
        target.value='MANUAL';target.dispatchEvent(new Event('change'));
        check(!document.getElementById('entry-buy').disabled,'manual target with explicit integer quantity enables valid purchase');
        check(window.calls.every(c=>c.path==='api/entry-catalog'),'selection and polling never execute an order');
      }else if(window.entryAlertExpired){
        document.getElementById('entry-quantity').value='3';document.getElementById('entry-quantity').dispatchEvent(new Event('input'));
        document.getElementById('entry-target').value='35';document.getElementById('entry-target').dispatchEvent(new Event('change'));
        check(document.getElementById('entry-buy-state').textContent.includes('TerminÃ³ la sesiÃ³n'),'expired session reason visible beside purchase button');
        check(document.getElementById('entry-buy').disabled,'choosing quantity and target cannot authorize an expired alert');
        check(window.calls.every(c=>c.path==='api/entry-catalog'),'expired alert selections never buy');
      }else if(window.entryObservedItm){
        const contract=document.getElementById('entry-contract');
        check(contract.options.length===3&&contract.value==='OBSERVED_ITM','actual ITM identities visible and nearest observed preselected for review');
        document.getElementById('entry-quantity').value='3';document.getElementById('entry-quantity').dispatchEvent(new Event('input'));
        document.getElementById('entry-target').value='35';document.getElementById('entry-target').dispatchEvent(new Event('change'));
        check(document.getElementById('entry-quote').textContent.includes('Ask fuera de tu rango')&&!document.getElementById('entry-quote').textContent.includes('Spread superior'),'selected ITM shows exact unmet conditions');
        check(document.getElementById('entry-buy').disabled,'observed ITM never authorizes invalid buy');
        contract.value='OTHER_OBSERVED_ITM';contract.dispatchEvent(new Event('input'));
        check(document.getElementById('entry-quote').textContent.includes('Strike 102'),'can select another observed ITM to inspect');
        await window.intervals[0]();
        check(contract.value==='OTHER_OBSERVED_ITM','refresh preserves observed selection');
        document.getElementById('entry-buy').click();
        check(window.calls.every(c=>c.path==='api/entry-catalog'),'inspection never dispatches or manufactures eligible contracts');
      }else if(window.entryContractRejected){
        check(document.getElementById('status').textContent.includes('PreparaciÃ³n abierta Â· Sin contrato apto'),'opening distinguished from contract rejection');
        check(!document.getElementById('entry-diagnostics').hidden,'observed quote diagnostics visible');
        const observed=document.getElementById('entry-observed-contracts').textContent;
        check(observed.includes('2.88')&&observed.includes('0.07')&&observed.includes('Ask fuera de tu rango'),'actual bid ask spread and rejection shown');
        check(observed.includes('No es ITM')&&observed.includes('1.62'),'cheap OTM clearly distinguished');
        check(document.getElementById('entry-contract').options.length===1,'observed rejected contracts never enter purchase selector');
        await window.intervals[0]();
        check(document.getElementById('entry-buy').disabled&&window.calls.every(c=>c.path==='api/entry-catalog'),'refresh never buys or creates a review');
      }else if(window.entryAlert){
        check(document.getElementById('entry-signal').textContent.includes('retroceso o cambio de vela no cancela'),'delivered alert does not wait for another breakout');
        const contract=document.getElementById('entry-contract');contract.value='SYNTHETIC_OPTION';contract.dispatchEvent(new Event('change'));
        document.getElementById('entry-quantity').value='3';document.getElementById('entry-quantity').dispatchEvent(new Event('input'));
        document.getElementById('entry-target').value='35';document.getElementById('entry-target').dispatchEvent(new Event('change'));
        check(!document.getElementById('entry-buy').disabled,'can confirm explicit purchase while detector no longer has EXIT');
        check(window.calls.every(c=>c.path==='api/entry-catalog'),'opening an authorized alert never auto buys');
        document.getElementById('entry-buy').click();await new Promise(resolve=>setTimeout(resolve,80));
        check(document.getElementById('entry-panel').hidden,'explicit alert purchase enters position view');
        check(window.calls.filter(c=>c.path==='api/entry-buy').length===1,'one explicit alert purchase');
      }else if(window.entryExpired){
        check(document.getElementById('entry-reason').textContent.includes('caducÃ³'),'expired authentication distinct from signal retraction');
        check(!document.getElementById('entry-reopen').hidden,'clear renewal control shown without loosening authentication');
        check(window.calls.every(c=>c.path==='api/entry-catalog'),'expired session never buys');
      }else if(window.entryBlocked){
        check(document.getElementById('entry-reason').textContent.includes('no se cumple'),'real retraction remains blocked');
        await window.intervals[0]();
        check(window.calls.every(c=>c.path==='api/entry-catalog'),'blocked polling never buys');
      }else{
        const contract=document.getElementById('entry-contract');contract.value='SYNTHETIC_OPTION';contract.dispatchEvent(new Event('change'));
        const quantity=document.getElementById('entry-quantity');quantity.value='3';quantity.dispatchEvent(new Event('input'));
        const target=document.getElementById('entry-target');target.value='35';target.dispatchEvent(new Event('change'));
        if(window.entryRecovery){
          check(document.getElementById('entry-buy').disabled,'can prepare during initial retraction but cannot buy');
          const existingOption=contract.options[1];window.entryPhase=1;await window.intervals[0]();
          check(contract.options[1]===existingOption,'stable contract list does not rebuild the dropdown each poll');
          check(!document.getElementById('entry-buy').disabled,'same candle recovery reenables explicit entry');
          window.entryPhase=2;await window.intervals[0]();
          check(document.getElementById('entry-buy').disabled&&contract.value==='SYNTHETIC_OPTION','unavailable selected contract retained but not buyable');
          check(quantity.value==='3'&&target.value==='35','temporary absence keeps quantity and target');
          window.entryPhase=3;await window.intervals[0]();
          check(contract.value==='SYNTHETIC_OPTION'&&quantity.value==='3'&&target.value==='35','contract recovery restores explicit choices');
          check(window.calls.every(c=>c.path==='api/entry-catalog'),'recovery and refresh never auto buy');
        }
        check(!document.getElementById('entry-buy').disabled,'explicit choices enable simulated purchase');
        check(document.getElementById('entry-cost').textContent.includes('600.00'),'premium cost displayed before click');
        document.getElementById('entry-buy').click();await new Promise(resolve=>setTimeout(resolve,80));
        if(window.entryRetry||window.entryReceipt){
          if(window.entryReceipt){
            check(document.getElementById('entry-buy').disabled,'lost response initially locks further submission');
            await window.intervals[0]();
            check(window.calls.some(c=>c.path==='api/entry-result'),'lost response resolved only through receipt');
          }
          check(!document.getElementById('entry-panel').hidden,'proven pre-dispatch rejection stays in preparation');
          check(document.getElementById('entry-feedback-title').textContent==='Compra no enviada','definite rejection visible beside button');
          await window.intervals[0]();
          check(document.getElementById('entry-feedback-title').textContent==='Compra no enviada','catalog polling cannot erase purchase rejection');
          check(window.calls.filter(c=>c.path==='api/entry-buy').length===1,'recovery never automatically retries even a safe rejection');
          check(!document.getElementById('entry-buy').disabled,'recovered definite rejection permits a new explicit click');
          document.getElementById('entry-buy').click();await new Promise(resolve=>setTimeout(resolve,80));
        }
        if(window.entryUncertain){
          check(document.getElementById('entry-buy').disabled,'uncertain request cannot submit again');
          await window.intervals[0]();
          check(window.calls.some(c=>c.path==='api/entry-result'),'uncertain entry reads receipt only');
        }
        check(document.getElementById('entry-panel').hidden && !document.getElementById('position-metrics').hidden,'buy transitions to existing position monitor');
        await window.intervals[0]();
        check(document.getElementById('pct').textContent==='5.00% bruto','direct entry shares actual position monitoring view');
        check(window.calls.filter(c=>c.path==='api/entry-buy').length===((window.entryRetry||window.entryReceipt)?2:1) && window.calls.filter(c=>c.path==='api/execute').length===0,'one request per explicit entry click and no automatic execution endpoint');
      }
    } else if(window.watchView){
      check(!document.getElementById('signal-watch').hidden,'blocked signal can open MiniApp');
      check(document.getElementById('status').textContent.includes('Solo visualizaciÃ³n'),'watch explicitly read only');
      check(document.getElementById('actions').hidden && document.getElementById('selection').hidden,'watch exposes no buy or sell controls');
      check(document.getElementById('position-metrics').hidden && document.getElementById('position-chart').hidden,'no invented position or chart');
      await window.intervals[0]();
      check(document.getElementById('watch-price').textContent.includes('104.00'),'current detector price displayed without buying');
      check(window.calls.every(c=>c.path==='api/watch'),'watch never executes or prepares an order');
      failed=true;await window.intervals[0]();
      check(document.getElementById('watch-price').textContent==='â€”','failed watch clears live price');
    } else {
      check(window.calls.filter(c=>c.path==='api/execute').length===1,'exactly one initial execution');
      check(document.getElementById('status').textContent.includes('pendiente'),'pending is not filled');
      check(document.getElementById('close').hidden,'no close before a position');
      check(document.getElementById('pending').children.length===2,'cancel remaining quantity control');
      await window.intervals[0]();
      check(document.getElementById('pct').textContent==='5.00% bruto','current bid PnL');
      check(document.getElementById('stop').textContent==='$1.80' && document.getElementById('summary').textContent.includes('Stop 10%'),'approved stop10 shown in summary and chart level');
      if(window.unknownFees)check(document.getElementById('net').textContent==='â€”','unknown costs never become zero fees or net');
      check(!document.getElementById('close').hidden,'manual close control visible');
      document.getElementById('close').click();await new Promise(resolve=>setTimeout(resolve,50));
      check(!document.getElementById('review').hidden,'close requires explicit review');
      check(window.calls.filter(c=>c.path==='api/confirm').length===0,'preparing close never confirms');
      document.getElementById('confirm').click();await new Promise(resolve=>setTimeout(resolve,50));
      check(window.calls.filter(c=>c.path==='api/confirm').length===1,'single explicit close confirmation');
      check(document.getElementById('pnl').textContent==='â€”','stale quote hides current PnL');
      check(document.getElementById('quote-age').textContent.includes('STALE'),'stale quote label');
      await window.intervals[0]();
      check(!document.getElementById('sale-result').hidden,'confirmed sale summary visible');
      check(document.getElementById('sale-net').textContent.includes(window.unknownFees?'Neto no disponible':'206.10'),'realized result from fills with explicit fee availability');
      check(document.getElementById('status').textContent.includes('PosiciÃ³n cerrada'),'closed is distinct from buy fill');
      check(document.getElementById('close').hidden,'closed position cannot sell twice');
      failed=true;await window.intervals[0]();
      check(document.getElementById('pnl').textContent==='â€”' && document.getElementById('close').hidden,'failed refresh hides actionable mark');
      check(window.calls.filter(c=>c.path==='api/execute').length===1,'refreshes and failures never repeat buy');
    }
    document.body.dataset.testResult='PASS';
    document.getElementById('test-results').textContent=JSON.stringify(window.results);
  }catch(error){document.body.dataset.testResult='FAIL';document.getElementById('test-results').textContent=String(error);}
};
