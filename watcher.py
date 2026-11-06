#!/usr/bin/env python3
"""64 GB MacBook Pro deal-feed watcher. Python 3.11+, standard library only."""
import argparse
import datetime as dt
import email.utils
import hashlib
import html
import json
import logging
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

LOG = logging.getLogger('watcher')
UA = 'MacBookDealWatcher/1.0 (personal RSS reader)'

def plain(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', value or ''))).strip()

def eligible(title, config):
    # Match title only: article bodies often mention unrelated configurations.
    t = plain(title).lower()
    if not re.search(r'mac\s*book\s*pro', t) or not re.search(r'\b64\s*[- ]?\s*g(?:b|igabytes?)\b', t):
        return False
    if not config.get('allow_used', False) and re.search(r'\b(refurb\w*|renewed|used|pre[- ]?owned|open[- ]?box)\b', t):
        return False
    if config.get('chips') and not any(re.search(r'\b' + re.escape(chip.lower()) + r'\b', t) for chip in config['chips']):
        return False
    return bool(re.search(r'\$\s*\d|\b(deal\w*|sale|save|saving\w*|discount\w*|off|low|clearance|drops?)\b', t))

def advertised_price(title):
    # Avoid interpreting "$300 off" as a $300 laptop. Do not infer from article body.
    values = []
    for m in re.finditer(r'\$\s*(\d[\d,]*(?:\.\d{1,2})?)', plain(title)):
        if re.search(r'\b(?:save|saving|savings|discount(?:ed)?(?: by)?)\s*$', plain(title)[:m.start()], re.I) or re.match(r'\s*(?:off|discount|saving)', plain(title)[m.end():], re.I):
            continue
        amount = float(m.group(1).replace(',', ''))
        if amount >= 500:
            values.append(amount)
    return min(values) if len(values) == 1 else None

def parse_feed(data):
    root = ET.fromstring(data)
    atom = '{http://www.w3.org/2005/Atom}'
    entries = root.findall('./channel/item') + root.findall(atom + 'entry')
    for e in entries:
        title = e.findtext('title') or e.findtext(atom + 'title') or ''
        link = e.findtext('link') or ''
        if not link:
            for node in e.findall(atom + 'link'):
                if node.get('rel', 'alternate') == 'alternate':
                    link = node.get('href', '')
                    break
        raw_date = e.findtext('pubDate') or e.findtext(atom + 'published') or e.findtext(atom + 'updated')
        published = None
        if raw_date:
            try:
                published = email.utils.parsedate_to_datetime(raw_date)
            except (ValueError, TypeError):
                try:
                    published = dt.datetime.fromisoformat(raw_date.replace('Z', '+00:00'))
                except ValueError:
                    pass
        if published and published.tzinfo is None:
            published = published.replace(tzinfo=dt.timezone.utc)
        if urllib.parse.urlsplit(link).scheme in ('https', 'http'):
            yield {'title': plain(title), 'url': link, 'published': published}

def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=25) as r:
        data = r.read(5_000_001)
    if len(data) > 5_000_000:
        raise ValueError('feed exceeds 5 MB')
    return data

def send(webhook, message):
    p = urllib.parse.urlsplit(webhook)
    if p.scheme != 'https' or p.hostname != 'discord.com' or not re.fullmatch(r'/api(?:/v\d+)?/webhooks/\d+/[A-Za-z0-9_-]+', p.path):
        raise ValueError('Set a valid https://discord.com/api/webhooks/... URL')
    query = dict(urllib.parse.parse_qsl(p.query))
    query['wait'] = 'true'
    url = urllib.parse.urlunsplit(p._replace(query=urllib.parse.urlencode(query)))
    body = json.dumps({'username': '64GB MacBook Deals', 'content': message[:1950], 'allowed_mentions': {'parse': []}}).encode()
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json', 'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=25) as r:
                r.read()
            return
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 3:
                raise RuntimeError(f'Discord HTTP {e.code}') from None
            retry = json.loads(e.read()).get('retry_after', 5)
            time.sleep(min(max(float(retry), 1), 45))
        except urllib.error.URLError:
            # Never log the webhook URL/token or retry uncertain delivery blindly.
            raise RuntimeError('Discord connection failed; delivery not confirmed') from None

