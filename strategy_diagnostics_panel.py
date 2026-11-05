"""Explicit-refresh diagnostics, isolated from entry and account connections."""
from datetime import datetime, timezone
from pathlib import Path
import json
import streamlit as st

STATUS = {
    'UNAVAILABLE':'Sin datos disponibles', 'INVALID_OR_INCOMPLETE':'Datos incompletos o inválidos',
    'VERSION_MISMATCH':'Versión del registro diferente', 'FEED_MISMATCH':'Fuentes diferentes',
    'OUTSIDE_SESSION':'Fuera de la sesión regular', 'COLLECTOR_NOT_CURRENT':'Conexión de mercado no reciente',
    'TRADE_NOT_CURRENT':'Precio sin actualización reciente', 'NO_MATCH':'La geometría todavía no se cumple',
    'DETECTOR_NOT_EXIT':'La geometría calculada no está publicada como señal',
    'DETECTOR_MISMATCH':'El registro y la geometría difieren',
    'GEOMETRY_MATCH':'La geometría coincide; revisar vigencia y requisitos de compra',
}
CHECKS = {'opening_inside':'apertura dentro', 'upper_expansion':'expansión superior',
          'lower_expansion':'expansión inferior', 'directional_exit':'salida direccional',
          'midpoint':'dirección de la media'}


def render_strategy_diagnostics(symbols, *, database=None, now=None):
    from market_store import DEFAULT_MARKET_DATABASE
    from strategy_diagnostics import read_snapshot, describe
    st.subheader('Estado de la estrategia')
    st.caption('Valores observados y condiciones de Bollinger. Esta vista no envía órdenes ni activa compañías. '
               'La compra también requiere una señal vigente, contrato apto y fondos verificados.')
    selected = st.multiselect('Compañías para revisar', symbols, default=list(symbols),
                             key='strategy_diagnostic_symbols')
    if st.button('Actualizar diagnóstico', key='strategy_diagnostic_refresh', disabled=not selected):
        clock = now or datetime.now(timezone.utc)
        st.session_state['strategy_diagnostic_snapshot'] = read_snapshot(database or DEFAULT_MARKET_DATABASE, selected, clock)
    snapshot = st.session_state.get('strategy_diagnostic_snapshot')
    if snapshot:
        st.caption('Última lectura: '+snapshot['captured_at']+'. Se actualiza al pulsar el botón.')
        clock = now or datetime.now(timezone.utc)
        records = []
        for symbol in selected:
            r = describe(snapshot, symbol, clock)
            def number(value):return round(value, 5) if value is not None else None
            records.append({'Compañía':symbol, 'Estado':STATUS[r['status']],
                'Fuente':r['feed'] or 'Sin informar', 'Apertura':number(r['opening']),
                'Precio':number(r['price']), 'Banda superior':number(r['upper']),
                'Banda inferior':number(r['lower']), 'Superior %':number(r['upper_pct']),
                'Inferior %':number(r['lower_pct']), 'Mínimo %':r['required_pct'],
                'Edad del precio (s)':number(r['age_seconds']),
                'Condiciones pendientes':', '.join(CHECKS[k] for k in r['missing']) or 'Consultar estado'})
        st.dataframe(records, hide_index=True, width='stretch')
        if not snapshot['available']:
            st.warning('No se pudo leer el diagnóstico en el tiempo disponible. Puedes actualizarlo de nuevo.')
    else:
        st.info('Pulsa Actualizar diagnóstico para consultar los registros actuales de mercado.')
    report_path = Path(__file__).resolve().parent/'exports/trade_review/reference_audits/latest.json'
    try:
        if report_path.stat().st_size > 100000:
            return
        report = json.loads(report_path.read_text(encoding='utf-8'))
        if not isinstance(report,dict) or report.get('purpose') != 'TC2000_REFERENCE_AUDIT_V1':
            return
        st.write('Última comparación con TC2000 · '+report['symbol'])
        st.caption('Análisis histórico del '+report['checked_at']+'. No son cotizaciones en vivo.')
        st.dataframe([{'Medición':k, 'Resultado':v} for k,v in report['display_summary'].items()],
                     hide_index=True, width='stretch')
        st.caption('Las barras sin datos suficientes quedan fuera de la comparación. '
                   'Un archivo de cierre no reconstruye la señal intravela ni demuestra ganancias de opciones.')
    except (OSError, ValueError, KeyError, TypeError):
        pass
