/* Real fetch/HTTP/workflow/SQLite, isolated synthetic account and quotes only. */
'use strict';
(async()=>{
  const el=id=>document.getElementById(id),checks=[];
  const check=(ok,text)=>{if(!ok)throw Error(text);checks.push(text);};
  async function until(test,label){
    for(let i=0;i<500;i++){if(test())return;await new Promise(r=>setTimeout(r,40));}
    throw Error(label);
  }
  async function step(number){
    const response=await fetch('fixture-step',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({step:number})});
    check(response.ok,'isolated quote step '+number);
  }
  try{
    await until(()=>el('entry-contract').options.length>1,'real HTTP catalog missing');
    check(el('entry-buy').disabled,'opening never buys');
    el('entry-contract').value=el('entry-contract').options[1].value;el('entry-contract').dispatchEvent(new Event('input'));
    el('entry-quantity').value='3';el('entry-quantity').dispatchEvent(new Event('input'));
    el('entry-target').value=window.fixtureTarget;el('entry-target').dispatchEvent(new Event('change'));
    check(!el('entry-buy').disabled,'explicit selections enable buy');
    el('entry-buy').click();
    if(window.fixtureReject){
      await until(()=>!el('entry-feedback').hidden&&el('entry-feedback-title').textContent==='Compra no enviada','rejection result missing');
      check(el('entry-feedback-detail').textContent.includes('comprobación final'),'specific contract rejection shown');
      await new Promise(r=>setTimeout(r,3500));
      check(!el('entry-feedback').hidden&&el('entry-feedback-title').textContent==='Compra no enviada','polling preserves rejected outcome');
      check(!el('entry-panel').hidden&&el('selection').hidden,'rejected buy never invents a position');
      document.body.dataset.e2eResult='PASS';el('e2e-results').textContent=JSON.stringify(checks);return;
    }
    await until(()=>el('entry-panel').hidden&&!el('selection').hidden,'buy did not transition to real HTTP receipt');
    check(document.querySelector('h1').textContent==='Mi operación simulada','purchase transitions to named position view');
    check(el('fill').textContent.includes('0 / 3'),'accepted pending buy is not a fill');
    check(el('close').hidden,'pending buy cannot close an unfilled position');
    await step(1);
    await until(()=>!el('close').hidden,'filled position never offered manual close');
    check(!el('position-chart').hidden&&el('chart').width>0,'position chart visible');
    check(el('stop').textContent==='$1.80','ten percent stop shown');
    await step(2);
    await until(()=>el('pct').textContent==='5.00% bruto','live market movement missing');
    if(window.fixtureTarget==='MANUAL'){
      check(el('target').textContent==='Cierre manual','manual target retained');
      el('close').click();await until(()=>!el('review').hidden,'manual close review missing');
      check(!el('confirm').disabled,'explicit close confirmation available');
      el('confirm').click();
      await until(()=>el('pending').textContent.includes('Salida'),'manual exit not accepted');
      await step(3);
    }else{
      check(el('target').textContent==='$2.70','selected percentage target shown');
      await step(3);
      await until(()=>el('pending').textContent.includes('Salida')||!el('sale-result').hidden,'automatic target exit not accepted');
      if(el('sale-result').hidden)await step(4);
    }
    await until(()=>!el('sale-result').hidden,'confirmed sale missing');
    check(el('status').textContent.includes('Posición cerrada'),'sale confirmed closed');
    check(el('close').hidden,'closed position cannot sell twice');
    check(el('sale-gross').textContent.includes(window.fixtureTarget==='MANUAL'?'30.00':'225.00'),'profit derived from actual isolated fills');
    check(el('sale-reason').textContent.includes(window.fixtureTarget==='MANUAL'?'Cierre manual':'Objetivo de ganancia'),'exit reason shown');
    document.body.dataset.e2eResult='PASS';
    el('e2e-results').textContent=JSON.stringify(checks);
  }catch(error){document.body.dataset.e2eResult='FAIL';el('e2e-results').textContent=String(error);}
})();
