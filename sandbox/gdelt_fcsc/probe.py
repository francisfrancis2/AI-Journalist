#!/usr/bin/env python3
"""Isolated connectivity and usefulness probe for GDELT and UAE open data."""

from __future__ import annotations

import argparse
import csv
import io
import json
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"

GDELT_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_LAST_UPDATE = "https://data.gdeltproject.org/gdeltv2/lastupdate.txt"
BAYANAT_ENDPOINT = "https://bayanat.ae/api/DatasetResources/GetDatasetResource"
FCSC_POPULATION_URL = (
    "https://releaseeuaestat.fcsc.gov.ae/rest/data/"
    "FCSA,DF_POP_IND,2.7.0/....A..?startPeriod=2019&endPeriod=2020"
    "&dimensionAtObservation=AllDimensions"
)

# The first resource currently returns structured rows. The second is attached
# to a recently updated clean-energy portal page but has been observed returning
# an empty HTTP 200 body, an important failure mode for a future adapter.
BAYANAT_WORKING_RESOURCE = "e43e91a9-6a63-428c-b3d6-7d09f267e189"
BAYANAT_EMPTY_RESOURCE = "e2be2cf7-5fe7-40cb-bd18-c8455fa7faa8"


@dataclass
class FetchResult:
    provider: str
    endpoint: str
    ok: bool
    status_code: int | None
    latency_ms: int
    payload: Any = None
    error: str | None = None
    response_preview: str | None = None


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_json_body(body: str) -> Any:
    """Decode JSON APIs that sometimes return JSON inside a JSON string."""
    payload = json.loads(body)
    for _ in range(2):
        if not isinstance(payload, str) or not payload.strip():
            break
        candidate = payload.strip()
        if not candidate.startswith(("[", "{")):
            break
        payload = json.loads(candidate)
    return payload


