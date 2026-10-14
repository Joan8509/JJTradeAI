"""Adaptador de solo lectura para datos históricos de Alpaca Market Data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from data_providers import DataBundle, DataProviderKind, prepare_market_frame
from stock_instruments import STOCK_INSTRUMENTS
from live_market import (
    MarketBar,
    NoMarketDataError,
    aggregate_minute_bars,
    normalize_minute_bars,
    retain_closed_aggregates,
)


ALPACA_DATA_URL = "https://data.alpaca.markets"
ALPACA_STOCK_STREAM_URL = "wss://stream.data.alpaca.markets/v2/{feed}"


@dataclass(frozen=True)
class AlpacaMarketConfig:
    """Configuración segura; las credenciales nunca forman parte del reporte."""

    api_key: str
    api_secret: str
    feed: str = "iex"
    base_url: str = ALPACA_DATA_URL

    @classmethod
    def from_env(cls) -> "AlpacaMarketConfig":
        key = os.environ.get("ALPACA_API_KEY", "").strip()
        secret = os.environ.get("ALPACA_API_SECRET", "").strip()
        if not key or not secret:
            raise ValueError(
                "Configura ALPACA_API_KEY y ALPACA_API_SECRET para usar datos en vivo."
            )
        return cls(key, secret, os.environ.get("ALPACA_DATA_FEED", "iex").strip())

    def __post_init__(self) -> None:
        if self.feed not in {"iex", "sip", "delayed_sip"}:
            raise ValueError("ALPACA_DATA_FEED debe ser iex, sip o delayed_sip.")

    @property
    def stock_stream_url(self) -> str:
        return ALPACA_STOCK_STREAM_URL.format(feed=self.feed)


Transport = Callable[[Request], dict[str, Any]]


def _default_transport(request: Request) -> dict[str, Any]:
    with urlopen(request, timeout=30) as response:  # noqa: S310 - URL configurable explícitamente
        return json.loads(response.read().decode("utf-8"))


class AlpacaMarketDataProvider:
    """Descarga barras de un minuto y crea los marcos usados por JJTradeAI."""

    def __init__(
        self,
        config: AlpacaMarketConfig,
        *,
        transport: Transport = _default_transport,
    ) -> None:
        self.config = config
        self._transport = transport

    def fetch_minute_bars(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        symbol = symbol.strip().upper()
        if not symbol:
            raise ValueError("El símbolo no puede estar vacío.")
        history_start = STOCK_INSTRUMENTS.get(symbol, {}).get('history_start')
        if history_start is not None:
            start = max(start, history_start)
            if end < start:
                raise NoMarketDataError(f"No hay historial de este instrumento para {symbol} antes de su inicio de cotización.")
        rows: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params = {
                "timeframe": "1Min",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "limit": 10000,
                "adjustment": "all",
                "feed": self.config.feed,
            }
            if page_token:
                params["page_token"] = page_token
            request = Request(
                f"{self.config.base_url}/v2/stocks/{symbol}/bars?{urlencode(params)}",
                headers={
                    "APCA-API-KEY-ID": self.config.api_key,
                    "APCA-API-SECRET-KEY": self.config.api_secret,
                    "Accept": "application/json",
                },
            )
            payload = self._transport(request)
            rows.extend(payload.get("bars") or [])
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        if not rows:
            raise NoMarketDataError(f"Alpaca no devolvió barras para {symbol}.")
        frame = pd.DataFrame(
            {
                "date": [row["t"] for row in rows],
                "open": [row["o"] for row in rows],
                "high": [row["h"] for row in rows],
                "low": [row["l"] for row in rows],
                "close": [row["c"] for row in rows],
                "volume": [row["v"] for row in rows],
            }
        )
        frame = normalize_minute_bars(frame)
        if history_start is not None:
            # Defend against an upstream response including the prior issuer.
            frame = frame.loc[frame.date >= history_start].reset_index(drop=True)
            if frame.empty:
                raise NoMarketDataError(f"Alpaca no devolvió barras de la identidad actual de {symbol}.")
        return frame

    def fetch_bundle(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
    ) -> DataBundle:
        minute_bars = self.fetch_minute_bars(symbol, start=start, end=end)
        return build_alpaca_data_bundle(
            minute_bars, symbol=symbol, feed=self.config.feed
        )


def _add_methodology_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Calcula columnas disponibles y marca Worden como no disponible."""
    result = frame.copy()
    for period in (20, 40, 100, 200):
        result[f"moving_average_{period}"] = result["close"].rolling(period).mean()
    result["worden_stochastics"] = float("nan")
    return result


def build_alpaca_data_bundle(
    minute_bars: pd.DataFrame,
    *,
    symbol: str,
    feed: str,
    session_closes: Mapping[object, datetime] | None = None,
) -> DataBundle:
    """Convierte el historial persistido al contrato multitemporal del motor."""
    normalized = normalize_minute_bars(minute_bars)
    latest_source = normalized.iloc[-1]["date"].to_pydatetime()
    datasets = {}
    for timeframe in ("15m", "1H", "1D"):
        aggregated = aggregate_minute_bars(normalized, timeframe)
        closed = retain_closed_aggregates(
            aggregated,
            timeframe,
            latest_source_timestamp=latest_source,
            session_closes=session_closes,
        )
        datasets[timeframe] = prepare_market_frame(_add_methodology_columns(closed))
    closed_through = {
        timeframe: frame.iloc[-1]["date"].isoformat()
        for timeframe, frame in datasets.items()
        if not frame.empty
    }
    return DataBundle(
        provider=DataProviderKind.MARKET_DATA_API,
        datasets=datasets,
        auxiliary_datasets={"1m": normalized.copy()},
        metadata={
            "timeframes": tuple(datasets),
            "vendor": "ALPACA",
            "symbol": symbol.strip().upper(),
            "feed": feed,
            "closed_through": closed_through,
        },
    )


