# Cloudscraper Proxy Diagnostics (KindProxy)

A small Python diagnostic project for **direct vs HTTP/HTTPS residential proxy** requests using Cloudscraper. It verifies response content and observed exit differences; it **does not** promise to bypass Cloudflare or establish IP residential classification.

## Requirements

- Python 3.10+ (tested by KindProxy on Python 3.12.3)
- `cloudscraper==1.2.71` from PyPI (tested)
- KindProxy HTTP residential proxy credentials for proxy mode

## Quick start (Ubuntu/Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your **dashboard-generated** gateway, username and password. Do not commit `.env`. `KP_PROXY_SERVER` is the HTTP proxy gateway URL, even when the destination is HTTPS.

```bash
python diagnose.py --mode direct
python diagnose.py --mode proxy
python diagnose.py --mode compare
```

Verify an ordinary HTML page with a distinctive marker:

```bash
python diagnose.py --mode compare \
  --url 'https://example.com/' \
  --expected-text 'Example Domain' \
  --output output/result.json
```

For an authorized JSON endpoint:

```bash
python diagnose.py --mode proxy \
  --url 'https://YOUR_AUTHORIZED_HOST/data.json' \
  --expected-json-key 'status'
```

### CLI options

| Option | Purpose |
|---|---|
| `--mode direct|proxy|compare` | Run independent Cloudscraper sessions |
| `--url` | Optional endpoint you are permitted to test |
| `--expected-text` | Expected visible response marker |
| `--expected-json-key` | Required JSON field; supports dot notation |
| `--connect-timeout`, `--read-timeout` | Explicit timeout values in seconds |
| `--output` | Save redacted JSON report |

## Real tests (November 2, 2026)

KindProxy ran the tool on Python 3.12.3, Cloudscraper 1.2.71 and Requests 2.34.2. In the `compare` run against `https://example.com/` with `Example Domain` as expected text, **both direct and proxied IP-check requests returned HTTP 200 with valid expected JSON**, and **both HTML checks returned HTTP 200 with expected content**. `exit_comparison` was `different`.

| Check | Direct | Proxy |
|---|---:|---:|
| IP-check HTTP | 200 | 200 |
| IP-check elapsed | 115 ms | 763 ms |
| HTML-check HTTP | 200 | 200 |
| HTML-check elapsed | 48 ms | 716 ms |
| Expected content | Yes | Yes |

These are **individual observed timings**, not a performance benchmark. The tests did **not** validate Cloudflare challenge handling or residential IP classification. The `examples/sample-result.json` file is a clearly labeled illustrative output structure, not a verbatim raw test log.

### Published screenshots

![Direct HTTP test](https://cdn.kindproxy.com/blog_images/cloudscraper-direct-test.png)

![Proxy and exit comparison](https://cdn.kindproxy.com/blog_images/cloudscraper-proxy-comparison-test.png)

## Diagnostics and security

The script classifies `cf-mitigated: challenge`, HTTP 403/407/429, timeouts, proxy failures and TLS errors without assuming a specific root cause. It avoids printing credentials, cookies, raw exception messages, full exit IPs and target URLs. `exit_comparison: different` indicates different observed addresses at the IP-check endpoint; it is not proof of a residential IP or the exit used for a later target request.

`session.trust_env = False` avoids silently inheriting proxy variables; if your environment requires a custom CA bundle, set `REQUEST_CA_BUNDLE_FILE` to the trusted certificate bundle path. Keep certificate validation enabled.

Use only websites and endpoints you have permission to test. Do not use this project for CAPTCHA solving, bypassing access restrictions, or aggressive retry loops.

## Further reading

- [Cloudscraper on PyPI](https://pypi.org/project/cloudscraper/1.2.71/)
- [Cloudscraper upstream repository](https://github.com/VeNoMouS/cloudscraper)
- [Cloudflare Challenge response detection](https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/)
- [KindProxy residential proxies](https://www.kindproxy.com/pricing/residential-proxies/traffic/?spread=blog)

## License

MIT License; see `LICENSE`.
