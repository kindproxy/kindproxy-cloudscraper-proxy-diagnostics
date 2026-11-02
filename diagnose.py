#!/usr/bin/env python3
"""Cloudscraper direct/proxy diagnostics. Only test endpoints you may access."""
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.parse import quote, urlsplit

import cloudscraper
import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

IP_ENDPOINT = "https://api.ipify.org?format=json"


def package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


def proxy_settings() -> dict[str, str]:
    raw = os.getenv("KP_PROXY_SERVER", "").strip()
    parsed = urlsplit(raw)
    user = os.getenv("KP_PROXY_USERNAME", "")
    password = os.getenv("KP_PROXY_PASSWORD", "")
    if (parsed.scheme != "http" or not parsed.hostname or not parsed.port
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or not user or not password):
        raise ValueError("Set KP_PROXY_SERVER=http://host:port and nonempty KP_PROXY_USERNAME/KP_PROXY_PASSWORD")
    hostname = parsed.hostname
    if ":" in hostname:
        hostname = f"[{hostname}]"
    proxy_url = f"http://{quote(user, safe='')}:{quote(password, safe='')}@{hostname}:{parsed.port}"
    return {"http": proxy_url, "https": proxy_url}


def classify_exception(exc: Exception) -> str:
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return "connection_timeout"
    if isinstance(exc, requests.exceptions.ReadTimeout):
        return "read_timeout"
    if isinstance(exc, requests.exceptions.SSLError):
        return "tls_error"
    if isinstance(exc, requests.exceptions.ProxyError):
        return "proxy_connection_error"
    if isinstance(exc, requests.exceptions.Timeout):
        return "timeout_unclassified"
    if isinstance(exc, requests.exceptions.TooManyRedirects):
        return "too_many_redirects"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "connection_error"
    if isinstance(exc, requests.exceptions.RequestException):
        return "request_error"
    return "request_failed"


def probe(session: requests.Session, url: str, mode: str, purpose: str,
          proxies: dict[str, str], connect_timeout: float, read_timeout: float,
          expected_text: str | None = None, expected_json_key: str | None = None):
    result = {"mode": mode, "purpose": purpose, "status": "request_failed"}
    observed_ip = None
    start = time.monotonic()
    try:
        response = session.get(url, proxies=proxies,
                               timeout=(connect_timeout, read_timeout),
                               allow_redirects=True)
        result.update(http_status=response.status_code,
                      content_type=response.headers.get("Content-Type", ""),
                      redirected=bool(response.history),
                      redirect_count=len(response.history))
        if response.headers.get("cf-mitigated", "").lower() == "challenge":
            result["status"] = "challenge_detected"
        elif response.status_code == 407:
            result["status"] = "http_407_source_unverified"
        elif response.status_code == 403:
            result["status"] = "http_403_source_unverified"
        elif response.status_code == 429:
            result["status"] = "rate_limited"
        elif response.status_code != 200:
            result["status"] = "unexpected_http_status"
        elif purpose == "exit_check":
            try:
                data = response.json()
                observed_ip = ipaddress.ip_address(data["ip"])
                result["status"] = "expected_content"
                result["exit_ip"] = "[redacted]"
            except (ValueError, KeyError, TypeError, AttributeError):
                result["status"] = "unexpected_content"
        elif expected_json_key is not None:
            try:
                data = response.json()
                keys = expected_json_key.split(".")
                for key in keys:
                    data = data[key]
                result["status"] = "expected_content"
            except (ValueError, KeyError, TypeError, IndexError):
                result["status"] = "unexpected_content"
        else:
            result["status"] = ("expected_content" if expected_text in response.text
                                else "unexpected_content")
    except Exception as exc:
        result["status"] = classify_exception(exc)
        result["error_type"] = type(exc).__name__  # Never print exception messages (may contain credentials)
    finally:
        result["elapsed_ms"] = round((time.monotonic() - start) * 1000)
    return result, observed_ip


def run_mode(mode: str, args):
    result = {}
    try:
        proxies = proxy_settings() if mode == "proxy" else {}
    except (ValueError, OSError) as exc:
        result["configuration_error"] = {"status": "invalid_proxy_configuration", "error_type": type(exc).__name__}
        return result, None
    session = cloudscraper.create_scraper()
    session.trust_env = False
    # Requests does not load environment CA bundle when trust_env=False.
    # Explicitly set REQUEST_CA_BUNDLE_FILE if a custom CA is required.
    ca_bundle = os.getenv("REQUEST_CA_BUNDLE_FILE", "").strip()
    if ca_bundle:
        session.verify = ca_bundle
    try:
        result["exit_check"], address = probe(session, IP_ENDPOINT, mode, "exit_check", proxies,
                                              args.connect_timeout, args.read_timeout)
        if args.url and result["exit_check"]["status"] == "expected_content":
            result["target_check"], _ = probe(session, args.url, mode, "target_check", proxies,
                                               args.connect_timeout, args.read_timeout,
                                               args.expected_text, args.expected_json_key)
        elif args.url:
            result["target_check"] = {"status": "skipped_exit_check_failed"}
        return result, address
    finally:
        session.close()


def main() -> int:
    if load_dotenv:
        load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("direct", "proxy", "compare"), default="direct")
    parser.add_argument("--url", help="Your own or explicitly authorized HTTP(S) test URL")
    marker = parser.add_mutually_exclusive_group()
    marker.add_argument("--expected-text", help="Distinctive response text")
    marker.add_argument("--expected-json-key", help="Required JSON key (supports dot notation)")
    parser.add_argument("--connect-timeout", type=float, default=10.0)
    parser.add_argument("--read-timeout", type=float, default=20.0)
    parser.add_argument("--output", help="Optional path to write the redacted JSON report")
    args = parser.parse_args()
    if args.url:
        parsed = urlsplit(args.url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            parser.error("--url must be an HTTP(S) URL without embedded credentials")
        if not (args.expected_text or args.expected_json_key):
            parser.error("--url requires --expected-text or --expected-json-key")
    elif args.expected_text or args.expected_json_key:
        parser.error("An expected-content check requires --url")
    if args.connect_timeout <= 0 or args.read_timeout <= 0:
        parser.error("Timeouts must be positive")

    report = {
        "tested_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python_version": platform.python_version(),
            "cloudscraper_version": package_version("cloudscraper"),
            "requests_version": package_version("requests"),
            "install_source": os.getenv("CLOUDSCRAPER_INSTALL_SOURCE", "not_declared"),
        },
        "results": {},
    }
    modes = ("direct", "proxy") if args.mode == "compare" else (args.mode,)
    addresses = {}
    for mode in modes:
        report["results"][mode], addresses[mode] = run_mode(mode, args)
    if args.mode == "compare":
        a, b = addresses.get("direct"), addresses.get("proxy")
        report["exit_comparison"] = "unavailable" if a is None or b is None else ("different" if a != b else "same")
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    print(serialized)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized + "\n", encoding="utf-8")
    return 0 if all("configuration_error" not in r for r in report["results"].values()) else 2


if __name__ == "__main__":
    sys.exit(main())
