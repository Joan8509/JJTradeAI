"""Descriptive, causal strength snapshot. No trading authority or I/O."""
from datetime import datetime, timedelta
import math

REVISION = 'strength_observation_v1'
# Explicit exploratory thresholds, not fitted probabilities or entry filters.
POLICY = dict(window_seconds=5, max_gap_seconds=2, acceleration_ratio=1.5,
              speed_pct_width_per_second=.2, expansion_multiple=2,
              efficiency=.7, retention=.7, relative_volume=1.5,
              minimum_volume_sessions=10)


def number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def stamp(value):
    result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return result


def evaluate(event, ticks=(), volume=None):
    """Use only observations received/processed by the original detection.

    Future continuity after detection is deliberately not a feature. Missing
    coverage is not zero strength. Stock movements never imply option P&L.
    """
    result = dict(revision=REVISION, mode='OBSERVATION_ONLY', calibrated=False,
                  classification='DATOS_INSUFICIENTES', components={}, metrics={},
                  policy=dict(POLICY), missing=[], source_timestamp=event.get('source_timestamp'),
                  detected_at=event.get('detected_at'), feed=event.get('feed'),
                  side=event.get('side'), price=number(event.get('price')))
    try:
        source, decision = stamp(event['source_timestamp']), stamp(event['detected_at'])
        if source > decision or event.get('source_kind') != 'TRADE':
            raise ValueError('TRADE_REQUIRED')
        direction = {'SUPERIOR': 1, 'INFERIOR': -1}[event['side']]
    except (ValueError, TypeError, KeyError):
        result['missing'] = ['Se requiere una señal TRADE con horas verificables.']
        return result
    band = event.get('band_expansion') or {}
    upper, lower = number(band.get('previous_upper')), number(band.get('previous_lower'))
    width = upper-lower if upper is not None and lower is not None else 0
    a, b, required = (number(band.get(k)) for k in ('upper_pct', 'lower_pct', 'required_pct'))
    if a is not None and b is not None and required is not None and required > 0:
        result['metrics'].update(upper_expansion_pct=a, lower_expansion_pct=b,
                                opposite_expansion_pct=b if direction == 1 else a)
        result['components']['expansion'] = min(a, b) >= required*POLICY['expansion_multiple']
    rows = []
    for row in ticks:
        try:
            t, received, processed = (stamp(row[k]) for k in ('time', 'received', 'processed'))
            price = number(row.get('price'))
            if (source-timedelta(seconds=12) <= t <= source and received <= decision
                    and processed <= decision and t <= received and price is not None and price > 0):
                rows.append((t, price))
        except (ValueError, TypeError, KeyError):
            continue
    rows = sorted(set(rows))
    ambiguous = len({t for t, _ in rows}) != len(rows)
    def anchor(seconds):
        target = source-timedelta(seconds=seconds)
        choices = [r for r in rows if target-timedelta(seconds=1) <= r[0] <= target]
        return choices[-1] if choices else None
    end, mid, start = anchor(0), anchor(5), anchor(10)
    covered = bool(not ambiguous and end and mid and start and width > 0 and
                   end[0] == source and end[1] == result['price'])
    if covered:
        recent = direction*(end[1]-mid[1])/(end[0]-mid[0]).total_seconds()
        prior = abs(mid[1]-start[1])/(mid[0]-start[0]).total_seconds()
        speed = 100*recent/width
        ratio = recent/prior if prior > 0 else None
        result['metrics'].update(speed_pct_width_per_second=speed,
                                acceleration_ratio=ratio)
        result['components']['speed'] = (speed >= POLICY['speed_pct_width_per_second'] and
            recent > 0 and (prior == 0 or recent >= POLICY['acceleration_ratio']*prior))
        path = [r for r in rows if start[0] <= r[0] <= end[0]]
        path = [r for r in path if r[0] >= mid[0]]
        travel = sum(abs(y[1]-x[1]) for x, y in zip(path, path[1:]))
        advance = direction*(end[1]-mid[1])
        peak = max(direction*(p-mid[1]) for _, p in path)
        efficiency = advance/travel if travel > 0 else 0
        retention = advance/peak if peak > 0 else 0
        result['metrics'].update(efficiency=efficiency, retention=retention)
        if all((y[0]-x[0]).total_seconds() <= POLICY['max_gap_seconds']
               for x, y in zip(path, path[1:])):
            result['components']['continuity'] = (efficiency >= POLICY['efficiency'] and
                                                 retention >= POLICY['retention'])
        # Optional direct band velocity: compare geometry from the SAME fixed
        # previous candle. Never confuse expansion amplitude with its speed.
        geometry = []
        for row in ticks:
            try:
                if (stamp(row['time']) in (mid[0], end[0]) and
                    stamp(row['received']) <= decision and stamp(row['processed']) <= decision and
                    row.get('previous_upper') == upper and row.get('previous_lower') == lower):
                    edge = number(row.get('lower' if direction == 1 else 'upper'))
                    if edge is not None:
                        geometry.append((stamp(row['time']), edge))
            except (KeyError, ValueError, TypeError):
                continue
        levels = dict(geometry)
        if mid[0] in levels and end[0] in levels:
            result['metrics']['opposite_band_speed_pct_width_per_second'] = (
                -direction*100*(levels[end[0]]-levels[mid[0]])/width/(end[0]-mid[0]).total_seconds())
    if isinstance(volume, dict):
        ratio = number(volume.get('ratio'))
        # Volume concerns the LAST CLOSED minute, not an unobserved live minute.
        try:
            causal = (stamp(volume['closed_at']) <= source and
                      stamp(volume['known_at']) <= decision)
        except (KeyError, TypeError, ValueError):
            causal = False
        if causal and ratio is not None and ratio >= 0 and volume.get('sessions', 0) >= 10:
            result['components']['volume'] = ratio >= POLICY['relative_volume']
            result['metrics']['volume_previous_closed_minute'] = dict(volume)
    labels = dict(expansion='Expansión de ambas bandas', speed='Velocidad y aceleración (10 segundos previos)',
                  continuity='Continuidad antes de detectar', volume='Volumen relativo del último minuto cerrado')
    result['missing'] = [v for k, v in labels.items() if k not in result['components']]
    known, favorable = len(result['components']), sum(result['components'].values())
    result.update(observed_components=known, favorable_components=favorable)
    if known == 4:
        result['classification'] = 'ALTA' if favorable >= 3 else 'MEDIA' if favorable == 2 else 'BAJA'
    elif known:
        result['classification'] = 'PARCIAL'
    return result


