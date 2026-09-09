"""Pruebas del contexto reciente de noticias."""

from datetime import datetime, timezone
import unittest

from alpaca_market_data import AlpacaMarketConfig
from news_context import AlpacaNewsProvider, build_news_context


END = datetime(2026, 7, 21, 15, 0, tzinfo=timezone.utc)


class NewsContextTests(unittest.TestCase):
    def test_fetches_symbol_news_without_content(self) -> None:
        requests = []
        def transport(request):
            requests.append(request)
            return {"news": [{"id": 7, "headline": "Earnings update", "source": "benzinga", "created_at": "2026-07-21T14:00:00Z", "updated_at": "2026-07-21T14:01:00Z", "url": "https://example.com/7", "symbols": ["AAPL"]}], "next_page_token": None}
        provider = AlpacaNewsProvider(
            AlpacaMarketConfig("key", "secret"), transport=transport
        )

        result = build_news_context(provider, "aapl", as_of=END)

        self.assertEqual(result["status"], "REQUIERE_REVISION")
        self.assertEqual(result["article_count"], 1)
        self.assertIn("symbols=AAPL", requests[0].full_url)
        self.assertIn("include_content=false", requests[0].full_url)
        self.assertNotIn("secret", requests[0].full_url)

    def test_no_articles_does_not_approve_news_gate(self) -> None:
        provider = AlpacaNewsProvider(
            AlpacaMarketConfig("key", "secret"),
            transport=lambda request: {"news": [], "next_page_token": None},
        )

        result = build_news_context(provider, "SPY", as_of=END)

        self.assertEqual(result["status"], "REQUIERE_REVISION")
        self.assertEqual(result["article_count"], 0)


if __name__ == "__main__":
    unittest.main()
