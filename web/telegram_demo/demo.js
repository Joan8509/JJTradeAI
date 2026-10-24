/* Pure visual demo: no fetch, initData, account, order API or persistent storage. */
(() => {
  const tg=window.Telegram && window.Telegram.WebApp;
  if(tg){tg.ready();tg.expand();}
  const el=id=>document.getElementById(id), bidSeries=[2.00,2.02,2.07,2.10,2.08,2.13,2.17,2.12,2.06,2.10,2.16,2.20,2.17,2.23,2.18,2.14,2.19,2.25,2.21,2.16];
  let index=3;
  const price=v=>'$'+v.toFixed(2);
  function draw(){
    const qty=Number(el('quantity').value),profit=el('profit').value,bid=bidSeries[index];
    const target=profit==='MANUAL'?null:2*(1+Number(profit)/100);
    el('cost').textContent='Prima ficticia al Ask: '+price(qty*200)+' USD · Sin incluir costos pendientes.';
    el('summary').textContent=qty+' contratos de ejemplo · Ganancia '+(profit==='MANUAL'?'manual':profit+'%')+' · Stop 10%';
    el('bid').textContent=price(bid);el('pnl').textContent=price((bid-2)*qty*100);el('pct').textContent=((bid-2)/2*100).toFixed(2)+'% bruto ficticio';
    el('target').textContent=target===null?'Manual':price(target);
    const c=el('chart'),dpr=window.devicePixelRatio||1,w=c.clientWidth||320,h=230;
    c.width=w*dpr;c.height=h*dpr;const ctx=c.getContext('2d');ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);
    const high=Math.max(2.4,target||0),lo=1.5,y=v=>195-(v-lo)/(high-lo)*160;
    [[2,'Prima','#a2b3cc'],[1.8,'Stop 10%','#fb7185'],...(target===null?[]:[[target,'Objetivo','#4ade80']])].forEach(([value,label,color])=>{
      ctx.setLineDash([5,4]);ctx.strokeStyle=color;ctx.beginPath();ctx.moveTo(16,y(value));ctx.lineTo(w-12,y(value));ctx.stroke();ctx.fillStyle=color;ctx.fillText(label+' '+price(value),18,y(value)-5);
    });
    ctx.setLineDash([]);ctx.strokeStyle='#38bdf8';ctx.beginPath();bidSeries.slice(0,index+1).forEach((v,i)=>{const x=18+i/(bidSeries.length-1)*(w-36);if(i)ctx.lineTo(x,y(v));else ctx.moveTo(x,y(v));});ctx.stroke();
  }
  function show(setup){el('setup').hidden=!setup;el('monitor').hidden=setup;if(!setup)requestAnimationFrame(draw);}
  el('tab-setup').onclick=()=>show(true);el('tab-monitor').onclick=el('preview').onclick=()=>show(false);
  el('quantity').onchange=el('profit').onchange=draw;el('restart').onclick=()=>{index=0;draw();};
  window.addEventListener('resize',draw);setInterval(()=>{index=(index+1)%bidSeries.length;draw();},1500);draw();
})();
