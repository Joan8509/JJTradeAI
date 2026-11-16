"""Describe existing closed-bar SMA context. No I/O or trading authority."""
import math

REVISION='ma_direction_and_route_v1'
PERIODS=(20,40,100,200)
TIMES={'1H':'Hora','1D':'Diario'}
ROLES={'POSIBLE_PISO':'Posible piso','POSIBLE_TECHO':'Posible techo',
    'POSIBLE_CONTINUIDAD_ALCISTA':'Posible continuidad alcista',
    'POSIBLE_CONTINUIDAD_BAJISTA':'Posible continuidad bajista',
    'APOYO_POR_DETRAS':'Apoyo por detrás','MEDIA_POR_DETRAS':'Media por detrás',
    'TENDENCIA_NO_VALIDADA':'Tendencia sin validar','EN_NIVEL':'En el nivel'}


def number(value):
    if isinstance(value,bool):return None
    try:result=float(value)
    except (TypeError,ValueError):return None
    return result if math.isfinite(result) else None


def outlook(context,side):
    """Summarize only values already calculated for this original signal price.

    Agreement is descriptive, never a probability, new entry gate, stop or TP.
    A forward MA can suggest continuity; it is not automatically resistance.
    """
    empty=dict(revision=REVISION,state='SIN_DATOS',frames=[],route=[],behind=[],at_price=[],
        reading='SIN_DATOS',aligned_with_signal=None,nearest_limit=None,complete=False)
    if not isinstance(context,dict) or context.get('state')!='DESCRIPTIVO' or side not in ('SUPERIOR','INFERIOR'):
        return empty
    price=number(context.get('price'))
    if price is None or price<=0 or context.get('ma_type') not in (None,'SMA'):return empty
    frames=[]
    for timeframe in TIMES:
        frame=next((f for f in context.get('frames',[]) if f.get('timeframe')==timeframe),None)
        if frame is None:continue
        values={str(p):number(frame.get('averages',{}).get(str(p))) for p in PERIODS}
        slopes={str(p):number(frame.get('slopes',{}).get(str(p))) for p in PERIODS}
        a,b=values['20'],values['40'];x,y=slopes['20'],slopes['40']
        order='SIN_DATOS' if a is None or b is None else 'ALCISTA' if a>b else 'BAJISTA' if a<b else 'IGUALES'
        slope='SIN_DATOS' if x is None or y is None else 'SUBIENDO' if x>0 and y>0 else 'BAJANDO' if x<0 and y<0 else 'NO_COINCIDEN_O_PLANAS'
        bias=('ALCISTA' if order=='ALCISTA' and slope=='SUBIENDO' else
              'BAJISTA' if order=='BAJISTA' and slope=='BAJANDO' else 'SIN_DIRECCION_CONJUNTA')
        if order=='SIN_DATOS' or slope=='SIN_DATOS':bias='SIN_DATOS'
        pair=next((p for p in frame.get('pairs',[]) if p.get('periods')==[20,40]),{})
        c,d=values['100'],values['200']
        background='SIN_DATOS' if c is None or d is None else 'ALCISTA' if c>d else 'BAJISTA' if c<d else 'IGUALES'
        long_pair=next((p for p in frame.get('pairs',[]) if p.get('periods')==[100,200]),{})
        frames.append(dict(timeframe=timeframe,averages=values,slopes=slopes,order=order,slope=slope,bias=bias,
            background_order=background,background_cross_validated=long_pair.get('validated') is True,
            cross_validated=pair.get('validated') is True,sessions_since_cross=pair.get('sessions_since_cross'),
            phase=pair.get('phase'),last_closed_at=frame.get('last_closed_at')))
    biases=[f['bias'] for f in frames]
    valid=[v for v in biases if v in ('ALCISTA','BAJISTA')]
    if len(valid)==2:reading=valid[0] if valid[0]==valid[1] else 'HORA_DIARIO_EN_CONFLICTO'
    elif len(valid)==1:reading='PARCIAL_'+valid[0]
    else:reading='SIN_DIRECCION_CONJUNTA' if frames else 'SIN_DATOS'
    route=[];behind=[];at_price=[];seen=set()
    for level in context.get('levels',[]):
        timeframe=level.get('timeframe');period=level.get('period');value=number(level.get('value'))
        identity=(timeframe,period)
        if timeframe not in TIMES or period not in PERIODS or value is None or value<=0 or identity in seen:continue
        seen.add(identity)
        # Recalculate distances from the original context price, not a new quote.
        distance=abs(value-price)
        row=dict(label=f'SMA{period} {TIMES[timeframe]}',timeframe=timeframe,period=period,value=value,
            distance_usd=distance,distance_pct=100*distance/price,
            role=level.get('role') if level.get('role') in ROLES else 'TENDENCIA_NO_VALIDADA',
            hour_confirmation=level.get('hour_confirmation'),confirmation_hour_at=level.get('confirmation_hour_at'),
            touch_episodes_last_20_hours=level.get('touch_episodes_last_20_hours'))
        ahead=value>price if side=='SUPERIOR' else value<price
        (at_price if value==price else route if ahead else behind).append(row)
    for rows in (route,behind,at_price):rows.sort(key=lambda v:(v['distance_usd'],v['timeframe'],v['period']))
    limits=[r for r in route if r['role'] in ('POSIBLE_PISO','POSIBLE_TECHO')]
    aligned=(reading==('ALCISTA' if side=='SUPERIOR' else 'BAJISTA')) if reading in ('ALCISTA','BAJISTA') else None
    complete=len(frames)==2 and all(f['averages'][str(p)] is not None for f in frames for p in PERIODS)
    return dict(revision=REVISION,state='DESCRIPTIVO' if frames or seen else 'SIN_DATOS',side=side,
        price=price,available_at=context.get('available_at'),frames=frames,reading=reading,
        aligned_with_signal=aligned,route=route,behind=behind,at_price=at_price,
        nearest_limit=limits[0] if limits else None,complete=complete,
        crosses_validated=len(frames)==2 and all(f['cross_validated'] for f in frames))


