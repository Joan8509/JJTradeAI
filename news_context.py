"""Noticias recientes normalizadas para revisión humana del panorama."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request

from alpaca_market_data import AlpacaMarketConfig, Transport, _default_transport


@dataclass(frozen=True)
class NewsItem:
    article_id: int
    headline: str
    source: str
    created_at: str
    updated_at: str
    url: str
    symbols: tuple[str, ...]


class AlpacaNewsProvider:
    def __init__(self, config: AlpacaMarketConfig, *, transport: Transport = _default_transport) -> None:
        self.config = config
        self._transport = transport

    def fetch_recent(self, symbol: str, *, end: datetime, lookback: timedelta = timedelta(hours=24), max_articles: int = 20) -> tuple[NewsItem, ...]:
        if end.tzinfo is None or lookback.total_seconds() <= 0 or max_articles <= 0:
            raise ValueError("Rango de noticias inválido.")
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("El símbolo de noticias es obligatorio.")
        items = []
        token = None
        while len(items) < max_articles:
            params: dict[str, Any] = {
                "symbols": normalized,
                "start": (end - lookback).isoformat(),
                "end": end.isoformat(),
                "sort": "desc",
                "limit": min(50, max_articles - len(items)),
                "include_content": "false",
            }
            if token:
                params["page_token"] = token
            request = Request(
                f"{self.config.base_url}/v1beta1/news?{urlencode(params)}",
                headers={"APCA-API-KEY-ID": self.config.api_key, "APCA-API-SECRET-KEY": self.config.api_secret, "Accept": "application/json"},
            )
            payload = self._transport(request)
            articles = payload.get("news") or []
            items.extend(_parse_article(item) for item in articles)
            token = payload.get("next_page_token")
            if not token or not articles:
                break
        return tuple(items[:max_articles])


def build_news_context(provider: AlpacaNewsProvider, symbol: str, *, as_of: datetime) -> dict:
    items = provider.fetch_recent(symbol, end=as_of)
    return {
        "status": "REQUIERE_REVISION",
        "article_count": len(items),
        "reason": "Titulares descriptivos; impacto e invalidación requieren revisión humana.",
        "articles": [item.__dict__ for item in items],
    }


def _parse_article(item: Any) -> NewsItem:
    if not isinstance(item, dict):
        raise ValueError("Artículo de noticias inválido.")
    return NewsItem(
        article_id=int(item["id"]),
        headline=str(item.get("headline") or ""),
        source=str(item.get("source") or ""),
        created_at=str(item.get("created_at") or ""),
        updated_at=str(item.get("updated_at") or ""),
        url=str(item.get("url") or ""),
        symbols=tuple(str(value).upper() for value in item.get("symbols") or ()),
    )
