"""Render the completed offline MA study; never reads operational state."""
from pathlib import Path
import csv,json,hashlib
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'exports/trade_review/2026-11-09_ma_playback'


def main():
    r=json.loads((OUT/'report.json').read_text());h=r['historical'];total=h['summary']['TOTAL']
    labels={'BASE':'Sin filtro de medias','ORDEN_20_HORA_DIARIO':'20/40 ordenadas a favor en Hora y Diario',
        'ORDEN_Y_PENDIENTE_20_HORA_DIARIO':'20/40 orden y pendientes a favor en ambos',
        'ORDEN_100_HORA_DIARIO':'100/200 ordenadas a favor en ambos',
        'ESPACIO_MEDIA_010':'Siguiente media a 0.10% o mas',
        'LIMITE_VALIDADO_010':'Siguiente posible piso/techo a 0.10% o mas'}
    lines=['# Playback de medias: entradas, recorrido y limites','',
        'Conclusión: mantener la entrada inmediata por estrategia valida. No exigir que las medias de Hora y Diario se alineen ni esperar un cruce nuevo. La distancia a una referencia es una variable de recorrido a seguir evaluando, no un filtro universal ni un objetivo de opciones calibrado.','',
        '## Fuentes y metodo','',
        f"Historico congelado: {h['original_signals']} eventos de la regla antigua v3; {h['nonoverlapping_signals']} tras excluir solapes de 15 minutos por compania/cohorte, {h['symbols']} companias, 63 fechas, {h['date_from']} a {h['date_to']}. Contexto SMA Hora/Diario provisional archivado: permite orden, pendiente y distancia; carece de validacion de duracion de cruce y papeles de piso/techo de la metodologia actual.",
        'Senales originales recientes: 84 TRADE con contexto guardado: 63v5, 4v6, 17v7. Se separan versiones, fuenteIEX, alcanceRTH y expansion3%. Precios posteriores del archivo independiente congelados mediante transaccion RO. Solo endpoint a <=1s del horizonte permite retorno; faltantes no son perdidas.',
        'Plan congelado antes de calcular estas agrupaciones; distancias0.10/0.50% son categorias exploratorias heredadas, no limites activos. Ventanas antiguas y resultados ya se habian estudiado: particion cronologica descriptiva, no prueba prospectiva intacta. No se agrego ninguna espera a las reglas candidatas.',
        'El contexto es calculable con informacion conocida al detectar, pero el worker lo genera despues: no demuestra que estuviera disponible antes de enviar una orden. Un eventual filtro requeriria precalculo y validacion de latencia.','',
        '## Entradas: que se conservaria y que se perderia','',
        'Avance antes del primer retroceso: desplazamiento favorable del SUBYACENTE medido con cierres de minuto en el estudio antiguo. Es no negativo por construccion; cero no equivale a operacion perdedora. No son porcentajes de ganancia o acierto de opciones.','',
        '| Regla hipotetica | Senales conservadas | Avance medio antes de retroceso | Casos con avance que descartaria |',
        '|---|---:|---:|---:|']
    for candidate,x in total['first_advance'].items():
        lines.append(f"| {labels[candidate]} | {x['retained']['signals']} / 1120 | {x['retained']['mean_pct']:.4f}% | {x['discarded']['positive']} |")
    lines+=['',
        'Exigir orden20/40 conservaria solo26.1% y eliminaria73.9% de las senales, incluidos434 casos con avance antes de retroceso. Exigir ademas pendientes conservaria14.0% y descartaria500 casos con avance. Esperar confirmacion nueva no forma parte de este ensayo; añadirla podria introducir demora adicional.',
        'En el tramo cronologico reciente365casos, avance medio BASE0.0777%, orden20/40 0.0476%, orden+pendiente0.0439%, orden100/200 0.0663%. No hay una mejora estable de la amplitud al imponer alineacion.','',
        '## Recorrido: distancia a la siguiente media','',
        '| Distancia al detectar | Casos | Avance medio antes de retroceso | Avance maximo medio en la ventana | Retroceso maximo medio |',
        '|---|---:|---:|---:|---:|']
    for name,label in [('CERCA_MENOS_010','Menos0.10%'),('ENTRE_010_050','0.10% a menos0.50%'),('LEJOS_050_O_MAS','0.50% o mas'),('SIN_MEDIA_DELANTE_COMPLETO','Ninguna entre las8medias disponibles')]:
        d=total['distance_buckets'][name];a=d['first_retracement_advance_pct'];m=d['max_extreme_advance_pct'];b=d['max_adverse_pct']
        lines.append(f"| {label} | {a['signals']} | {a['mean_pct']:.4f}% | {m['mean_pct']:.4f}% | {b['mean_pct']:.4f}% |")
    lines+=['',
        'La asociacion bruta sugiere menos recorrido cuando la siguiente SMA esta muy cerca. Tambien hay menos excursion adversa en ese grupo: puede reflejar movimientos pequenos, hora de sesion u otras diferencias, no un efecto causal de la media.',
        'Excluir cualquier media a menos0.10% sube ligeramente el avance bruto0.0789% ->0.0821%, pero elimina47 casos que si avanzaron. Al comparar compania/dia, mejora media+0.00021 puntos porcentuales, IC95%[-0.00200,+0.00175]: cruza cero. No justifica activarlo como filtro.',
        'Una media por delante alineada con tendencia puede representar continuidad. Este historico no tiene roles validados: no se pueden llamar resistencias a las ocho SMA ni estimar un precio exacto de venta.','',
        '## Comprobacion con la version actual','',
        '| Cohorte | Senales | Fechas | Evaluables10s | Evaluables30s | Evaluables60s |',
        '|---|---:|---|---:|---:|---:|']
    for cohort,v in r['recent']['cohorts'].items():
        lines.append(f"| {cohort} | {v['signals']} | {', '.join(v['days'])} | {v['return_10s']['BASE']['retained']['covered']} | {v['return_30s']['BASE']['retained']['covered']} | {v['return_60s']['BASE']['retained']['covered']} |")
    lines+=['',
        'Actualv7:17senales de un dia, solo5endpoints10s,8a30s,5a60s. No publicar100% de eficacia a partir de los5positivos observables a10s. Exigir orden+pendiente20/40HoraDiario habria retenido0/17. La muestra no permite medir una mejora reproducible ni trasladar los resultadosv3 a esta regla.',
        'Solo3casosactuales tienen datos comparables tanto10scomo60s: AAPL09:30 +0.3067% ->+0.6829%; MSFT10:20 +0.0701% ->-0.0314%; TSLA15:15 +0.0118% ->-0.0931%. Son precios de senal, no fills ni P&L de contratos. Ilustran recorridos distintos; no validan un nuevo plazo de venta. No comparar porcentajes de diferentes subconjuntos como si fueran las mismas operaciones.',
        'No hay cobertura continua a1s para demostrar orden de toques de barreras en estas ventanas; no se calibran stops/targets de opciones.','',
        '## Incertidumbre y comprobaciones','',
        'Bootstrap descriptivo2000remuestreos por dia, igual peso por compania/dia. Todos los intervalos de mejora del avance inicial de las reglas examinadas incluyen cero. Confusores de direccion, fase horaria y regimen siguen posibles. Categorias escasas no se transforman en predicciones. Primera/segunda/tercera vela se identifican en datos recientes, pero faltan dias para comparar grupos y versiones de forma estable.',
        'Control cronologico previo separado de36companias: ninguno de los filtros de paresMA paso sus criterios fijados de entrenamiento/validacion. Ese estudio usaba tambien exposicion y decisiones por minuto, por lo que se adjunta como antecedente y no como rendimiento del nuevo lector instantaneo.',
        '20pruebasOK5.906s: ausencia de datos futuros, desconocido distinto deFalse, coste de oportunidades, ausencia de rentabilidad no sustituida por0, exclusiones temporales, roles continuidad/piso/techo, UI y calculo original. Recalculados y contrastados1120featureshistoricos+84recientes con el codigo final.',
        'Intento opcional de reconstruir medias para3ejemplosdeapertura elegidos por el usuario interrumpido por limite seguroSQL. No se modifico el limite operativo ni se uso ningun resultado de ese intento. Esos casos favorables no se agregaron a la muestra para evitar sesgo de seleccion.','',
        '## Decision','',
        '1. Conservar entrada inmediata por estrategia valida y preparar las referencias SMA antes, sin esperar nuevos cruces.',
        '2. Mantener tendencia/recorrido visibles como contexto. La variable candidata mas razonable para investigacion es distancia a un posible piso/techo, distinguiendo continuidad de barrera.',
        '3. No activar bloqueo por alineacion, filtro universal0.10%, toma de ganancia por toqueSMA ni cambios al stop20% con esta evidencia.',
        '4. Para validar cambios de salida hacen falta dias nuevos y BBO/fills del contrato: comprobar objetivo elegido contraSL20 y coste de esperar, sin inferirlos del porcentaje del subyacente.',
        '', 'Sin cambios de estrategia, servicios, colas, objetivos o stop; sin brokerAPI, ordenes ni notificaciones.','',
        'Contexto conceptual: las SMA se usan para tendencias y posibles zonas de soporte/resistencia, no para fijar un techo exacto: https://www.schwab.com/learn/story/how-to-trade-simple-moving-averages .']
    (OUT/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    with (OUT/'historical_policies.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['partition','candidate','retained','advance_before_retracement_mean_pct','favorable_discarded','flat_discarded','unknown'])
        for partition,v in h['summary'].items():
            for c,x in v['first_advance'].items():w.writerow([partition,c,x['retained']['signals'],x['retained']['mean_pct'],x['discarded']['positive'],x['discarded']['flat'],x['unknown']['signals']])
    with (OUT/'recent_policies.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f);w.writerow(['cohort','horizon','candidate','retained','covered','mean_return_pct','favorable_discarded','adverse_discarded','unknown'])
        for cohort,v in r['recent']['cohorts'].items():
            for horizon in ('return_10s','return_30s','return_60s'):
                for c,x in v[horizon].items():w.writerow([cohort,horizon,c,x['retained']['signals'],x['retained']['covered'],x['retained']['mean_pct'],x['discarded']['positive'],x['discarded']['negative'],x['unknown']['signals']])
    paths=list(OUT.glob('*'))+[ROOT/p for p in ['ma_outcome_research.py','scripts/study_ma_outcomes.py','scripts/render_ma_study_report.py','tests/test_ma_outcome_research.py','ma_price_outlook.py','bollinger_ma_context.py']]
    checks={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file() and p.name!='checksums.json'}
    (OUT/'checksums.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in checks.items())
    print(json.dumps(dict(report=str(OUT/'REPORT.md'),checksums_verified=len(checks),bytes=sum(p.stat().st_size for p in OUT.iterdir() if p.is_file()))))


if __name__=='__main__':main()
