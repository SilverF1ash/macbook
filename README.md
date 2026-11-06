# 64 GB MacBook Pro Discord Deal Watcher

A personal Python deal-feed monitor that posts to a Discord channel using a webhook. No Discord bot account, paid API, or Python packages needed. The GitHub Actions workflow is configured to check every 30 minutes; Discord delivery requires the repository secret.

## What it watches

Slickdeals MacBook search, 9to5Toys, MacRumors, AppleInsider and Macworld RSS feeds. These can cover multiple retailers, but this does not directly monitor every retailer or guarantee every deal. Headlines must mention both MacBook Pro and 64 GB, plus price/deal language. It can miss roundups where the 64 GB configuration appears only in the article body. Retailer sites and feeds can block requests or change format.

Defaults:
- All chip generations qualify, to include older clearance inventory. Set `chips` to `["M5", "M6"]` to restrict it.
- Explicit used, refurbished, renewed and open-box headlines are excluded. **New condition is not verified**; every alert is a lead requiring retailer confirmation.
- All qualifying prices are included. An unambiguous headline price at or below $3,000 gets a target badge. To send only priced leads at or below $3,000, change `max_price_usd` from `null` to `3000`; this also excludes articles without a clear headline price.
- First run sends qualifying feed entries up to 7 days old. Run `--initialize` first to suppress existing entries.
- Repeated URL/title pairs are suppressed for 180 days. Cross-source articles and edited headlines can produce another alert. Delivery is at-least-once: an interrupted run after posting but before saving state can resend.
- No purchases, no @everyone pings. Prices, stock, coupons, location restrictions and AppleCare eligibility must be checked on the retailer page. It does not verify that a discount is genuinely below historical prices.

## 1. Create a private Discord channel and webhook

In your own server, create a channel such as `#macbook-deals`. On Discord desktop/browser, open channel settings → Integrations → Webhooks → New Webhook → select that channel → Copy Webhook URL. You need permission to manage webhooks. This posts channel messages; it does not send direct messages.

Treat the webhook URL like a password. Enter it only in a local environment variable or a GitHub Actions secret. Do not put it in the code, config, screenshots, or chat. Enable channel notifications in Discord/mobile if you want push alerts. No personal user ID is needed.

## 2. Run on your Mac (Python 3.11+)

Extract this ZIP, open Terminal, and change into the extracted project folder:

```bash
cd /path/to/macbook-discord-watcher
python3 -m unittest discover -s tests -v
python3 watcher.py --dry-run
```

Set the secret without printing it or saving it in shell history:

```bash
read -s -p 'Paste Discord webhook URL: ' DISCORD_WEBHOOK_URL
export DISCORD_WEBHOOK_URL
printf '\n'
python3 watcher.py --test-discord
python3 watcher.py
```

The `read -p` example uses bash; start `bash` first if your Terminal uses zsh. Dry-run performs real feed requests but sends nothing and does not change state. A Discord delivery test sends one setup message to your selected channel.

For continuous local checks, keep the following running. The laptop must stay awake and online; closing Terminal stops it.

```bash
while true; do
  python3 watcher.py
  sleep 1800
done
```

## 3. Alternative: run while your laptop is off with GitHub Actions

1. Create a GitHub repository and upload **the contents** of this folder, including `.github/workflows/deals.yml`, at repository root. GitHub must receive the workflow file, not the ZIP. `watcher.py` and `config.json` should be at the root.
2. Open repository Settings → Secrets and variables → Actions → New repository secret. Name: `DISCORD_WEBHOOK_URL`. Value: your webhook URL.
3. Ensure Actions is enabled and repository policy allows the supplied workflow to write contents. It commits only `state/seen.json`, which stores delivery fingerprints and timestamps, not the webhook.
4. In Actions, select **MacBook deal watcher** → Run workflow. Check logs and the Discord channel. No deal alert on a successful run simply means no matching unseen feed entry was found.
5. The included schedule checks at minutes 7 and 37 of every hour, in UTC. Scheduling is approximate and may be delayed. The workflow must be on the default branch. Public-repository schedules may be disabled after 60 days without activity; check periodically. Private-repository Actions usage depends on your plan and can incur charges if included minutes are exceeded. No hosting or billing has been enabled by this download.

To stop, disable the GitHub workflow or stop the local loop. Rotate/delete the Discord webhook if it leaks. Use one scheduler for each shared state file; don't run local and cloud copies together if you want duplicate suppression across both.

## Troubleshooting

- **Feed unavailable warning:** one source failed; other sources still run. All sources failing returns a nonzero exit so GitHub marks the run failed. Partial failures produce warnings, not Discord health alerts.
- **Discord HTTP 401/404:** recreate the webhook and update the secret. Never paste its URL into an issue or chat.
- **No messages:** run `--test-discord`, then `--dry-run`. The filters are intentionally strict about 64 GB appearing in the headline.
- **No price badge:** many articles quote the discount amount rather than the laptop price. The watcher avoids treating "$600 off" as a $600 MacBook.
- Local state is `state/seen.json`. Deleting it causes existing qualifying entries to alert again.

## Verification and limitations

Five offline tests cover headline filtering, price ambiguity, Atom parsing, duplicate suppression, failed-delivery retry state, and total source failure. Live feed availability depends on the machine's network and the publishers. A real Discord test requires your webhook. No claim of exhaustive platform coverage is made.

Reference documentation:
- Discord webhook API: https://github.com/discord/discord-api-docs/blob/main/developers/resources/webhook.mdx
- GitHub scheduling: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

## Direct Micro Center monitoring

The `microcenter` section in `config.json` enables direct public listing checks for Cambridge (121) and North Jersey (075), alongside the RSS feeds. Each check verifies the selected store and scans result pages (maximum 15 per store). It filters for MacBook Pro listings explicitly specifying 64GB memory/RAM and positive stock at that store, excluding used/refurbished/open-box product titles.

A listing qualifies when it advertises savings, costs at most `target_price_usd`, or its price is below the previously observed price. The optional `max_price_usd` also applies. The first check can alert on existing sales above $3,000; that amount is a target badge, not a hard cap. Each store/product/price is alerted once, including further price drops. State is saved in `state/seen.json`. Open-box offers attached to new product cards are not scanned.

A blocked request, unverified store, missing product cards or excessive pagination generates a source warning; other feeds/stores continue. Check logs for Micro Center source warnings even when the overall run succeeds. A successful Discord setup test does not verify retailer access. Retailer HTML and access rules can change, and access from GitHub runners may differ from a local check. Final stock, prices and AppleCare eligibility require retailer confirmation.

## Micro Center access status

Direct listing requests returned HTTP 403 Forbidden from GitHub-hosted Linux and Windows runners during live diagnostics. Per-store health is recorded in state/seen.json. The main workflow now fails if an enabled store could not be checked, after processing the other sources and saving delivery history. A green RSS check or successful Discord test is not evidence of retailer access.

The existing local execution instructions can be used to test access from your own computer. Local access is not guaranteed, and continuous local monitoring requires that computer to remain awake and online. No proxy, CAPTCHA bypass, paid service, alternative secret destination or self-hosted runner has been configured.
