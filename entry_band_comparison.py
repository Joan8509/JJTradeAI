"""Descriptive 3%/5% comparison. Never authorizes, delays or rejects an order."""
from datetime import datetime
from decimal import Decimal
from bollinger_expansion import MINIMUM_BAND_EXPANSION_PCT,measure_band_expansion

REVISION='entry_band_3_vs_5_observation_v1'
CANDIDATE_MINIMUM_PCT=5.0


def compare_snapshot(snapshot):
    result=dict(revision=REVISION,mode='OBSERVATION_ONLY',
        active_minimum_pct=MINIMUM_BAND_EXPANSION_PCT,
        candidate_minimum_pct=CANDIDATE_MINIMUM_PCT,status='UNKNOWN',meets_candidate=None)
    try:
        geometry=snapshot.get('geometry') or (snapshot.get('signal') or {}).get('band_expansion')
        measured=measure_band_expansion(*(geometry[key] for key in
            ('upper','lower','previous_upper','previous_lower')))
        stamp=datetime.fromisoformat(snapshot['source_timestamp'].replace('Z','+00:00'))
        if stamp.tzinfo is None:return result
        passed=measured.meets(CANDIDATE_MINIMUM_PCT)
        result.update(status='PASS_5' if passed else 'BELOW_5',meets_candidate=passed,
            upper_pct=measured.upper_pct,lower_pct=measured.lower_pct,
            minimum_pct=measured.minimum_pct,source_at=stamp.isoformat())
    except (TypeError,ValueError,KeyError,AttributeError,OverflowError):
        pass
    return result


def attach_comparison(order,snapshot):
    # Pure arithmetic/metadata only, no filesystem, API, queue or additional
    # SQLite commit. A diagnostic failure must never change execution.
    try:order['entry_band_comparison']=compare_snapshot(snapshot)
    except Exception:pass


def summarize_entries(entries):
    """Group actual filled trades. This is never hypothetical 5% strategy PnL."""
    groups={name:dict(entries=0,open=0,closed=0,wins=0,losses=0,flat=0,gross=Decimal(0))
            for name in ('PASS_5','BELOW_5','UNKNOWN')}
    for entry in entries:
        study=entry.get('entry_band_comparison') or {}
        status=study.get('status','UNKNOWN') if isinstance(study,dict) else 'UNKNOWN'
        if (not isinstance(study,dict) or study.get('revision')!=REVISION
            or study.get('active_minimum_pct')!=3 or study.get('candidate_minimum_pct')!=5
            or study.get('mode')!='OBSERVATION_ONLY' or status not in groups):status='UNKNOWN'
        group=groups[status];group['entries']+=1
        if entry['status']!='CLOSED':group['open']+=1;continue
        pnl=Decimal(str(entry['report']['gross_pnl']))
        group['closed']+=1;group['gross']+=pnl
        group['wins' if pnl>0 else 'losses' if pnl<0 else 'flat']+=1
    return dict(revision=REVISION,mode='OBSERVATION_ONLY',groups=groups,
                actual_local_simulation_results_only=True,hypothetical_five_percent_pnl=False)
