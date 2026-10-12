"""Supervisor del servidor continuo: colector, Bollinger, estudio y API privada."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    required = ("ALPACA_API_KEY", "ALPACA_API_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "JJTRADE_BACKEND_KEY")
    if any(not os.environ.get(name) for name in required):
        raise SystemExit("Faltan variables privadas del servidor. Revisa deployment/.env.example.")
    if len(os.environ["JJTRADE_BACKEND_KEY"]) < 32:
        raise SystemExit("JJTRADE_BACKEND_KEY debe tener al menos 32 caracteres.")
    commands = {
        "datos": [sys.executable, "live_strategy_service.py", "--data-only", "--days", "30"],
        "bollinger": [sys.executable, "bollinger_phone_worker.py"],
        "estudio": [sys.executable, "bollinger_strategy_study.py", "--watch"],
        "api": [sys.executable, "cloud_snapshot_api.py"],
    }
    stopping = False
    processes, restart_at = {}, {}
    def stop(*args):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping:
            for name, command in commands.items():
                process = processes.get(name)
                if process and process.poll() is not None:
                    print(f"Servicio {name} detenido; reintento en 30 segundos.", flush=True)
                    restart_at[name] = time.monotonic()+30
                    processes.pop(name)
                if name not in processes and time.monotonic() >= restart_at.get(name, 0):
                    processes[name] = subprocess.Popen(command, cwd=ROOT)
                    print(f"Servicio {name} iniciado.", flush=True)
            time.sleep(1)
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
        for process in processes.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == "__main__":
    main()
