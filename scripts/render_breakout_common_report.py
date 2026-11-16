"""Produce reviewable Spanish playback report and integrity manifest."""
from pathlib import Path
import sys,json,csv,hashlib
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from breakout_quality_research import CANDIDATES,comparison,rank_on_training,initial_rates
OUT=ROOT/'exports/trade_review/2026-11-11_common_factors'


def fmt(value,digits=3):return 'Sin datos' if value is None else f'{value:.{digits}f}'


def main():
    report=json.loads((OUT/'report.json').read_text());interaction=json.loads((OUT/'interactions.json').read_text())
    impulse=json.loads((OUT/'initial_impulse.json').read_text());waiting=json.loads((OUT/'waiting_for_five.json').read_text())
    minutes=json.loads((OUT/'minute_rows.json').read_text());ticks=json.loads((OUT/'tick_rows_with_rates.json').read_text())
    current=[r for r in ticks if r['cohort'].startswith('v7_')]
    names=dict(BASE='Estrategia sin filtro adicional',OPPOSITE_5='Banda contraria >=5%',
        OPPOSITE_8='Banda contraria >=8%',BOTH_5='Ambas bandas >=5%',VOLUME_15='Volumen relativo >=1.5x',
        EXPOSURE_1='Ruptura >=1% del ancho previo',WIDTH_ABOVE_MEDIAN='Ancho superior a mediana reciente',
        POSITIVE_PACE='Desplazamiento previo favorable',OPPOSITE_5_VOLUME_15='Banda contraria5% + volumen1.5x',
        OPPOSITE_5_POSITIVE_PACE='Banda contraria5% + desplazamiento favorable')
    text=['# Playback de factores comunes de ruptura',
        '', 'Se estudio la primera entrada, sin esperar a confirmar con velas futuras. Resultado: el volumen relativo es una asociacion candidata, pero no se encontro un filtro que mejore de forma consistente la seleccion instantanea de la version actual. No se activa ninguno.',
        '', '## Evidencia y separacion temporal', '',
        f'Historial: {len(minutes)} eventos sin solape de5min, 19 companias y62 sesiones (05/08-30/10). Reconstruccion con apertura inicial dentro y3% por banda. Son muestras de apertura de minuto; NO reproducen la primera ruptura intraminuto ni el vencimiento30sV7. Fuentes originales congeladas, verificadas por SHA256.',
        'Particion cronologica:22 sesiones de desarrollo,20 de contraste y20 posteriores. Este historial ya habia sido examinado antes: control retrospectivo descriptivo, no validacion prospectiva intacta. Los volumenes historicos cerrados son computables desde ese instante, pero sus recibos/revisiones originales no estan preservados; no equivalen a disponibilidad garantizada antes de la compra.',
        f'Archivo reciente:140 señales TRADE originales;73V7 del9/10/11Nov, separadas de63V5 y4V6. Hay1.163.718 ticks conservados en el archivo al inventariar; se congelo solo la evidencia relevante. Sin discontinuidades registradas de retencion; esto no establece cobertura de todos los mercados. FuenteIEX/RTH, no NasdaqBasic.',
        'Se ajustan criterios en el tramo de desarrollo; se muestran tambien resultados negativos y oportunidades descartadas. Un dato faltante mantiene la decision previa: no se convierte en veto ni perdida. Los porcentajes son del subyacente, nunca ganancias de opciones.',
        '', '## Hallazgo1: esperar5% perjudica la primera entrada', '',
        '72/73 señalesV7 tenian expansion de la banda contraria entre3% y5% en la primera deteccion; solo una ya alcanzaba5%. El umbral3% comprime esta variable en el instante inicial: la amplitud aislada ofrece poca discriminacion entre continuaciones y reversiones.',
        f"Al reproducir las condiciones con5%, conservando el MISMO reloj30s y frescura3s: {waiting['summary']['BOTH_5']['observed_eligible']}/73 tuvieron un precio apto observado antes de vencer; en61 no se observo. No significa que se conozcan los prints no archivados.",
        f"En las12 observadas,11 requerian esperar: mediana {waiting['summary']['BOTH_5']['median_delay']:.2f}s; cambio direccional medio del precio {waiting['summary']['BOTH_5']['mean_price_change']:.4f}%. Es desplazamiento del subyacente mientras se espera, no slippage real ni P&L. Banda contraria5% y ambas5% produjeron la misma seleccion observada.",
        '', '## Hallazgo2: fuerza y continuidad no son el mismo resultado', '',
        '| Regla hipotetica | Casos conservados | Avance maximo medio1min | Retroceso maximo medio1min |',
        '|---|---:|---:|---:|']
    for c in ('BASE','OPPOSITE_5','VOLUME_15','OPPOSITE_5_VOLUME_15'):
        forward=report['minute_secondary']['mfe_1m']['ALL']['candidates'][c]['unknown_pass']
        adverse=report['minute_secondary']['mae_1m']['ALL']['candidates'][c]['unknown_pass']
        text.append(f"| {names[c]} | {forward['signals']} | {fmt(forward['mean'])}% | {fmt(adverse['mean'])}% |")
    text += ['', 'El conjunto bandas5%+volumen1.5x casi duplica el recorrido favorable medio, pero tambien aumenta el adverso. Conservaria112/1096 casos y descartaria484 que terminaron el primer minuto a favor. Mayor recorrido no prueba una entrada mas certera ni que el objetivo se toque antes que el stop.',
        '', '## Hallazgo3: volumen relativo, candidato aun no aprobado', '',
        'Sobre919 eventos con volumen comparable conocido, el grupo inferior a1x termina el primer minuto a favor en139/303 (45.9%); el grupo>=1.5x en226/410 (55.1%). Es asociacion bruta, no una tasa de ganancia de contratos ni control por regimen.',
        'En los20 dias posteriores, el criterio1.5x conserva160/309 casos (incluye3 desconocidos que no se bloquean):53.1% terminan a favor, frente a49.2% general. Descarta67 favorables y79 desfavorables. Al equilibrar compania/dia, la diferencia de retorno no es concluyente y su intervalo95% cruza cero; no promover a filtro por el agregado.',
        '', '## Primer impulso, evitando confundirlo con el cierre', '',
        'Se examino tambien el primer toque de una barrera simetrica de0.1 del ancho previo de Bollinger durante el primer minuto, heredada del estudio original.185 casos con toque favorable inequívoco,169 adverso,45 ambiguos (ambos lados) y697 sin toque. Estos742 ultimos no son perdidas ni aciertos. No se sabe el orden intraminuto cuando ambos niveles se tocan; no son barreras de opciones.',
        '', '| Tramo | Base: favorables entre casos claros | Bandas5% + volumen1.5x |',
        '|---|---:|---:|']
    for p,label in (('TRAIN','Desarrollo'),('VALIDATION','Contraste'),('TEST','20 sesiones posteriores')):
        c=impulse['minute_partitions'][p]['fixed']
        a,b=c['BASE']['unknown_pass'],c['OPPOSITE_5_VOLUME_15']['unknown_pass']
        text.append(f"| {label} | {fmt(a['positive_pct'],1)}% ({a['covered']}) | {fmt(b['positive_pct'],1)}% ({b['covered']}) |")
    text += ['', 'La combinacion aparenta65.2% en el total de casos claros, pero cae a46.7% en las sesiones posteriores, por debajo de53.4% base. No presentarla como mejora validada: el agregado oculta inestabilidad temporal y grandes descartes.',
        '', '## Resultados de todos los candidatos', '',
        'Metricas de cierre del primer minuto, distintas del apartado de primer toque. Los desconocidos pasan. Se incluye el coste de descartar movimientos favorables.',
        '', '| Criterio | Conserva de1096 | Final a favor | Favorables descartados | Desfavorables descartados |',
        '|---|---:|---:|---:|---:|']
    for c in CANDIDATES:
        r=report['minute_results']['ALL']['candidates'][c];a=r['unknown_pass'];b=r['discarded']
        text.append(f"| {names[c]} | {a['signals']} | {fmt(a['positive_pct'],1)}% | {b['positive']} | {b['negative']} |")
    text += ['', 'Ni el entrenamiento con criterios prefijados eligio un candidato que cumpliera todos los requisitos de mejora y conservacion de oportunidades. Algunos criterios son redundantes en esta muestra; no constituyen confirmaciones independientes.',
        '', '## Modelo de interacciones desarrollado y contrastado', '',
        'Se desarrollo un arbol interpretable limitado a profundidad2 y al menos50 casos por hoja, con umbrales tomados SOLO de deciles de caracteristicas del entrenamiento. Puede abstenerse ante datos ausentes. Busca combinaciones de volumen, anchura, expansion, cuerpo y profundidad de ruptura. Su analisis es suplementario y exploratorio, declarado despues del estudio prefijado; no se ajusta usando el tramo posterior.',
        '', '| Tramo | Final a favor sin filtro | Final a favor con modelo | Casos conservados |',
        '|---|---:|---:|---:|']
    for p,label in (('TRAIN','Desarrollo'),('VALIDATION','Contraste'),('TEST','20 sesiones posteriores')):
        r=interaction['partitions'][p]['comparison'];a=r['baseline'];b=r['unknown_pass']
        text.append(f"| {label} | {fmt(a['positive_pct'],1)}% | {fmt(b['positive_pct'],1)}% | {b['signals']}/{a['signals']} |")
    text += ['', 'El modelo identifica una debilidad aparente en el entrenamiento, pero empeora en el tramo posterior:46.6% frente a49.2%. Se deja desarrollado para reproducir y descartar esa hipotesis, sin conectarlo a las compras. El segundo arbol para primer toque no encuentra una hoja que supere su criterio prefijado de debilidad; tampoco habilita un filtro.',
        '', '## Comprobacion en la version actual y calculo sin demora', '',
        'V7:73 señales de3 sesiones. Cobertura estricta del precio al final:30 a10s,21 a30s y25 a60s (muestra a menos1s del horizonte). Sensibilidad a30s con tolerancia3s:45 casos, sin usarlos para elegir criterios. No comparar subconjuntos distintos como si fueran las mismas operaciones.',
        'A30s, el filtrovolumen1.5x tiene solo2 observaciones con ese volumen alto conocido:ninguna termina a favor (una adversa y otra plana). Es una muestra demasiado pequeña, pero no confirma el patron historico. El historial de contratos simulados consultado termina30Oct: no aporta operaciones de esta cohorteV7 para validar ganancias10% o stop20%.',
        'Se desarrollo ademas una medicion de VELOCIDAD de apertura contraria desde la geometria anterior, hasta3s antes y con las mismas bandas previas. Es calculable en38/73 eventos frente a la necesidad anterior de ventanas mas largas; no requiere esperar nuevos prints. Tiempo desde primera salida conocido en73;60 aparecieron en el mismo instante del reloj y63 dentro de1s. Esos datos no demuestran mejor resultado por recortar el plazo a1s.',
        '', '## Decision tecnica', '',
        '1. Conservar entrada inmediata con3%, apertura inicial dentro y reloj30s. No esperar5% ni un cierre futuro.',
        '2. Mantener volumen como variable candidata, diferenciando el volumen ya cerrado del que entra en el impulso. No tratar un volumen previo bajo como prueba de que no llegara una ruptura fuerte.',
        '3. Conservar el modelo y las mediciones desarrolladas como investigacion reproducible; no activar los criterios fallidos en REAL ni simulacion.',
        '4. Para una seleccion operativa nueva hacen falta datos de la misma regla y precios de contratos, comprobar primero objetivo/stop, frecuencia y oportunidades perdidas. El siguiente contraste debe ser con sesiones nuevas; estos resultados no se deben volver a llamar validacion independiente.',
        '', '## Integridad y alcance', '',
        'Solo se leyeron SQLite con mode=ro y query_only; no se abrieron feeds, sesiones broker, claves o Telegram. Se congelaron senales e inputs relevantes en este directorio privado. Fuentes historicas originales verificadas por SHA256; pruebas cubren causalidad, desconocidos, particiones, solapes, denominadores y vencimiento estricto. Sin recargas, activaciones, ordenes, cambios de stop/objetivo o filtros. Se añadio exclusion Git para el archivo privado movement_strength.sqlite3 y sus auxiliares.',
        '', 'Archivos: plan.json,report.json,minute_rows.json,original_trade_signals.json,frozen_tick_evidence.json,interactions.json,initial_impulse.json,waiting_for_five.json,candidate_summary.csv,validation.json ychecksums.json.']
    (OUT/'REPORT.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    with (OUT/'candidate_summary.csv').open('w',newline='',encoding='utf-8-sig') as f:
        fields=('dataset','partition','candidate','signals','covered','positive_pct','mean','unknown_signals','missed_positive','discarded_negative')
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for dataset,key in (('MINUTE_PROXY','minute_results'),('CURRENT_V7_SECONDS','current_tick_results')):
            for part in ('TRAIN','VALIDATION','TEST','ALL'):
                for c,r in report[key][part]['candidates'].items():
                    a=r['unknown_pass'];b=r['discarded']
                    writer.writerow(dict(dataset=dataset,partition=part,candidate=c,
                        **{k:a[k] for k in ('signals','covered','positive_pct','mean')},
                        unknown_signals=r['unknown']['signals'],missed_positive=b['positive'],discarded_negative=b['negative']))
    # Recompute stored comparisons and rates, proving they match final source.
    for part in ('TRAIN','VALIDATION','TEST','ALL'):
        selected_rows=minutes if part=='ALL' else [r for r in minutes if r['partition']==part]
        for c in CANDIDATES:
            assert comparison(selected_rows,c,'return_1m')==report['minute_results'][part]['candidates'][c]
    assert rank_on_training([r for r in minutes if r['partition']=='TRAIN'],'return_1m')==report['minute_results']['chosen_on_training']
    original={e['event_key']:e for e in json.loads((OUT/'original_trade_signals.json').read_text())}
    evidence=json.loads((OUT/'frozen_tick_evidence.json').read_text())
    for r in ticks:
        rates=initial_rates(original[r['source_event_key']],evidence[r['source_event_key']]['ticks'])
        assert all(r['features'][k]==v for k,v in rates.items())
    validation=dict(checked_at=datetime.now(timezone.utc).isoformat(),minute_rows=len(minutes),tick_rows=len(ticks),current_v7=len(current),
        comparisons_reproduced=40,rates_reproduced=len(ticks),source_write_access=False,
        activation='NONE_RESEARCH_ONLY',orders=0,notices=0,
        test_modules=['tests.test_breakout_quality_research','tests.test_movement_strength','tests.test_opening_strength_study'])
    (OUT/'validation.json').write_text(json.dumps(validation,indent=2),encoding='utf-8')
    paths=[p for p in OUT.iterdir() if p.is_file() and p.name!='checksums.json']
    paths += [ROOT/p for p in ('breakout_quality_research.py','scripts/study_breakout_common_factors.py',
        'scripts/study_breakout_interactions.py','scripts/study_initial_impulse.py','scripts/study_waiting_for_five.py',
        'scripts/render_breakout_common_report.py','tests/test_breakout_quality_research.py')]
    checks={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (OUT/'checksums.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha for p,sha in checks.items())
    print(json.dumps(validation|dict(checksums_verified=len(checks),report=str(OUT/'REPORT.md')),ensure_ascii=True))


if __name__=='__main__':main()