def render(value, *, st):
    if not value:
        st.caption('Fuerza del movimiento: pendiente de observación.')
        return
    label = value.get('classification', 'DATOS_INSUFICIENTES').replace('_', ' ').lower()
    st.write('Fuerza observada: '+label+' · clasificación provisional')
    st.caption('Se calcula en paralelo. No retrasa la compra ni modifica el objetivo o el stop. No es una probabilidad de éxito.')
    with st.expander('Mediciones de fuerza del movimiento'):
        names = dict(expansion='Expansión', speed='Velocidad y aceleración',
                     continuity='Continuidad previa', volume='Volumen del minuto anterior')
        metrics = value.get('metrics', {})
        def describe(key):
            def fmt(name, suffix=''):
                number = metrics.get(name)
                return f'{number:.3f}{suffix}' if number is not None else 'Sin dato'
            if key == 'expansion':
                return 'Superior '+fmt('upper_expansion_pct','%')+' · inferior '+fmt('lower_expansion_pct','%')
            if key == 'speed':
                return fmt('speed_pct_width_per_second','% del ancho/segundo')+' · aceleración '+fmt('acceleration_ratio','×')
            if key == 'continuity':
                return 'Eficiencia '+fmt('efficiency')+' · avance conservado '+fmt('retention')
            v = metrics.get('volume_previous_closed_minute', {})
            return f"{v['ratio']:.2f}× · {v['sessions']} sesiones" if v else 'Sin dato'
        st.dataframe([{'Medición': name, 'Observación':
            'Acompaña' if value.get('components', {}).get(key) is True else
            'No alcanza la referencia' if value.get('components', {}).get(key) is False else
            'Datos insuficientes', 'Valor': describe(key)} for key, name in names.items()], hide_index=True, width='stretch')
        rate = metrics.get('opposite_band_speed_pct_width_per_second')
        if rate is not None:
            st.caption(f'Apertura de la banda contraria: {rate:.3f}% del ancho previo por segundo.')
        st.caption('Referencias experimentales: aceleración 1.5×; velocidad 0.2% del ancho previo por segundo; '
                   'expansión 2× el mínimo; continuidad 70%; volumen 1.5× la mediana de al menos 10 sesiones a la misma hora.')
        st.caption('Precio y hora originales: '+str(value.get('price'))+' · '+str(value.get('source_timestamp')))
