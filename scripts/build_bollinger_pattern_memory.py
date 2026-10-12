"""Build compact silent memory from the existing completed playback."""
import gzip
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bollinger_pattern_memory import MEMORY_PATH


def main():
    reports = sorted(MEMORY_PATH.parent.glob('filters_*/report.json.gz'))
    if not reports:
        raise RuntimeError('No playback report available')
    with gzip.open(reports[-1], 'rt', encoding='utf-8') as handle:
        report = json.load(handle)
    records = []
    for row in report['comparisons']:
        if row['candidate'] != 'BASE':
            continue
        result = row['baseline']['fifteen']
        if result['status'] != 'EVALUADA':
            continue
        records.append({key: row[key] for key in ('symbol', 'provider', 'feed', 'side')} |
                       {'stamp': row['original']['source_timestamp'], 'start': result['start'],
                        'end': result['end'], 'positive': result['result'] == 'POSITIVO',
                        'exposure': row['initial_exposure']})
    payload = {'version': report['version'], 'as_of': report['as_of'],
               'source': reports[-1].parent.name, 'records': records}
    temporary = MEMORY_PATH.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, separators=(',', ':')), encoding='utf-8')
    temporary.replace(MEMORY_PATH)
    print('Internal historical records:', len(records))


if __name__ == '__main__':
    main()
