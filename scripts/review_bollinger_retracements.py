"""Clustered, paired comparison; does not select live exit rules."""
import gzip,json,random,statistics
from pathlib import Path


def interval(rows,plan,baseline='TIME_5',repetitions=2000):
    days={}
    for row in rows:
        delta=row['plans'][plan]['return_pct']-row['plans'][baseline]['return_pct']
        days.setdefault(row['source_timestamp'][:10],[]).append(delta)
    clusters=[(sum(values),len(values)) for values in days.values()]
    if not clusters:return [None,None],0
    rng=random.Random(1729)
    samples=[]
    for _ in range(repetitions):
        chosen=[rng.choice(clusters) for _ in clusters]
        samples.append(sum(s for s,n in chosen)/sum(n for s,n in chosen))
    samples.sort()
    # Bonferroni descriptive screen across ten alternatives, paired by event.
    return [samples[int(.0025*repetitions)],samples[int(.9975*repetitions)]],len(clusters)


def conditional_continuity(rows):
    groups=[]
    for period in ('TRAIN','VALIDATION','RECENT'):
        for label in (True,False):
            cohort=[]
            for row in rows:
                if row['period']!=period:continue
                continues=(row['first_pullback_minutes'] is None or row['first_pullback_minutes']>2) and (row['first_reentry_minutes'] is None or row['first_reentry_minutes']>2) and row['plans']['TIME_2']['return_pct']>0
                if continues==label:cohort.append(row)
            outcomes={}
            for minute in (5,10,15):
                changes=[]
                for row in cohort:
                    sign=1 if row['side']=='SUPERIOR' else -1
                    before=1+sign*row['plans']['TIME_2']['return_pct']/100
                    after=1+sign*row['plans']['TIME_'+str(minute)]['return_pct']/100
                    changes.append(sign*(after/before-1)*100)
                outcomes[str(minute)]={'mean_return_from_minute3_pct':sum(changes)/len(changes) if changes else None,
                    'positive_pct':100*sum(c>0 for c in changes)/len(changes) if changes else None}
            groups.append({'period':period,'continuity_observed_after_two_minutes':label,'sample':len(cohort),'outcomes_after_observation':outcomes})
    return groups


def main():
    folder=sorted(Path('exports/bollinger_playback').glob('retracements_*'))[-1]
    with gzip.open(folder/'report.json.gz','rt',encoding='utf-8') as handle:p=json.load(handle)
    rows=[r for r in p['observations'] if r['delay_minutes']==0]
    reviews=[]
    for plan in p['plans_fixed_before_run']:
        if plan=='TIME_5':continue
        evidence=[];passes=True
        for period in ('TRAIN','VALIDATION','RECENT'):
            cohort=[r for r in rows if r['period']==period]
            bounds,sessions=interval(cohort,plan)
            mean=sum(r['plans'][plan]['return_pct'] for r in cohort)/len(cohort) if cohort else None
            stable=len(cohort)>=(100 if period=='TRAIN' else 50) and sessions>=10 and bounds[0]>0 and mean>0
            if period!='RECENT':passes=passes and stable
            evidence.append({'period':period,'n':len(cohort),'sessions':sessions,'mean_return_pct':mean,
                             'paired_gain_over_TIME5_interval':bounds,'passes_descriptive_screen':stable})
        reviews.append({'plan':plan,'training_validation_pass':passes,'evidence':evidence})
    comparisons=[]
    for symbol in sorted({r['symbol'] for r in rows}):
        for side in ('SUPERIOR','INFERIOR','BOTH'):
            group=[r for r in rows if r['symbol']==symbol and (side=='BOTH' or r['side']==side)]
            groups={name:[r for r in group if r['exposure_group']==name] for name in ('SMALL_LT1','LARGE_GE3')}
            if min(map(len,groups.values()))<20:continue
            rates={name:100*sum(r['first_reentry_minutes'] is not None and r['first_reentry_minutes']<=2 for r in values)/len(values)
                   for name,values in groups.items()}
            comparisons.append({'symbol':symbol,'side':side,'samples':{name:len(v) for name,v in groups.items()},'reentry_within_2min_pct':rates})
    slim={k:v for k,v in p.items() if k!='observations'}
    slim['exit_review']=reviews;slim['within_company_exposure_comparison']=comparisons
    slim['conditional_continuity']=conditional_continuity(rows)
    slim['conditional_continuity_definition']='Known only after two minute closes and next open: no earlier adverse close, no reentry during first two minutes, and positive move at minute3 open. Later returns measured from that open, excluding qualification-period profit. Cannot predict original alert.'
    slim['review_limitations']='Paired day-cluster bootstrap screen against TIME5 with fixed seed and multiplicity adjustment. Underlying only, no costs, not an independently validated optimal exit; recent period previously explored. No live plans activated.'
    (folder/'summary.json').write_text(json.dumps(slim,indent=2),encoding='utf-8')
    print('TRAIN_VALIDATION_PASS',[r['plan'] for r in reviews if r['training_validation_pass']])
    print('WITHIN_COMPANY',json.dumps(comparisons))
    print('OUTPUT',folder)


if __name__=='__main__':main()