def build_alpaca_live_preview_bundle(
    minute_bars: pd.DataFrame, *, symbol: str, feed: str
) -> DataBundle:
    """Construye temporalidades incluyendo su ultima vela todavia abierta."""
    normalized = normalize_minute_bars(minute_bars)
    datasets = {
        timeframe: prepare_market_frame(
            _add_methodology_columns(aggregate_minute_bars(normalized, timeframe))
        )
        for timeframe in ("15m", "1H", "1D")
    }
    return DataBundle(
        provider=DataProviderKind.MARKET_DATA_API,
        datasets=datasets,
        auxiliary_datasets={"1m": normalized.copy()},
        metadata={
            "timeframes": tuple(datasets), "vendor": "ALPACA",
            "symbol": symbol.strip().upper(), "feed": feed,
            "freshness_approved": True, "provisional": True,
        },
    )


def alpaca_messages_to_bars(messages: Iterable[dict[str, Any]]) -> tuple[MarketBar, ...]:
    """Convierte únicamente eventos de barra Alpaca al modelo canónico."""
    bars = []
    for message in messages:
        if message.get("T") not in {"b", "u"}:
            continue
        bars.append(
            MarketBar(
                symbol=str(message["S"]),
                timestamp=pd.Timestamp(message["t"]).to_pydatetime(),
                open=float(message["o"]),
                high=float(message["h"]),
                low=float(message["l"]),
                close=float(message["c"]),
                volume=float(message["v"]),
            )
        )
    return tuple(bars)


class AlpacaStockBarStream:
    """Cliente WebSocket mínimo para barras cerradas de un minuto."""

    def __init__(self, config: AlpacaMarketConfig, *, on_trade_message=None) -> None:
        self.config = config
        self._socket: Any = None
        self.on_trade_message = on_trade_message

    def run(
        self,
        symbols: Iterable[str],
        on_bar: Callable[[MarketBar], None],
        *,
        on_error: Callable[[Exception], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        """Mantiene el stream hasta que ``stop`` cierre la conexión."""
        try:
            import websocket
        except ImportError as error:
            raise RuntimeError(
                "Instala las dependencias del proyecto para habilitar WebSocket."
            ) from error

        normalized_symbols = sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()})
        if not normalized_symbols:
            raise ValueError("Debe indicarse al menos un símbolo para el stream.")

        def send(socket: Any, payload: dict[str, Any]) -> None:
            socket.send(json.dumps(payload))

        def handle_open(socket: Any) -> None:
            send(socket, {"action": "auth", "key": self.config.api_key, "secret": self.config.api_secret})

        subscribed = False

        def handle_message(socket: Any, raw_message: str) -> None:
            nonlocal subscribed
            messages = json.loads(raw_message)
            if not isinstance(messages, list):
                messages = [messages]
            if not subscribed and any(
                item.get("T") == "success" and item.get("msg") == "authenticated"
                for item in messages
            ):
                subscription = {
                        "action": "subscribe",
                        "bars": normalized_symbols,
                        "updatedBars": normalized_symbols,
                    }
                if self.on_trade_message is not None:
                    subscription["trades"] = normalized_symbols
                send(socket, subscription)
                subscribed = True
                if on_status and self.on_trade_message is None:
                    on_status("CONECTADO")
            for item in messages:
                if item.get("T") == "subscription" and self.on_trade_message is not None:
                    if set(normalized_symbols).issubset(item.get('trades', [])) and on_status:
                        on_status("CONECTADO")
                if item.get("T") == "error":
                    if on_error:
                        on_error(RuntimeError(f"Alpaca stream error {item.get('code')}: {item.get('msg')}"))
                    socket.close()
                    return
                if self.on_trade_message is not None and item.get("T") in ("t", "c", "x"):
                    try:
                        self.on_trade_message(item)
                    except Exception as error:
                        if on_error:
                            on_error(error)
                        socket.close()
                        return
            for bar in alpaca_messages_to_bars(messages):
                try:
                    on_bar(bar)
                except Exception as error:
                    if on_error:
                        on_error(error)
                    socket.close()
                    return

        def handle_error(_socket: Any, error: Any) -> None:
            if on_error:
                on_error(error if isinstance(error, Exception) else RuntimeError(str(error)))

        def handle_close(_socket: Any, _code: Any, _message: Any) -> None:
            if on_status:
                on_status("DESCONECTADO")

        self._socket = websocket.WebSocketApp(
            self.config.stock_stream_url,
            on_open=handle_open,
            on_message=handle_message,
            on_error=handle_error,
            on_close=handle_close,
        )
        self._socket.run_forever(ping_interval=20, ping_timeout=10)

    def stop(self) -> None:
        """Cierra el stream activo de forma idempotente."""
        if self._socket is not None:
            self._socket.close()
