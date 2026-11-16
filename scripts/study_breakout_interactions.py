"""Exploratory interpretable interaction search; original study remains frozen."""
from pathlib import Path
import sys,json
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from breakout_quality_research import fit_tree,tree_prediction,comparison,day_difference

OUT=ROOT/'exports/trade_review/2026-11-11_common_factors'
KEYS=('opposite','minimum','exposure','width_pct','body_width_pct','volume_ratio','width_ratio')


def main():
    plan=dict(created_at=datetime.now(timezone.utc).isoformat(),mode='EXPLORATORY_RESEARCH_ONLY',
        reason='Supplementary interaction analysis after fixed-candidate study; not an untouched holdout claim.',
        keys=KEYS,max_depth=2,min_leaf=50,thresholds='training feature deciles only',
        weakness='training leaf <=40% positive AND negative mean directional return',
        policy='unknown passes; no real/simulation gates enabled; keep >=40% of observations',
        metric='return_1m',fit_partition='TRAIN',no_selection_on_validation_or_test=True)
    (OUT/'interaction_plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    rows=json.loads((OUT/'minute_rows.json').read_text())
    tree=fit_tree([r for r in rows if r['partition']=='TRAIN'],'return_1m',KEYS)
    prediction=lambda f:tree_prediction(f,tree)
    result=dict(plan=plan,tree=tree,partitions={})
    for partition in ('TRAIN','VALIDATION','TEST','ALL'):
        group=rows if partition=='ALL' else [r for r in rows if r['partition']==partition]
        result['partitions'][partition]=dict(comparison=comparison(group,prediction,'return_1m'),
            bootstrap=day_difference(group,prediction,'return_1m'))
    (OUT/'interactions.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
