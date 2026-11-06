import datetime as dt
import unittest
from unittest.mock import Mock
import microcenter
import tempfile
from pathlib import Path
import urllib.error
import watcher
from unittest.mock import patch

STORE = {'id': '121', 'name': 'Cambridge'}

def page(price=2500, stock='2', memory='64GB Unified Memory', sale=True):
    return ("<script>var bloomreach_last_store_selected = '121 - Cambridge';</script>"
            '<li class="product_wrapper"><a id="hypProductH2_0" '
            f'href="/product/123/macbook" data-price="{price}">'
            f'Apple MacBook Pro M4 Max; {memory}; 1TB SSD</a>'
            f'<ul><li>nested spec</li></ul>{stock} IN STOCK at Cambridge Store '
            + ('Save $500.00' if sale else '') + '</li>')

class MicrocenterTests(unittest.TestCase):
    def test_store_failure_fails_run_even_when_feed_succeeds(self):
        config = {'microcenter': {'enabled': True, 'stores': [STORE]},
                  'feeds': [{'name': 'Working', 'url': 'https://example.com/rss'}]}
        def fetch(url):
            if 'microcenter.com' in url:
                raise urllib.error.HTTPError(url, 403, 'Forbidden', {}, None)
            return b'<rss><channel><item><title>Unrelated</title><link>https://example.com/item</link></item></channel></rss>'
        with tempfile.TemporaryDirectory() as folder, patch('watcher.fetch', side_effect=fetch):
            with self.assertRaisesRegex(RuntimeError, 'monitoring incomplete: Cambridge'):
                watcher.run(config, Path(folder) / 'state.json', dry_run=True)

    def run_check(self, text, state, send):
        microcenter.check({'microcenter': {'enabled': True, 'stores': [STORE]}},
                          state, dt.datetime.now(dt.timezone.utc),
                          lambda url: text, send, 'secret', lambda s: None)

    def test_nested_card_and_wrong_store(self):
        p = microcenter.parse_page(page(), STORE)
        self.assertEqual(p.cards[0]['price'], 2500)
        self.assertIn('64GB Unified Memory', p.cards[0]['name'])
        with self.assertRaises(ValueError):
            microcenter.parse_page(page(), {'id': '075', 'name': 'North Jersey'})

    def test_delivery_dedup_price_drop_and_failure(self):
        state, send = {}, Mock()
        self.run_check(page(), state, send)
        self.run_check(page(), state, send)
        self.assertEqual(send.call_count, 1)
        self.run_check(page(price=2400), state, send)
        self.assertEqual(send.call_count, 2)
        send.side_effect = RuntimeError('delivery failed')
        with self.assertRaises(RuntimeError):
            self.run_check(page(price=2300), state, send)
        self.assertNotIn(2300, state['microcenter']['121:123']['alerted_prices'])

    def test_no_alert_for_wrong_ram_sold_out_or_regular_price(self):
        for text in [page(memory='128GB Unified Memory'), page(stock='0'),
                     page(price=4000, sale=False)]:
            send = Mock()
            self.run_check(text, {}, send)
            send.assert_not_called()
