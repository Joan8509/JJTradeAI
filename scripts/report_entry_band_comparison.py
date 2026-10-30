"""Read-only report of future observed 3% entries classified against 5%."""
from pathlib import Path
import sys,argparse,json
from datetime import datetime,date
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from operation_results import read_operation_results
from entry_band_comparison import summarize_entries

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--day',type=date.fromisoformat)
    args=parser.parse_args();now=datetime.now(ZoneInfo('America/New_York'))
    day=args.day or now.date();history=read_operation_results(now=now)
    entries=[e for e in history['entries'] if e['opened_at'].astimezone(now.tzinfo).date()==day]
    report=dict(checked_at=now.isoformat(),entry_day_et=day.isoformat(),
                history_available=history['available'],**summarize_entries(entries))
    target=ROOT/'exports/trade_review/band_comparison'/f'{day.isoformat()}.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,default=str,indent=2),encoding='utf-8')
    print(json.dumps(report,default=str))

if __name__=='__main__':main()
