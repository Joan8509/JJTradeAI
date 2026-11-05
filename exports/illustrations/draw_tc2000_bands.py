"""Synthetic TC2000-style charts, with actual rolling BB20/2, ddof0."""
from pathlib import Path
import sys,json
import numpy as np
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from bollinger_expansion import measure_band_expansion

OUT=Path(__file__).resolve().parent
history=95+np.sqrt(12.5)*np.sin(np.arange(80)*2*np.pi/20-np.pi/2)
def bands(values):
    window=np.asarray(values)[-20:]
    return float(window.mean()+2*window.std()),float(window.mean()-2*window.std()),float(window.mean())
previous_upper,previous_lower,previous_mid=bands(history)
evidence=[]
for threshold in (3,5):
    low,high=100.,115.
    for _ in range(80):
        price=(low+high)/2;upper,lower,mid=bands(np.r_[history,price])
        measured=measure_band_expansion(upper,lower,previous_upper,previous_lower)
        if measured.minimum_pct<threshold+1e-7:low=price
        else:high=price
    price=high;upper,lower,mid=bands(np.r_[history,price])
    measured=measure_band_expansion(upper,lower,previous_upper,previous_lower)
    opening=float(history[-1])
    assert previous_lower<opening<previous_upper and lower<opening<upper
    assert price>upper and mid>previous_mid and measured.meets(threshold)
    assert measured.meets(5)==(threshold==5)
    im=Image.new('RGB',(1080,900),'black');d=ImageDraw.Draw(im)
    def font(size,bold=False):return ImageFont.truetype('C:/Windows/Fonts/'+('arialbd.ttf' if bold else 'arial.ttf'),size)
    def text(x,y,s,size=23,color='#dddddd',bold=False):d.text((x,y),s,font=font(size,bold),fill=color)
    d.rectangle((0,0,1079,45),fill='#171717',outline='#555555')
    text(20,9,'+  DEMO     1m   [15m]   1h   D   W',23,'#a7ff00',True)
    text(20,57,'DEMO 15 minutos · Bollinger Bands 20, 2 · ddof=0',23,'#00d7d7')
    text(20,92,f'UMBRAL {threshold}% EN CADA BANDA',30,'#f1d747' if threshold==3 else '#00ff66',True)
    text(20,132,'Datos simulados · Misma escala en ambos gráficos',21,'#aaaaaa')
    left,right,top,bottom=60,900,190,680
    ymin,ymax=88.,107.
    def y(v):return bottom-(v-ymin)/(ymax-ymin)*(bottom-top)
    xs=np.linspace(left,right,17)
    closes=list(history[-16:])+[price]
    series=[bands(history[:len(history)-15+i]) for i in range(16)]+[(upper,lower,mid)]
    for v in np.arange(88,108,2):
        d.line((left,y(v),right+20,y(v)),fill='#242424',width=1)
        text(right+34,int(y(v))-12,f'{v:.2f}',22,'#00ff00')
    for x in xs[::4]:d.line((x,top,x,bottom),fill='#242424',width=1)
    polygon=[(x,y(b[0])) for x,b in zip(xs,series)]+[(x,y(b[1])) for x,b in reversed(list(zip(xs,series)))]
    d.polygon(polygon,fill='#353535')
    text(275,362,'DEMO',100,'#4d4d4d',True)
    text(200,472,'Ejemplo didáctico de Bollinger',33,'#555555')
    for k in (0,1,2):d.line([(x,y(b[k])) for x,b in zip(xs,series)],fill='#32acb1',width=2)
    for i,(x,close) in enumerate(zip(xs,closes)):
        op=opening if i==16 else float(history[-17+i])
        col='#00ff00' if close>=op else '#ff3535'
        high_wick=max(op,close)+(0.35 if i<16 else .22)
        low_wick=min(op,close)-.30
        d.line((x,y(high_wick),x,y(low_wick)),fill=col,width=2)
        a,b=sorted((y(op),y(close)))
        d.rectangle((x-13,a,x+13,max(a+2,b)),fill=col)
    # Mark the previous/current observation without implying candle-close waiting.
    d.line((xs[-2],top,xs[-2],bottom),fill='#555555',width=1)
    text(xs[-2]-76,bottom+17,'Anterior',20,'#aaaaaa')
    text(xs[-1]-30,bottom+17,'Ahora',20,'#ffffff')
    text(left,top+8,'Ancho anterior: $10.00',23,'#ffffff',True)
    text(530,210,f'Superior: +{measured.upper_pct:.2f}%',25,'#00eeee',True)
    d.line((800,247,right,y(upper)),fill='#00eeee',width=2)
    text(510,596,f'Inferior: {measured.lower_pct:.2f}% hacia abajo',24,'#00eeee',True)
    d.line((800,626,right,y(lower)),fill='#00eeee',width=2)
    d.rectangle((right+25,int(y(price))-13,right+117,int(y(price))+23),fill='#070707',outline='#666666')
    text(right+30,int(y(price))-10,f'{price:.2f}',23,'#ffffff',True)
    d.rectangle((20,735,1060,875),outline='#555555',fill='#101010',width=2)
    text(40,750,f'Banda contraria al CALL: baja ${previous_lower-lower:.2f} / $10 = {threshold}%',26,'#eeeeee',True)
    text(40,794,'La vela abre dentro; el precio sale por arriba.',24,'#dddddd')
    text(40,835,'NO cumple el 5% activo de la app.' if threshold==3 else 'CUMPLE el filtro del 5% en ambas bandas.',25,
        '#ffbf69' if threshold==3 else '#00ff66',True)
    path=OUT/f'bollinger_tc2000_{threshold}.png';im.save(path)
    evidence.append(dict(threshold=threshold,upper_pct=measured.upper_pct,lower_pct=measured.lower_pct,
        previous_upper=previous_upper,previous_lower=previous_lower,upper=upper,lower=lower,
        opening=opening,price=price,synthetic=True,path=path.name))
(OUT/'bollinger_tc2000_evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
print(json.dumps(evidence))
