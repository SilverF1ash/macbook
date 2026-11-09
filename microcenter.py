"""Read public Micro Center listings; never bypass access challenges."""
import datetime as dt
from html.parser import HTMLParser
import logging
import re
import time
from urllib.parse import urlencode

LOG = logging.getLogger('watcher')

class Listings(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cards = []
        self.pages = {1}
        self.depth = 0
        self.card = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'a':
            match = re.search(r'[?&]st-page=(\d+)', a.get('href', ''))
            if match:
                self.pages.add(int(match[1]))
        if tag == 'li':
            if self.depth:
                self.depth += 1
            elif 'product_wrapper' in a.get('class', '').split():
                self.depth = 1
                self.card = {'text': [], 'name': '', 'url': '', 'price': None}
        if self.depth and tag == 'a':
            if a.get('id', '').startswith('hypProductH2_'):
                self.card['url'] = a.get('href', '')
                try:
                    self.card['price'] = float(a.get('data-price', ''))
                except ValueError:
                    pass
                self.in_title = True

    def handle_data(self, data):
        if self.depth:
            self.card['text'].append(data)
            if getattr(self, 'in_title', False):
                self.card['name'] += data

    def handle_endtag(self, tag):
        if tag == 'a':
            self.in_title = False
        if tag == 'li' and self.depth:
            self.depth -= 1
            if not self.depth:
                self.card['text'] = ' '.join(' '.join(self.card['text']).split())
                self.cards.append(self.card)

def parse_page(data, store):
    text = data.decode('utf-8', errors='replace') if isinstance(data, bytes) else data
    selected = re.search(r"bloomreach_last_store_selected\s*=\s*'([^']+)'", text)
    if not selected or selected[1] != store['id'] + ' - ' + store['name']:
        raise ValueError('Micro Center store selection could not be verified')
    parser = Listings()
    parser.feed(text)
    if not parser.cards:
        raise ValueError('Micro Center returned no product cards; check access or page format')
    return parser

def check(config, state, now, fetch, send, webhook, save, dry_run=False, initialize=False):
    settings = config.get('microcenter', {})
    if not settings.get('enabled'):
        return 0
    records = state.setdefault('microcenter', {})
    health = state.setdefault('microcenter_health', {})
    successful = 0
    for store in settings['stores']:
        try:
            cards = []
            page, last = 1, 1
            while page <= last:
                url = 'https://www.microcenter.com/search/search_results.aspx?' + urlencode(
                    {'Ntt': 'macbook 64gb', 'storeid': store['id'], 'st-page': page})
                parser = parse_page(fetch(url), store)
                cards.extend(parser.cards)
                last = max(last, max(parser.pages))
                if last > 15:
                    raise ValueError('Micro Center pagination exceeds safety limit; review search')
                page += 1
                if page <= last:
                    time.sleep(1)
        except Exception as exc:
            reason = 'HTTP ' + str(exc.code) if hasattr(exc, 'code') else type(exc).__name__
            health[store['id']] = {'store': store['name'], 'ok': False,
                                   'error': reason, 'checked_at': now.isoformat()}
            LOG.warning('Micro Center %s unavailable (%s); monitoring incomplete', store['name'], reason)
            if not dry_run:
                save(state)
            continue
        health[store['id']] = {'store': store['name'], 'ok': True, 'checked_at': now.isoformat()}
        if not dry_run:
            save(state)
        successful += 1
        matched = 0
        for card in cards:
            name, text, price = card['name'], card['text'], card['price']
            if store.get('model_skus') and not any(sku.lower() in name.lower() for sku in store['model_skus']):
                continue
            if not re.search(r'mac\s*book\s*pro', name, re.I):
                continue
            if not re.search(r'\b64\s*GB\s+(?:Unified\s+)?(?:Memory|RAM)\b', name, re.I):
                continue
            if re.search(r'\b(refurb\w*|renewed|used|pre[- ]?owned|open[- ]?box)\b', name, re.I):
                continue
            if config.get('chips') and not any(re.search(r'\b' + re.escape(c) + r'\b', name, re.I) for c in config['chips']):
                continue
            stock = re.search(r'(\d+\+?)\s+IN STOCK\s+at\s+' + re.escape(store['name']) + r'\s+Store', text, re.I)
            if not stock or int(stock[1].rstrip('+')) == 0 or price is None or price < 500:
                continue
            if not re.match(r'^/product/\d+/', card['url']):
                continue
            matched += 1
            key = store['id'] + ':' + re.search(r'/product/(\d+)/', card['url'])[1]
            previous = records.get(key, {})
            discounted = bool(re.search(r'Save\s+\$\s*[1-9]', text, re.I))
            dropped = previous.get('price') is not None and price < previous['price']
            qualifies = discounted or price <= config.get('target_price_usd', 3000) or dropped
            cap = config.get('max_price_usd')
            qualifies = qualifies and (cap is None or price <= cap)
            alerted = previous.get('alerted_prices', [])
            if initialize and qualifies and price not in alerted:
                alerted = alerted + [price]
            if qualifies and price not in alerted and not initialize:
                badge = 'WITHIN YOUR TARGET' if price <= config.get('target_price_usd', 3000) else 'MICRO CENTER DEAL LEAD'
                link = 'https://www.microcenter.com' + card['url'] + '?storeid=' + store['id']
                message = (f'**{badge} — {store["name"]}**\n{name}\n'
                           f'Listed price: **${price:,.2f}** | {stock[1]} in stock\n{link}\n'
                           'Public new-product listing; confirm price, stock, configuration and AppleCare with the store.')
                if dry_run:
                    print(message + '\n')
                else:
                    send(webhook, message)
                    alerted = alerted + [price]
            records[key] = {'price': price, 'alerted_prices': alerted, 'checked_at': now.isoformat()}
            if not dry_run:
                save(state)
        LOG.info('Micro Center %s: %d product cards, %d in-stock 64GB MacBook Pro listings', store['name'], len(cards), matched)
    return successful
