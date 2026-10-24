"""Package only the two VPS fixes and standalone regressions; no private files."""
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import zipfile

ROOT = Path(__file__).resolve().parents[1]
GIT = Path('C:/Users/Administrator/AppData/Local/GitHubDesktop/app-3.6.7/resources/app/git/cmd/git.exe')
PRODUCTION = ('live_strategy_service.py', 'bollinger_tick_stream.py')


def method(path, name):
    source = (ROOT/path).read_text(encoding='utf-8')
    node = next(n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.FunctionDef) and n.name == name)
    return textwrap.indent(textwrap.dedent('\n'.join(source.splitlines()[node.lineno-1:node.end_lineno])), '    ')


def main():
    now = datetime.now(timezone.utc)
    stage = ROOT/'exports/backups'/('pc_fixes_'+now.strftime('%Y%m%dT%H%M%SZ'))
    (stage/'tests').mkdir(parents=True)
    base = subprocess.check_output([str(GIT), 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    patch = subprocess.check_output([str(GIT), 'diff', '--binary', 'HEAD', '--', *PRODUCTION], cwd=ROOT)
    if not patch:
        raise ValueError('No fixes to package')
    (stage/'fixes.patch').write_bytes(patch)
    header = '''"""Standalone VPS regressions; imports the existing test fixture only."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest
import pandas as pd
from bollinger_tick_stream import TickGeometry
from live_bollinger_preview import evaluate_live_bollinger_preview
from tests.test_bollinger_tick_stream import CANDLE, seed, trade
UTC = timezone.utc

class HistoryContinuityFixTests(unittest.TestCase):
'''
    history = [method('tests/test_bollinger_tick_stream.py', name) for name in (
        'setUp', 'observe', 'test_missing_older_period_does_not_substitute_an_earlier_close',
        'test_recovered_older_period_restores_reference_without_historical_signal')]
    preview = method('tests/test_live_bollinger_preview.py',
                     'test_week_window_preserves_preview_across_session_and_candle_boundaries')
    test_text = header+'\n\n'.join(history)+'\n\nclass PreviewWindowFixTests(unittest.TestCase):\n'+preview+'\n'
    (stage/'tests/test_vps_recovery_fixes.py').write_text(test_text, encoding='utf-8')
    # Check forward application to the exact base, without touching this checkout.
    with tempfile.TemporaryDirectory(prefix='jjtrade_patch_') as directory:
        target = Path(directory)
        for name in PRODUCTION:
            (target/name).write_bytes(subprocess.check_output([str(GIT), 'show', base+':'+name], cwd=ROOT))
        subprocess.run([str(GIT), 'apply', '--check', str(stage/'fixes.patch')], cwd=target, check=True, capture_output=True)
    subprocess.run([str(GIT), 'apply', '--reverse', '--check', str(stage/'fixes.patch')], cwd=ROOT, check=True, capture_output=True)
    validation = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(stage/'tests'),
                                 '-p', 'test_vps_recovery_fixes.py', '-v'], cwd=ROOT, capture_output=True, text=True)
    (stage/'validation.txt').write_text(validation.stdout+validation.stderr, encoding='utf-8')
    if validation.returncode:
        raise ValueError('Standalone regression failed; package not finalized')
    readme = f'''# Paquete de dos correcciones VPS para revisar en la PC

Base Git VPS: {base}. PreparadoUTC:{now.isoformat()}.
No contiene bases, configuracion, claves, recibos privados ni otros cambios locales.

1. Leer AGENTS.md y continuidad en C:\\JJTradeAI. La VPS es el colector activo.
   No iniciar colector/radar/interfaces escritores de PC ni transferir bases de PC
   sobre la VPS. No copiar DPAPI ni cambiar feed/tolerancias/regla Bollinger.
2. Conservar y revisar git status/diffs de PC. Comparar hashes del manifiesto.
3. Revisar fixes.patch: solo live_strategy_service.py y bollinger_tick_stream.py.
   Acota vista previa a7dias; exige20periodos oficiales sin sustituir los ausentes.
4. Desde la raiz PC, ejecutar git apply --check RUTA\\fixes.patch. Si no coincide,
   conciliar manualmente conservando los cambios PC; no forzar ni sobrescribir.
   Aplicar solo tras revisar. Este paquete no ejecuta la aplicacion.
5. Copiar solo el nuevo tests/test_vps_recovery_fixes.py a tests/ (si ya existe,
   comparar antes). Usa seed/CANDLE/trade del test existente, que no se modifica.
6. Ejecutar venv\\Scripts\\python.exe -m unittest tests.test_vps_recovery_fixes -v
   y venv\\Scripts\\python.exe -m unittest tests.test_live_bollinger_preview
   tests.test_bollinger_tick_stream tests.test_live_strategy_service tests.test_market_store -q
   (el segundo comando en una sola linea).
7. Actualizar continuidad PC con validacion real; no habilitar avisos/ordenes.

Validacion VPS: parche aplicable a la base aislada, reverse-check en arbol actual
y3regresiones aisladas del paquete OK (validation.txt). Suite afectada63OK en
sesion anterior,33.917s; no se afirma suitecompletaVPS/PC ni aplicacion enPC.
Las tres regresiones no incluyen el cambio local previo de deduplicacion.
El parche mantiene3s yIEX; no agrega ordenes ni reenvios historicos.
'''
    (stage/'README_PC.md').write_text(readme, encoding='utf-8')
    manifest = {'base_commit': base, 'created_utc': now.isoformat(), 'production': {},
                'patch_checked_against_isolated_base': True, 'reverse_checked_current_tree': True,
                'standalone_regressions_passed': 3, 'files': {}}
    for name in PRODUCTION:
        manifest['production'][name] = {
            'base_sha256': hashlib.sha256(subprocess.check_output([str(GIT), 'show', base+':'+name], cwd=ROOT)).hexdigest(),
            'vps_sha256': hashlib.sha256((ROOT/name).read_bytes()).hexdigest()}
    allowed = ['fixes.patch', 'tests/test_vps_recovery_fixes.py', 'validation.txt', 'README_PC.md']
    for name in allowed:
        content = (stage/name).read_bytes()
        manifest['files'][name] = {'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content)}
    (stage/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    archive = stage.with_suffix('.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        for name in allowed+['manifest.json']:
            bundle.write(stage/name, arcname=name)
    with zipfile.ZipFile(archive) as bundle:
        assert sorted(bundle.namelist()) == sorted(allowed+['manifest.json'])
        assert bundle.testzip() is None
        for name in allowed:
            assert hashlib.sha256(bundle.read(name)).hexdigest() == manifest['files'][name]['sha256']
    print(json.dumps({'zip': str(archive), 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                      'bytes': archive.stat().st_size, 'files': len(allowed)+1, 'regressions': 3}))


if __name__ == '__main__':
    main()
