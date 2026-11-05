"""Explicit offline audit command. Writes only private diagnostic artifacts."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tc2000_reference_audit import audit_export

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',required=True)
    parser.add_argument('--symbol',required=True)
    args=parser.parse_args()
    source=Path(args.input)
    if source.stat().st_size>5_000_000:raise ValueError('EXPORT_TOO_LARGE')
    compact,detail=audit_export(source.read_bytes(),ROOT/'exports/market_data.db',
        symbol=args.symbol,now=datetime.now(timezone.utc))
    out=ROOT/'exports/trade_review/reference_audits';out.mkdir(exist_ok=True)
    tag=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    (out/(args.symbol+'_'+tag+'.json')).write_text(json.dumps(detail,indent=2),encoding='utf-8')
    temp=out/('latest_'+tag+'.tmp')
    temp.write_text(json.dumps(compact,indent=2),encoding='utf-8')
    temp.replace(out/'latest.json')
    print(json.dumps(compact,ensure_ascii=True))

if __name__=='__main__':main()
