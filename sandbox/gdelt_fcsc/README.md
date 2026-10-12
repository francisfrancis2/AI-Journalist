# GDELT + UAE Open Data sandbox

This sandbox tests GDELT, Bayanat, and FCSC/UAE.Stat without changing the V2
application. It answers three separate questions for each provider:

1. Can the backend reach the endpoint?
2. Can the response be normalized into evidence the Research Agent could use?
3. Does the response contain useful incremental structure (media diversity,
   trend data, or official statistical time series)?

The probe has two deliberately separate modes:

- `mock` uses small recorded-shape fixtures. It validates parsing and analysis
  deterministically and makes no network requests.
- `live` calls the public endpoints. Failures, throttling, Cloudflare blocks,
  empty HTTP 200 responses, and response formats are recorded as observed; no
  fixture data is silently substituted.

Run from the repository root:

```bash
python sandbox/gdelt_fcsc/probe.py --mode mock
python sandbox/gdelt_fcsc/probe.py --mode live
python sandbox/gdelt_fcsc/probe.py --mode both
python -m unittest discover -s sandbox/gdelt_fcsc -p 'test_*.py'
```

Outputs are written to `sandbox/gdelt_fcsc/out/` and ignored by Git. The
generated `findings.md` contains a concise go/no-go assessment. Live mode uses
no credentials and does not call any existing paid application provider.

## Live probes

- **GDELT DOC 2.0:** recent UAE business articles in JSON.
- **GDELT Event raw feed:** the latest 15-minute export, used as a fallback
  connectivity and UAE-event test when the hosted DOC API is throttled.
- **Bayanat:** one resource known to return JSON rows and one recent portal
  resource that currently demonstrates the `200 + empty body` edge case.
- **FCSC/UAE.Stat:** a documented SDMX population-indicator query.

These endpoints are diagnostic defaults, not the final V2 dataset catalogue.
