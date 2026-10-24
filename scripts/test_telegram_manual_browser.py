"""Headless Edge against fully synthetic HTML/fetch, no live bot/API/profile."""
from datetime import datetime,timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
EDGE=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')


def main():
    evidence=ROOT/'exports/trade_review/telegram_manual_browser'
    evidence.mkdir(parents=True,exist_ok=True)
    html=(ROOT/'web/telegram_manual/index.html').read_text(encoding='utf-8')
    html=re.sub(r'<script\b.*?</script>','',html,flags=re.S)
    html=re.sub(r'<link\b[^>]*>','',html)
    harness=(ROOT/'tests/telegram_manual_browser_harness.js').read_text(encoding='utf-8')
    source=(ROOT/'web/telegram_manual/app.js').read_text(encoding='utf-8')
    results=[]
    modes=('signed','signed_unknown_fees','unauthenticated','watch','watch_unauthenticated',
                 'entry','entry_otm5','entry_blocked','entry_uncertain','entry_unauthenticated',
                 'entry_recovery','entry_retry','entry_expired','entry_safe_receipt','entry_alert','entry_contract_rejected',
                 'entry_input_sequence','entry_selection_order','entry_alert_expired','entry_crypto_failure','entry_auto_pin','entry_restored','entry_refresh_failure','entry_observed_itm','entry_chain')
    requested=sys.argv[1:]
    if any(mode not in modes for mode in requested):raise ValueError('UNKNOWN_SYNTHETIC_MODE')
    for mode in requested or modes:
        with tempfile.TemporaryDirectory(prefix='jjtrade_miniapp_browser_') as directory:
            folder=Path(directory)
            script=('window.unauth='+('true' if mode.endswith('unauthenticated') else 'false')+
                ';window.entryOtm5='+('true' if mode=='entry_otm5' else 'false')+
                ';window.entryAutoPin='+('true' if mode=='entry_auto_pin' else 'false')+
                ';window.entryRestored='+('true' if mode=='entry_restored' else 'false')+
                ';window.entryRefreshFailure='+('true' if mode=='entry_refresh_failure' else 'false')+
                ';window.entryObservedItm='+('true' if mode=='entry_observed_itm' else 'false')+
                ';window.entryChain='+('true' if mode=='entry_chain' else 'false')+
                ';window.entryView='+('true' if mode.startswith('entry') else 'false')+
                ';window.entryBlocked='+('true' if mode in ('entry_blocked','entry_alert') else 'false')+
                ';window.entryAlert='+('true' if mode=='entry_alert' else 'false')+
                ';window.entryContractRejected='+('true' if mode in ('entry_contract_rejected','entry_observed_itm') else 'false')+
                ';window.entryInputSequence='+('true' if mode=='entry_input_sequence' else 'false')+
                ';window.entrySelectionOrder='+('true' if mode=='entry_selection_order' else 'false')+
                ';window.entryAlertExpired='+('true' if mode=='entry_alert_expired' else 'false')+
                ';window.entryCryptoFailure='+('true' if mode=='entry_crypto_failure' else 'false')+
                ';window.entryUncertain='+('true' if mode=='entry_uncertain' else 'false')+
                ';window.entryRecovery='+('true' if mode=='entry_recovery' else 'false')+
                ';window.entryRetry='+('true' if mode=='entry_retry' else 'false')+
                ';window.entryExpired='+('true' if mode=='entry_expired' else 'false')+
                ';window.entryReceipt='+('true' if mode=='entry_safe_receipt' else 'false')+
                ';window.watchView='+('true' if mode.startswith('watch') else 'false')+
                ';window.unknownFees='+('true' if mode=='signed_unknown_fees' else 'false')+';'+harness)
            script+='\n'+source+'\nrunChecks();'
            page=html.replace('</body>','<pre id="test-results"></pre><script>'+script+'</script></body>')
            path=folder/'test.html';path.write_text(page,encoding='utf-8')
            run=subprocess.run([str(EDGE),'--headless=new','--disable-gpu','--no-first-run',
                '--disable-background-networking','--disable-extensions','--no-default-browser-check',
                '--user-data-dir='+str(folder/'profile'),'--dump-dom','--virtual-time-budget=3000',
                path.as_uri()+('#entry=AMZN&side=CALL&candle=2026-10-16T14%3A00%3A00%2B00%3A00' if mode.startswith('entry')
                    else '#watch=AMZN&side=CALL&candle=2026-10-16T14%3A00%3A00%2B00%3A00' if mode.startswith('watch')
                    else '#intent=synthetic_intent')],capture_output=True,timeout=40)
            dom=run.stdout.decode('utf-8',errors='replace')
            ok='data-test-result="PASS"' in dom
            match=re.search(r'<pre id="test-results">(.*?)</pre>',dom,re.S)
            result=dict(mode=mode,passed=ok,returncode=run.returncode,
                checks=match.group(1) if match else 'BROWSER_RESULT_MISSING')
            results.append(result)
            print(json.dumps(dict(mode=mode,passed=ok,returncode=run.returncode)),flush=True)
            if not ok:(evidence/(mode+'.diagnostic.txt')).write_text(dom+run.stderr.decode('utf-8',errors='replace'),encoding='utf-8')
    (evidence/'result.json').write_text(json.dumps(dict(checked_utc=datetime.now(timezone.utc).isoformat(),
        synthetic_only=True,results=results),indent=2),encoding='utf-8')
    print(json.dumps(dict(modes=len(results),all_passed=all(r['passed'] for r in results))))
    return 0 if all(r['passed'] for r in results) else 2


if __name__=='__main__':raise SystemExit(main())
