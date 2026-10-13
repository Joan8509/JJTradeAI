"""Store descriptive, company/direction/exposure history without selecting exits."""
import gzip,json
from pathlib import Path


def main():
    root=Path('exports/bollinger_playback')
    folder=sorted(root.glob('retracements_*'))[-1]
    with gzip.open(folder/'report.json.gz','rt',encoding='utf-8') as handle:report=json.load(handle)
    rows=[r for r in report['observations'] if r['delay_minutes']==0]
    profiles=[]
    keys=sorted({(r['symbol'],r['provider'],r['feed'],r['side'],r['exposure_group']) for r in rows})
    for symbol,provider,feed,side,exposure in keys:
        sample=[r for r in rows if (r['symbol'],r['provider'],r['feed'],r['side'],r['exposure_group'])==(symbol,provider,feed,side,exposure)]
        values=sorted(r['advance_before_pullback_pct'] for r in sample)
        import pandas as pd
        profiles.append({'symbol':symbol,'provider':provider,'feed':feed,'side':side,'exposure_group':exposure,'sample':len(sample),
            'sessions':len({r['source_timestamp'][:10] for r in sample}),
            'reentry_2m_fraction':sum(r['first_reentry_minutes'] is not None and r['first_reentry_minutes']<=2 for r in sample)/len(sample),
            'pullback_2m_fraction':sum(r['first_pullback_minutes'] is not None and r['first_pullback_minutes']<=2 for r in sample)/len(sample),
            'advance_before_pullback_p25':float(pd.Series(values).quantile(.25)),
            'advance_before_pullback_median':float(pd.Series(values).median()),
            'advance_before_pullback_p75':float(pd.Series(values).quantile(.75))})
    payload={'version':report['version'],'as_of':report['as_of'],'source':folder.name,'profiles':profiles,
        'basis':'Matched complete, nonoverlapping underlying minute paths, theoretical next-open entry. Minute-close pullbacks; intraminute movements may be missed. No fees or option prices.',
        'authority':'DESCRIPTIVE_NO_EXIT_RECOMMENDATION_NO_ALERT_SUPPRESSION'}
    target=root/'retracement_memory.json';temporary=target.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload,indent=2),encoding='utf-8');temporary.replace(target)
    print('Profiles stored:',len(profiles))


if __name__=='__main__':main()