def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(path)

def run(config, state_path, dry_run=False, initialize=False):
    state = json.loads(state_path.read_text()) if state_path.exists() else {'seen': {}}
    seen = state['seen']
    successful = 0
    now = dt.datetime.now(dt.timezone.utc)
    webhook = os.getenv('DISCORD_WEBHOOK_URL', '')
    if not dry_run and not initialize and not webhook:
        raise ValueError('DISCORD_WEBHOOK_URL is required; use --dry-run to preview')
    from microcenter import check as check_microcenter
    successful += check_microcenter(config, state, now, fetch, send, webhook,
                                   lambda current: save_state(state_path, current), dry_run, initialize)
    for feed in config['feeds']:
        try:
            entries = list(parse_feed(fetch(feed['url'])))
            if not entries:
                raise ValueError('no feed entries returned')
            successful += 1
        except Exception as e:
            LOG.warning('Feed unavailable: %s (%s)', feed['name'], type(e).__name__)
            continue
        for item in entries:
            if not eligible(item['title'], config):
                continue
            # URL + title allows updated prices in titles to produce a fresh alert.
            key = hashlib.sha256((item['url'] + '\n' + item['title']).encode()).hexdigest()
            if key in seen:
                continue
            if item['published'] and (now - item['published']).total_seconds() > config.get('max_age_days', 7) * 86400:
                continue
            if initialize:
                seen[key] = now.isoformat()
                continue
            price = advertised_price(item['title'])
            cap = config.get('max_price_usd')
            if cap is not None and (price is None or price > cap):
                continue
            target = config.get('target_price_usd', 3000)
            badge = 'WITHIN YOUR TARGET' if price is not None and price <= target else '64 GB DEAL LEAD'
            message = (f'**{badge}**\n{item["title"][:700]}\n'
                       f'Source: {feed["name"]}\n{item["url"]}\n'
                       'Condition, exact configuration, seller, stock, price and AppleCare eligibility need retailer confirmation. '
                       'No used/refurbished terms detected in headline; new condition is not verified.')
            if dry_run:
                print(message + '\n')
            else:
                send(webhook, message)
                seen[key] = now.isoformat()
                save_state(state_path, state)
                time.sleep(1)
    if not successful:
        raise RuntimeError('All feeds failed; no monitoring completed')
    if not dry_run:
        cutoff = now - dt.timedelta(days=180)
        state['seen'] = {k: v for k, v in seen.items() if dt.datetime.fromisoformat(v) >= cutoff}
        save_state(state_path, state)
    LOG.info('Checked %d sources successfully (feeds and stores)', successful)
    if config.get('microcenter', {}).get('enabled'):
        failed = [entry['store'] for entry in state.get('microcenter_health', {}).values()
                  if not entry['ok']]
        if failed:
            raise RuntimeError('Micro Center monitoring incomplete: ' + ', '.join(failed)
                               + '. Other sources were processed; check source errors above.')

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default='config.json')
    p.add_argument('--state', default='state/seen.json')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--initialize', action='store_true', help='Mark current entries seen without sending')
    p.add_argument('--test-discord', action='store_true')
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    try:
        if args.test_discord:
            send(os.getenv('DISCORD_WEBHOOK_URL', ''), '64 GB MacBook deal watcher connected. This is a setup test.')
        else:
            run(json.loads(Path(args.config).read_text()), Path(args.state), args.dry_run, args.initialize)
    except Exception as e:
        LOG.error('%s', str(e) if isinstance(e, (ValueError, RuntimeError)) else type(e).__name__)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