def fetch_json(
    provider: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> FetchResult:
    request_headers = {
        "Accept": "application/json",
        "User-Agent": "AI-Journalist-source-sandbox/1.0",
        **(headers or {}),
    }
    started = time.monotonic()
    try:
        request = Request(url, headers=request_headers)
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            latency_ms = round((time.monotonic() - started) * 1000)
            if not body.strip():
                return FetchResult(
                    provider=provider,
                    endpoint=url,
                    ok=False,
                    status_code=response.status,
                    latency_ms=latency_ms,
                    error="empty_response_body",
                )
            try:
                payload = _parse_json_body(body)
            except json.JSONDecodeError as exc:
                return FetchResult(
                    provider=provider,
                    endpoint=url,
                    ok=False,
                    status_code=response.status,
                    latency_ms=latency_ms,
                    error=f"invalid_json: {exc}",
                    response_preview=body[:300],
                )
            if payload is None or payload == "" or payload == [] or payload == {}:
                return FetchResult(
                    provider=provider,
                    endpoint=url,
                    ok=False,
                    status_code=response.status,
                    latency_ms=latency_ms,
                    error="empty_json_payload",
                    response_preview=body[:300],
                )
            return FetchResult(
                provider=provider,
                endpoint=url,
                ok=True,
                status_code=response.status,
                latency_ms=latency_ms,
                payload=payload,
            )
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return FetchResult(
            provider=provider,
            endpoint=url,
            ok=False,
            status_code=exc.code,
            latency_ms=round((time.monotonic() - started) * 1000),
            error=f"http_{exc.code}",
            response_preview=body[:300],
        )
    except (URLError, TimeoutError, OSError) as exc:
        return FetchResult(
            provider=provider,
            endpoint=url,
            ok=False,
            status_code=None,
            latency_ms=round((time.monotonic() - started) * 1000),
            error=f"network_error: {exc}",
        )


def _normalize_gdelt_event_row(row: list[str]) -> dict[str, Any] | None:
    if len(row) < 61:
        return None
    actor_country_match = row[7] == "UAE" or row[17] == "UAE"
    geo_country_match = any(row[index] == "AE" for index in (37, 45, 53))
    name_match = any("United Arab Emirates" in row[index] for index in (36, 44, 52))
    if not (actor_country_match or geo_country_match or name_match):
        return None

    def integer(index: int) -> int | None:
        try:
            return int(row[index])
        except (ValueError, TypeError):
            return None

    def number(index: int) -> float | None:
        try:
            return float(row[index])
        except (ValueError, TypeError):
            return None

    return {
        "provider": "gdelt_raw_event",
        "evidence_type": "media_event_signal",
        "event_id": row[0],
        "event_code": row[26],
        "event_root_code": row[28],
        "actor_1": row[6] or None,
        "actor_2": row[16] or None,
        "location": row[52] or row[36] or row[44] or None,
        "mentions": integer(31),
        "source_count": integer(32),
        "article_count": integer(33),
        "average_tone": number(34),
        "observed_at": row[59] or None,
        "url": row[60] or None,
        "credibility": "unverified",
    }


def fetch_gdelt_raw_events(timeout: float = 20.0) -> FetchResult:
    """Download and filter the latest small GDELT event export."""
    started = time.monotonic()
    headers = {"User-Agent": "AI-Journalist-source-sandbox/1.0"}
    try:
        with urlopen(Request(GDELT_LAST_UPDATE, headers=headers), timeout=timeout) as response:
            manifest = response.read().decode("utf-8", errors="replace")
        export_lines = [line for line in manifest.splitlines() if ".export.CSV.zip" in line]
        if not export_lines:
            raise ValueError("manifest_missing_event_export")
        parts = export_lines[0].split()
        archive_url = parts[-1].replace("http://", "https://", 1)
        with urlopen(Request(archive_url, headers=headers), timeout=timeout) as response:
            archive = response.read()
            status_code = response.status
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            member = zipped.namelist()[0]
            text = zipped.read(member).decode("utf-8", errors="replace")
        rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
        events = [event for row in rows if (event := _normalize_gdelt_event_row(row))]
        return FetchResult(
            provider="gdelt_raw_event",
            endpoint=archive_url,
            ok=True,
            status_code=status_code,
            latency_ms=round((time.monotonic() - started) * 1000),
            payload={
                "manifest_url": GDELT_LAST_UPDATE,
                "archive_url": archive_url,
                "archive_bytes": len(archive),
                "total_events": len(rows),
                "uae_events": events,
            },
        )
    except HTTPError as exc:
        return FetchResult(
            provider="gdelt_raw_event",
            endpoint=GDELT_LAST_UPDATE,
            ok=False,
            status_code=exc.code,
            latency_ms=round((time.monotonic() - started) * 1000),
            error=f"http_{exc.code}",
        )
    except (URLError, TimeoutError, OSError, ValueError, zipfile.BadZipFile) as exc:
        return FetchResult(
            provider="gdelt_raw_event",
            endpoint=GDELT_LAST_UPDATE,
            ok=False,
            status_code=None,
            latency_ms=round((time.monotonic() - started) * 1000),
            error=f"feed_error: {exc}",
        )


def normalize_gdelt(payload: Any) -> list[dict[str, Any]]:
    articles = payload.get("articles", []) if isinstance(payload, dict) else []
    normalized: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for article in articles:
        if not isinstance(article, dict):
            continue
        url = str(article.get("url") or "").strip()
        title = str(article.get("title") or "").strip()
        if not url or not title or url in seen_urls:
            continue
        seen_urls.add(url)
        normalized.append(
            {
                "provider": "gdelt",
                "evidence_type": "media_article",
                "url": url,
                "title": title,
                "published_at": article.get("seendate"),
                "domain": article.get("domain"),
                "language": article.get("language"),
                "source_country": article.get("sourcecountry"),
                "credibility": "unverified",
            }
        )
    return normalized


def normalize_bayanat(payload: Any, *, title: str) -> dict[str, Any]:
    rows = [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []
    columns = sorted({str(key) for row in rows for key in row})
    years: list[int] = []
    for row in rows:
        for key in ("year", "Year", "date", "Date"):
            value = str(row.get(key) or "")[:4]
            if value.isdigit():
                years.append(int(value))
                break
    return {
        "provider": "bayanat",
        "evidence_type": "official_dataset",
        "title": title,
        "row_count": len(rows),
        "columns": columns,
        "year_min": min(years) if years else None,
        "year_max": max(years) if years else None,
        "sample_rows": rows[:5],
        "credibility": "high",
        "primary_source": True,
    }


def normalize_fcsc_sdmx(payload: Any) -> list[dict[str, Any]]:
    """Flatten the common SDMX-JSON series/observation representation."""
    if not isinstance(payload, dict):
        return []
    data_sets = payload.get("dataSets") or payload.get("data", {}).get("dataSets") or []
    structure = payload.get("structure") or {}
    if not data_sets or not isinstance(structure, dict):
        return []
    dimensions = structure.get("dimensions", {})
    series_dimensions = dimensions.get("series", [])
    observation_dimensions = dimensions.get("observation", [])
    if not observation_dimensions:
        return []
    time_dimension = observation_dimensions[0]
    time_values = time_dimension.get("values", [])
    records: list[dict[str, Any]] = []
    for data_set in data_sets:
        for series_key, series in (data_set.get("series") or {}).items():
            indexes = [int(value) for value in series_key.split(":") if value != ""]
            labels: dict[str, Any] = {}
            for dimension, value_index in zip(series_dimensions, indexes):
                values = dimension.get("values", [])
                if value_index < len(values):
                    selected = values[value_index]
                    labels[dimension.get("id", "unknown")] = selected.get("name") or selected.get("id")
            for observation_key, observation in (series.get("observations") or {}).items():
                time_index = int(observation_key)
                period = time_values[time_index] if time_index < len(time_values) else {}
                value = observation[0] if isinstance(observation, list) and observation else observation
                records.append(
                    {
                        "provider": "fcsc_uaestat",
                        "evidence_type": "official_statistic",
                        **labels,
                        "TIME_PERIOD": period.get("name") or period.get("id") or observation_key,
                        "value": value,
                        "credibility": "high",
                        "primary_source": True,
                    }
                )
    return records


def analyze_gdelt(records: list[dict[str, Any]], baseline: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_urls = {str(item.get("url") or "") for item in baseline}
    domains = {str(item.get("domain")) for item in records if item.get("domain")}
    languages = {str(item.get("language")) for item in records if item.get("language")}
    novel = [item for item in records if item.get("url") not in baseline_urls]
    return {
        "normalized_articles": len(records),
        "unique_domains": len(domains),
        "languages": sorted(languages),
        "novel_vs_baseline": len(novel),
        "overlap_vs_baseline": len(records) - len(novel),
        "incremental_assessment": (
            "useful_as_media_signal" if len(domains) >= 2 else "insufficient_diversity"
        ),
    }


def analyze_official_dataset(dataset: dict[str, Any]) -> dict[str, Any]:
    year_max = dataset.get("year_max")
    current_year = datetime.now(timezone.utc).year
    age = current_year - year_max if isinstance(year_max, int) else None
    return {
        "rows": dataset.get("row_count", 0),
        "columns": dataset.get("columns", []),
        "year_range": [dataset.get("year_min"), year_max],
        "age_years": age,
        "freshness": (
            "current_or_recent" if age is not None and age <= 2
            else "historical_or_unknown"
        ),
        "incremental_assessment": (
            "useful_primary_statistics" if dataset.get("row_count", 0) >= 2
            else "insufficient_rows"
        ),
    }


def _mock_fetches() -> dict[str, FetchResult]:
    return {
        "gdelt": FetchResult(
            "gdelt", "fixture://gdelt_articles.json", True, 200, 0,
            _load_json(FIXTURES / "gdelt_articles.json"),
        ),
        "bayanat": FetchResult(
            "bayanat", "fixture://bayanat_resource.json", True, 200, 0,
            _load_json(FIXTURES / "bayanat_resource.json"),
        ),
        "fcsc": FetchResult(
            "fcsc_uaestat", "fixture://fcsc_sdmx.json", True, 200, 0,
            _load_json(FIXTURES / "fcsc_sdmx.json"),
        ),
    }


def _live_fetches(topic: str, timeout: float) -> dict[str, FetchResult]:
    gdelt_query = urlencode({
        'query': f'(UAE OR "United Arab Emirates") {topic}',
        'mode': 'artlist',
        'format': 'json',
        'maxrecords': '50',
        'timespan': '30d',
        'sort': 'datedesc',
    })
    gdelt_url = f"{GDELT_ENDPOINT}?{gdelt_query}"
    working_url = f"{BAYANAT_ENDPOINT}?{urlencode({'resourceID': BAYANAT_WORKING_RESOURCE})}"
    empty_url = f"{BAYANAT_ENDPOINT}?{urlencode({'resourceID': BAYANAT_EMPTY_RESOURCE})}"
    return {
        "gdelt": fetch_json("gdelt", gdelt_url, timeout=timeout),
        "gdelt_raw": fetch_gdelt_raw_events(timeout=timeout),
        "bayanat": fetch_json("bayanat", working_url, timeout=timeout),
        "bayanat_empty_case": fetch_json("bayanat", empty_url, timeout=timeout),
        "fcsc": fetch_json(
            "fcsc_uaestat",
            FCSC_POPULATION_URL,
            headers={"Accept": "application/vnd.sdmx.data+json;version=2.0.0"},
            timeout=timeout,
        ),
    }


def evaluate(mode: str, fetches: dict[str, FetchResult]) -> dict[str, Any]:
    baseline = _load_json(FIXTURES / "existing_sources.json")
    providers: dict[str, Any] = {}

    gdelt_fetch = fetches["gdelt"]
    gdelt_records = normalize_gdelt(gdelt_fetch.payload) if gdelt_fetch.ok else []
    providers["gdelt"] = {
        "fetch": asdict(gdelt_fetch) | {"payload": None},
        "analysis": analyze_gdelt(gdelt_records, baseline),
        "sample": gdelt_records[:5],
        "verdict": (
            "pass" if gdelt_fetch.ok and len(gdelt_records) >= 3
            else "conditional_rate_limit" if gdelt_fetch.status_code == 429
            else "fail"
        ),
    }

    if "gdelt_raw" in fetches:
        raw_fetch = fetches["gdelt_raw"]
        raw_payload = raw_fetch.payload if raw_fetch.ok and isinstance(raw_fetch.payload, dict) else {}
        raw_events = raw_payload.get("uae_events", [])
        providers["gdelt_raw_event"] = {
            "fetch": asdict(raw_fetch) | {"payload": None},
            "analysis": {
                "archive_bytes": raw_payload.get("archive_bytes"),
                "total_events": raw_payload.get("total_events", 0),
                "uae_events": len(raw_events),
                "unique_source_urls": len({item.get("url") for item in raw_events if item.get("url")}),
                "incremental_assessment": (
                    "usable_event_signal" if raw_events else "reachable_but_no_uae_events_in_window"
                ),
            },
            "sample": raw_events[:5],
            "verdict": (
                "pass" if raw_fetch.ok and raw_events
                else "reachable_no_matching_events" if raw_fetch.ok
                else "fail"
            ),
        }

    bay_fetch = fetches["bayanat"]
    bay_dataset = normalize_bayanat(
        bay_fetch.payload if bay_fetch.ok else [],
        title="Bayanat diagnostic resource",
    )
    providers["bayanat"] = {
        "fetch": asdict(bay_fetch) | {"payload": None},
        "analysis": analyze_official_dataset(bay_dataset),
        "sample": bay_dataset.get("sample_rows", []),
        "verdict": "pass" if bay_fetch.ok and bay_dataset["row_count"] else "fail",
    }

    fcsc_fetch = fetches["fcsc"]
    fcsc_records = normalize_fcsc_sdmx(fcsc_fetch.payload) if fcsc_fetch.ok else []
    providers["fcsc_uaestat"] = {
        "fetch": asdict(fcsc_fetch) | {"payload": None},
        "analysis": {
            "normalized_statistics": len(fcsc_records),
            "periods": sorted({str(item.get("TIME_PERIOD")) for item in fcsc_records}),
            "incremental_assessment": (
                "useful_primary_statistics" if len(fcsc_records) >= 2 else "not_observed"
            ),
        },
        "sample": fcsc_records[:5],
        "verdict": (
            "pass" if fcsc_fetch.ok and len(fcsc_records) >= 2
            else "conditional_access_block" if fcsc_fetch.status_code == 403
            else "fail"
        ),
    }

    if "bayanat_empty_case" in fetches:
        empty_fetch = fetches["bayanat_empty_case"]
        empty_guard_errors = {"empty_response_body", "empty_json_payload"}
        providers["bayanat_empty_case"] = {
            "fetch": asdict(empty_fetch) | {"payload": None},
            "analysis": {"guard_detected_empty_200": empty_fetch.error in empty_guard_errors},
            "verdict": "expected_guard_pass" if empty_fetch.error in empty_guard_errors else "unexpected",
        }

    return {
        "mode": mode,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "providers": providers,
    }


def render_findings(results: list[dict[str, Any]]) -> str:
    lines = [
        "# GDELT + UAE open-data sandbox findings",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "No V2 application code was used or changed by this probe.",
        "",
    ]
    for result in results:
        lines.extend([f"## {result['mode'].title()} run", ""])
        for name, provider in result["providers"].items():
            fetch = provider.get("fetch", {})
            lines.extend(
                [
                    f"### {name}",
                    "",
                    f"- Verdict: `{provider['verdict']}`",
                    f"- HTTP status: `{fetch.get('status_code')}`",
                    f"- Latency: `{fetch.get('latency_ms')} ms`",
                    f"- Error: `{fetch.get('error')}`",
                    f"- Analysis: `{json.dumps(provider.get('analysis', {}), ensure_ascii=False)}`",
                    "",
                ]
            )
    lines.extend(
        [
            "## Decision rule for V2", "",
            "- GDELT proceeds only with global throttling, caching, and graceful 429 fallback.",
            "- Bayanat proceeds only with schema/freshness checks and rejection of empty HTTP 200 responses.",
            "- UAE.Stat proceeds only after the deployed backend IP can access the SDMX endpoint or FCSC provides an allowlist path.",
            "- GDELT should be stored as a media signal; official statistics should remain primary-source evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("mock", "live", "both"), default="both")
    parser.add_argument("--topic", default="business")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "out")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    modes = ("mock", "live") if args.mode == "both" else (args.mode,)
    results: list[dict[str, Any]] = []
    for mode in modes:
        fetches = _mock_fetches() if mode == "mock" else _live_fetches(args.topic, args.timeout)
        result = evaluate(mode, fetches)
        results.append(result)
        (args.output_dir / f"{mode}_result.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    findings = render_findings(results)
    (args.output_dir / "findings.md").write_text(findings, encoding="utf-8")
    print(findings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