def summary(value):
    if value.get('state')!='DESCRIPTIVO':return 'Medias: historial insuficiente para esta lectura.'
    labels={'ALCISTA':'Hora y Diario acompañan hacia arriba',
        'BAJISTA':'Hora y Diario acompañan hacia abajo',
        'HORA_DIARIO_EN_CONFLICTO':'Hora y Diario apuntan en direcciones distintas',
        'PARCIAL_ALCISTA':'Lectura alcista en una temporalidad; la otra no la confirma',
        'PARCIAL_BAJISTA':'Lectura bajista en una temporalidad; la otra no la confirma',
        'SIN_DIRECCION_CONJUNTA':'Orden y pendientes sin una dirección conjunta',
        'SIN_DATOS':'Historial insuficiente para comparar Hora y Diario'}
    lines=[labels[value['reading']]+'.']
    if not value.get('crosses_validated'):lines.append('Cruces pendientes de validación en alguna temporalidad.')
    for frame in value['frames']:
        if frame['background_order'] in ('ALCISTA','BAJISTA'):
            lines.append(f"{TIMES[frame['timeframe']]}: orden 100/200 {frame['background_order'].lower()}"+
                ('.' if frame['background_cross_validated'] else ', cruce sin validar.'))
    if value['route']:
        first=value['route'][0]
        lines.append(f"Siguiente media en el recorrido: {first['label']} en ${first['value']:.2f}, a ${first['distance_usd']:.2f} ({first['distance_pct']:.3f}%).")
    else:lines.append('No se identifica una media por delante entre las disponibles.')
    limit=value.get('nearest_limit')
    if limit:lines.append(f"Zona a vigilar: {ROLES[limit['role']].lower()} en {limit['label']} (${limit['value']:.2f}).")
    if not value.get('complete'):lines.append('Faltan datos para algunas SMA 20/40/100/200 de Hora o Diario.')
    return '\n'.join(lines)
