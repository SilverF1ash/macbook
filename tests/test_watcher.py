import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import watcher

class WatcherTests(unittest.TestCase):
    def test_filters(self):
        cfg = {'allow_used': False}
        self.assertTrue(watcher.eligible('New MacBook Pro M5 Pro 64GB 1TB $2,899', cfg))
        self.assertTrue(watcher.eligible('Save $300 on MacBook Pro with 64 GB RAM', cfg))
        for title in ['MacBook Pro 48GB $2500', '64GB memory card deal', 'Refurbished MacBook Pro 64GB $2000', 'MacBook Pro 64GB open-box sale']:
            self.assertFalse(watcher.eligible(title, cfg), title)
    def test_prices(self):
        self.assertEqual(watcher.advertised_price('MacBook Pro 64GB $2,899.99'), 2899.99)
        self.assertIsNone(watcher.advertised_price('Save $600 on MacBook Pro 64GB'))
        self.assertIsNone(watcher.advertised_price('MacBook Pro 64GB was $3999 now $2999'))
    def test_atom(self):
        data = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>MacBook Pro 64GB sale</title><link href="https://example.com/deal"/><updated>2026-11-06T10:00:00Z</updated></entry></feed>'
        self.assertEqual(list(watcher.parse_feed(data))[0]['url'], 'https://example.com/deal')
    def test_dedup_and_failed_delivery(self):
        feed = b'<rss><channel><item><title>MacBook Pro 64GB $2899</title><link>https://example.com/deal</link></item></channel></rss>'
        cfg = {'feeds': [{'name': 'Fixture', 'url': 'https://example.com/rss'}]}
        with tempfile.TemporaryDirectory() as d, patch.dict('os.environ', {'DISCORD_WEBHOOK_URL':'secret'}), patch('watcher.fetch', return_value=feed), patch('watcher.time.sleep'):
            path = Path(d) / 'seen.json'
            with patch('watcher.send', side_effect=RuntimeError('failed')):
                with self.assertRaises(RuntimeError):
                    watcher.run(cfg, path)
            self.assertFalse(path.exists())
            with patch('watcher.send') as send:
                watcher.run(cfg, path)
                watcher.run(cfg, path)
                self.assertEqual(send.call_count, 1)
    def test_all_feeds_failed(self):
        with tempfile.TemporaryDirectory() as d, patch('watcher.fetch', side_effect=OSError()):
            with self.assertRaises(RuntimeError):
                watcher.run({'feeds':[{'name':'Bad','url':'https://example.com'}]}, Path(d)/'state', dry_run=True)

if __name__ == '__main__':
    unittest.main()
