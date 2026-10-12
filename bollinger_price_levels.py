"""Prior session reference levels; limited history is never a verified ATH."""
import math
import pandas as pd


def price_levels(daily, *, price, side, available_at):
    available=pd.Timestamp(available_at)
    current_date=available.tz_convert('America/New_York').date()
    dates=pd.to_datetime(daily['date'],utc=True)
    closed=daily[dates.dt.tz_convert('America/New_York').dt.date<current_date].sort_values('date')
    levels=[]
    if closed.empty:
        return {'levels':[], 'nearest_ahead':None,'ath_confirmed':False,'state':'SIN_DATOS'}
    last=closed.iloc[-1]
    last_date=pd.Timestamp(last['date']).tz_convert('America/New_York').date().isoformat()
    expected=daily.attrs.get('expected_previous_session')
    last_stamps=daily.attrs.get('last_minute_by_session',{})
    closes=daily.attrs.get('session_closes',{})
    expected_close=closes.get(last_date)
    final_minute=last_stamps.get(last_date)
    final_observed=expected_close is not None and final_minute is not None and pd.Timestamp(final_minute)+pd.Timedelta(minutes=1)==pd.Timestamp(expected_close)

    def add(kind,label,value,origin_date,quality):
        if not math.isfinite(float(value)) or value<=0:
            return
        ahead=value>=price if side=='SUPERIOR' else value<=price
        role='EN_NIVEL' if value==price else ('POSIBLE_RESISTENCIA' if side=='SUPERIOR' else 'POSIBLE_SOPORTE') if ahead else 'NIVEL_POR_DETRAS'
        levels.append({'kind':kind,'label':label,'value':float(value),'distance_pct':abs(value-price)/price*100,
                       'ahead':ahead,'role':role,'source_date':origin_date,'quality':quality})

    if expected is not None and expected!=last_date:
        add('LAST_AVAILABLE_CLOSE','Último cierre disponible (falta sesión anterior)',float(last.close),last_date,'FALTA_SESION_ANTERIOR')
    else:
        add('PREVIOUS_SESSION_CLOSE','Cierre de sesión anterior (Alpaca/IEX)',float(last.close),last_date,
            'ULTIMO_MINUTO_OBSERVADO' if final_observed else 'CIERRE_DISPONIBLE_NO_VERIFICADO')
    if 'high' in closed:
        highs=pd.to_numeric(closed.high,errors='coerce')
        highs=highs[highs.map(lambda v:pd.notna(v) and math.isfinite(v) and v>0)]
        if len(highs):
            index=highs.idxmax()
            source_date=pd.Timestamp(closed.loc[index,'date']).tz_convert('America/New_York').date().isoformat()
            add('AVAILABLE_HISTORY_HIGH','Máximo del historial disponible (ATH sin confirmar)',float(highs.loc[index]),source_date,'HISTORIAL_LIMITADO')
    ahead=[l for l in levels if l['ahead']]
    return {'levels':levels,'nearest_ahead':min(ahead,key=lambda l:l['distance_pct']) if ahead else None,
            'ath_confirmed':False,'state':'DESCRIPTIVO','history_from':str(closed.iloc[0]['date']),
            'history_to':str(last['date']),'expected_previous_session':expected,
            'caveat':'Referencia anterior a la sesión actual. No es cierre oficial consolidado ni ATH verificado; las barras pueden tener huecos o ajustes corporativos distintos.'}


def price_levels_text(context):
    lines=[]
    for level in context.get('levels',[]):
        location='por delante' if level['ahead'] else 'por detrás'
        lines.append(f"{level['label']}: {level['value']:.2f} · {level['distance_pct']:.3f}% {location}.")
        if level['quality'] in ('CIERRE_DISPONIBLE_NO_VERIFICADO','FALTA_SESION_ANTERIOR'):
            lines.append('Cierre pendiente de verificar con la última barra de la sesión anterior.')
    return '\n'.join(lines) if lines else 'Cierre anterior y máximo histórico: datos insuficientes.'
