"""Diagnóstico de solo lectura para verificar la conexión con Alpaca."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from alpaca_market_data import AlpacaMarketConfig, AlpacaMarketDataProvider, AlpacaStockBarStream
from market_store import DEFAULT_MARKET_DATABASE, MarketBarStore, MarketContinuityService
from safe_diagnostics import sanitize_diagnostic_detail


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="SPY", help="Símbolo estadounidense.")
    parser.add_argument("--days", type=int, default=5, help="Días naturales de historial.")
    parser.add_argument("--stream", action="store_true", help="Mostrar cada barra cerrada de un minuto.")
    parser.add_argument(
        "--database",
        default=str(DEFAULT_MARKET_DATABASE),
        help="SQLite local donde se conservan las barras.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.days <= 0:
        raise SystemExit("--days debe ser mayor que cero.")
    config = AlpacaMarketConfig.from_env()
    symbol = args.symbol.strip().upper()
    store = MarketBarStore(args.database)
    if args.stream:
        print(f"Conectando a Alpaca {config.feed} para {symbol}. Ctrl+C para salir.")
        stream = AlpacaStockBarStream(config)

        continuity = MarketContinuityService(
            store,
            AlpacaMarketDataProvider(config),
            provider_name="ALPACA",
            feed=config.feed,
        )

        def persist_and_print(bar):
            ingestion = continuity.ingest_live_bar(bar)
            event = " CIERRE_15M" if ingestion.closes_15m else ""
            print(
                f"{bar.timestamp.isoformat()} {bar.symbol} O={bar.open} "
                f"H={bar.high} L={bar.low} C={bar.close} V={bar.volume}{event}"
            )

        try:
            stream.run(
                [symbol],
                persist_and_print,
                on_error=lambda error: print(
                    "Error del stream: " + sanitize_diagnostic_detail(error)
                ),
            )
        except KeyboardInterrupt:
            stream.stop()
        return 0

    end = datetime.now(timezone.utc)
    provider = AlpacaMarketDataProvider(config)
    continuity = MarketContinuityService(
        store, provider, provider_name="ALPACA", feed=config.feed
    )
    inserted = continuity.recover(
        symbol, end=end, initial_lookback=timedelta(days=args.days)
    )
    frame = store.load_frame(symbol=symbol, provider="ALPACA", feed=config.feed)
    gaps = continuity.gaps(symbol)
    print(f"Proveedor=ALPACA feed={config.feed} símbolo={symbol}")
    print(f"Recuperadas={inserted} almacenadas={len(frame)} huecos_internos={len(gaps)}")
    if not frame.empty:
        latest = frame.iloc[-1]
        print(f"Última={latest['date']} cierre={latest['close']} volumen={latest['volume']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
