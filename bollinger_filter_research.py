"""Offline candidate rules. Never suppresses live notifications or executes orders."""
from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class Candidate:
    name: str
    exposure: float = 0
    consecutive: int = 1
    space_pct: float = 0
    pairs: tuple = ()
    hour_direction: bool = False


CANDIDATES=(
    Candidate('BASE'), Candidate('EXPOSICION_1',1), Candidate('EXPOSICION_3',3),
    Candidate('EXPOSICION_1_PERSISTENCIA',1,2),
    Candidate('EXPOSICION_1_ESPACIO_010',1,space_pct=.1),
    Candidate('EXPOSICION_1_ESPACIO_020',1,space_pct=.2),
    Candidate('EXPOSICION_1_PAR_HORA',1,pairs=(('1H',0),)),
    Candidate('EXPOSICION_1_PARES_HORA_DIARIO',1,pairs=(('1H',0),('1D',0))),
    Candidate('EXPOSICION_1_PAR_LARGO_HORA',1,pairs=(('1H',1),)),
    Candidate('EXPOSICION_1_CIERRE_HORA',1,hour_direction=True),
    Candidate('EXPOSICION_1_ESPACIO_010_PAR_HORA',1,space_pct=.1,pairs=(('1H',0),)),
)


def passes(candidate, sample):
    if not sample['signal'] or sample['exposure']<candidate.exposure:
        return False
    if candidate.space_pct and sample.get('space_pct') is not None and sample['space_pct']<candidate.space_pct:
        return False
    if candidate.space_pct and not sample.get('reference_complete',False):
        return False
    for timeframe,pair in candidate.pairs:
        trend=sample['pairs'].get((timeframe,pair),{})
        if not trend.get('validated') or not trend.get('aligned'):
            return False
    if candidate.hour_direction and not sample.get('hour_aligned'):
        return False
    return True


def select(candidate, event, samples):
    consecutive=0
    last=None
    for sample in samples:
        stamp=pd.Timestamp(sample['stamp'])
        if sample.get('missing'):
            return None,'DATOS_FALTANTES_DURANTE_ESPERA'
        if sample['inside']:
            return None,'REGRESO_DENTRO'
        if last is not None and stamp-last!=pd.Timedelta(minutes=1):
            return None,'DATOS_FALTANTES_DURANTE_ESPERA'
        consecutive=consecutive+1 if passes(candidate,sample) else 0
        if consecutive>=candidate.consecutive:
            return {**event,'source_timestamp':stamp.isoformat(),'detected_at':(stamp+pd.Timedelta(minutes=1)).isoformat(),
                    'price':sample['price'],'delay_minutes':int((stamp-pd.Timestamp(event['source_timestamp'])).total_seconds()/60)},'AVISO'
        last=stamp
    return None,'NO_CUMPLE_EN_LA_VELA'
