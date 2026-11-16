"""Render and validate the frozen report without touching live data."""
from pathlib import Path
from datetime import datetime,timezone
from statistics import fmean
import json,hashlib,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from breakout_quality_research import rank_on_training
OUT=ROOT/'exports/trade_review/2026-11-13_fast_opportunities'

def metric(s):
    rate=s['positive_pct']
    return f"{s['positive']}/{s['covered']} ({rate:.1f}%)" if rate is not None else 'Sin cobertura'

def main():
    report=json.loads((OUT/'report.json').read_text(encoding='utf-8'))
    rows=json.loads((OUT/'current_rows.json').read_text(encoding='utf-8'))
    events=json.loads((OUT/'original_trade_signals.json').read_text(encoding='utf-8'))
    frozen=json.loads((OUT/'frozen_tick_evidence.json').read_text(encoding='utf-8'))
    examples=report['examples'];slv=next(r for r in examples if r['symbol']=='SLV')
    tsla=next(r for r in examples if r['symbol']=='TSLA')
    slv_ticks=frozen[slv['source_event_key']]['ticks']
    training=[r for r in rows if r['partition']=='TRAIN']
    assert rank_on_training(training,'return_10s')==report['chosen_on_training']
    assert all(r['cohort']=='v7_ruptura_temprana_30s|iex|REGULAR' for r in rows)
    cutoff=datetime.fromisoformat(report['plan']['frozen_at']).timestamp()-70
    assert all(r['at']<=cutoff for r in rows)
    selected_keys={r['source_event_key'] for r in rows}
    known={e['event_key']:e for e in events}
    assert selected_keys<=known.keys()
    # These samples must not overlap within one company/day.
    last={}
    for r in sorted(rows,key=lambda r:r['at']):
        key=(r['day'],r['symbol'])
        assert r['at']>=last.get(key,-1)+60
        last[key]=r['at']
    lines=['# Movimientos rápidos: comparación actualizada al 13/11/2026',
      '',f"Corte: {report['plan']['frozen_at']}. {len(rows)} señales V7, IEX y sesión regular. El día 13 es parcial.",
      '9–11/11 desarrollo (73 señales); 12–13/11 contraste posterior (37). Umbrales fijados antes de evaluar los días posteriores.',
      'Las fechas de desarrollo ya se habían estudiado. SLV fue elegida por su éxito; no es un ejemplo seleccionado a ciegas.',
      '', '## Resultado de SLV y diferencia con TSLA',
      '', 'SLV: PUT, un contrato a $0.57 a las 09:52:39; salida BROKER_TARGET a $0.63 a las 10:01:44.',
      'Ganancia bruta $6.00 / 10.53%; duración 9 min 05 s. No se descuentan comisiones al llamar a esta cifra bruta.',
      'Primer evento SLV: 09:52:22.525829; hasta el fill transcurren 16.47 s. Esto no demuestra 16.47 s de latencia del broker: puede incluir búsqueda/validación del contrato. No separar fases sin sus recibos.',
      '', '| Al primer evento | SLV ganadora real | TSLA ruptura que retrocedió |',
      '|---|---:|---:|',
      f"| Banda contraria / ancho anterior | {slv['features']['opposite']:.2f}% | {tsla['features']['opposite']:.2f}% |",
      f"| Ancho actual / media | {slv['bandwidth_pct']:.2f}% | {tsla['bandwidth_pct']:.2f}% |",
      '| Orden/pendiente SMA20/40 H y D guardadas | Alineadas | Alineadas |',
      f"| Retorno subyacente a 30 s | No cubierto | {tsla['outcomes']['return_30s']:.3f}% |",
      '', 'La apertura opuesta por sí sola no distingue estos dos casos. Exigir 5% habría eliminado ambos, incluida SLV.',
      'La mayor anchura absoluta tampoco favorece por sí sola a SLV. Las medias guardadas estaban alineadas en ambos casos.',
      'Las medias se añadieron de forma asíncrona al evento: no se ha demostrado que el contexto completo estuviera disponible para comprar en ese instante.',
      '', '## Cobertura y resultados por fecha',
      '', 'Resultado positivo aquí significa precio del subyacente a favor en ese horizonte; no operación de opciones ganada.',
      '| Grupo | Señales | A favor a 10 s | A favor a 30 s | A favor a 60 s |',
      '|---|---:|---:|---:|---:|']
    for part in ('TRAIN','LATER_12','LATER_13','LATER_ALL'):
        r=report['results'][part]
        lines.append('| '+part+' | '+str(r['signals'])+' | '+' | '.join(metric(r['metrics'][m]['BASE']['baseline']) for m in ('return_10s','return_30s','return_60s'))+' |')
    lines+=['','## Todos los candidatos en las fechas posteriores','',
      'Comparación sobre el mismo subconjunto con el dato disponible. Faltantes se muestran, no se convierten en descartes ni pérdidas.',
      '| Criterio previo a entrar | Pasa: a favor / cubiertos 10 s | Base con dato conocido | Descartados que fueron a favor / cubiertos | Señales sin dato |',
      '|---|---:|---:|---:|---:|']
    for name,c in report['results']['LATER_ALL']['metrics']['return_10s'].items():
        if name=='BASE':continue
        lines.append(f"| {name} | {metric(c['retained'])} | {metric(c['known_baseline'])} | {metric(c['discarded'])} | {c['unknown']['signals']} |")
    lines+=['','## Horario de las oportunidades','',
      '| Fechas posteriores | Señales | A favor a 10 s | A favor a 30 s |',
      '|---|---:|---:|---:|']
    for group,x in report['results']['LATER_ALL']['windows'].items():
        lines.append(f"| {group} | {x['return_10s']['signals']} | {metric(x['return_10s'])} | {metric(x['return_30s'])} |")
    lines+=['', '## Candidatos concretos y sus límites', '',
      'Volumen relativo >=1.5: en las fechas posteriores hubo movimiento a favor a10s en4/6 casos cubiertos; el grupo descartado tuvo2/5. TSLA tenía volumen relativo5.60 y aun así retrocedió: no basta por sí solo.',
      'Recorrido fuera de la banda >=1% del ancho previo:3/3 a favor a10s, solo3 ejemplos cubiertos; además descartaría SLV al primer evento (0.75%). No convertir ese resultado pequeño en porcentaje de acierto operativo.',
      'Primera media hora después de apertura (09:45–10:15):3/4 a favor a30s frente2/6 más tarde en los días posteriores; muestra pequeña y de distinta composición, no permite prohibir otros horarios.',
      '', '## Rapidez real de SLV: cuello de botella comprobado', '']
    latency_path=OUT/'slv_latency.json'
    if latency_path.exists():
        latency=json.loads(latency_path.read_text(encoding='utf-8'))
        attempt=next(r for r in latency['attempts'] if r.get('first_signal_at','').startswith('2026-11-13'))
        first=attempt['first_attempt'];latest=attempt['seconds']
        assert first['error_code']=='TRADE_NOT_CURRENT'
        assert first['seconds']['contract_search']>latest['contract_search']
        lines += [f"Primer intento: {first['seconds']['total']:.2f}s; búsqueda de contrato {first['seconds']['contract_search']:.2f}s, terminó {first['checked_at']}. Resultado TRADE_NOT_CURRENT: se conservó la protección de frescura.",
          f"Intento preparado: {latest['total']:.2f}s, incluida búsqueda {latest['contract_search']:.2f}s y preview {latest['broker_preview']:.2f}s; fin {attempt['checked_at']}.",
          'El archivo IEX muestra una separación de14.53s entre el primer print de señal y el siguiente aceptado. No atribuir todo ese intervalo a procesamiento o latencia de compra.',
          'Mejora prioritaria propuesta: revisar la preparación anticipada del catálogo de las compañías seleccionadas y su recuperación después de renovar DATOS. Reutilizar el catálogo vigente, conservando cotización y preview actuales. Esa preparación ya tiene un mecanismo en la app; el estudio no demuestra todavía por qué no estuvo disponible a tiempo para este primer intento.',
          'No se ha activado una política nueva de caché ni se estima un ahorro garantizado a partir de dos intentos.']
    lines+=['', '## Decisión', '',
      f"Criterio elegido por el selector solo en desarrollo: {report['chosen_on_training'] or 'ninguno supera simultáneamente cobertura, mejora de tasa y retorno medio requeridos'}.",
      'El desarrollo tiene solo30 resultados cubiertos a10s y el selector exige30 retenidos: no puede aprobar un filtro que descarte alguno de ellos. Su abstención significa soporte insuficiente, no demuestra que todos los candidatos sean ineficaces.',
      'Mantener detección inmediata de la regla V7 vigente; no activar un filtro universal de 5%, ancho absoluto o alineación SMA con estos resultados.',
      'Los criterios con cifras favorables en los días posteriores quedan como candidatos descriptivos: el conjunto es pequeño y no se elige a posteriori el de mejor resultado.',
      'La mejora concreta para la siguiente etapa es completar evidencia al instante de señal y contrato: bid/ask, spread, coste/preview, envío/fill y ruta posterior del mismo contrato. Esto permite medir rapidez y ganancia real por separado.',
      'La comprobación de esos datos debe ejecutarse en paralelo o reutilizar datos precalculados: no añadir segundos de confirmación a la compra.',
      'No se cambió producción, estrategia, porcentajes, servicios, colas ni órdenes.',
      '', '## Verificación', '',
      'Datos de mercado/archivo consultados solo lectura. Señales maduras (70 s), un evento por compañía en 60 s, misma versión/fuente/sesión, selección solo desarrollo comprobadas.',
      'No se rellenaron huecos ni se utilizaron precios futuros para las variables de entrada. Datos posteriores son etiquetas de evaluación.',
      f"Ticks archivados de SLV en ventana de estudio: {len(slv_ticks)}. Los endpoints que no satisfacen tolerancia de 1 s permanecen sin resultado.",
      'El informe y JSON conservan todos los criterios, cobertura y señales descartadas. Sin consultas al broker ni avisos de prueba en el playback.']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    validation=dict(checked_at=datetime.now(timezone.utc).isoformat(),rows=len(rows),checks=['cohort','maturity','no_overlap','event_identity','training_only_selection'],
                    slv_tick_count=len(slv_ticks),orders_sent=False,production_changed=False)
    (OUT/'validation.json').write_text(json.dumps(validation,indent=2),encoding='utf-8')
    print('\n'.join(lines[28:60]))

if __name__=='__main__':main()
