# Preparacion de la proxima jornada

La lista configurada contiene AAPL, NVDA, TSLA, AMD, META, MSFT, BABA, SPY,
QQQ, IWM, DIA, MU, NIO, GLD, AMZN y NFLX. Los indices SPY, QQQ, IWM y DIA se
usan tambien como contexto de mercado, sin duplicar suscripciones.

## Precarga previa

Ejecutar una vez antes de la apertura, preferiblemente el dia anterior:

```powershell
.\scripts\prepare_next_market_day.ps1 -Feed iex
```

El proceso solicita API Key y Secret de Alpaca, completa el historial local y
termina automaticamente. Las credenciales solo existen en el entorno temporal
del proceso.

## Jornada PAPER

Ejecutar aproximadamente a las 9:15 AM ET:

```powershell
.\scripts\run_market_day.ps1 -Feed iex
```

El scanner queda preparado antes de la apertura de las 9:30 AM ET y se detiene
automaticamente despues de 420 minutos. Puede detenerse antes, desde otra
terminal, con:

```powershell
.\venv\Scripts\python.exe scanner_control.py stop
```

