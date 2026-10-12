# Sandbox assessment: GDELT, Bayanat, and FCSC/UAE.Stat

Assessment date: 2026-10-07

## Outcome

The sandbox is successful as a technical experiment, but the combined source
integration is **not yet ready for V2**. GDELT is suitable for a guarded media
signal pilot. Bayanat can return useful official rows but needs catalogue,
freshness, and empty-response protections. The UAE.Stat SDMX endpoint is blocked
from the current backend environment.

No production application files were changed.

## Live results

### GDELT DOC 2.0

- A successful run returned 50 articles from 41 domains in 14 languages.
- Response time was 16.7 seconds.
- Earlier calls from the same egress IP returned HTTP 429, so availability is
  intermittent even at sandbox request volume.
- The result set is broad, but several sampled headlines are not explicitly
  about UAE business. GDELT can find cross-language and international mentions,
  but should not be accepted as verified evidence without downstream relevance
  and credibility checks.

Decision: **partial go** as a cached media-momentum/discovery signal. Do not add
all returned URLs directly to the evidence pool.

### GDELT raw event feed

- The latest 15-minute export was reachable in 1.2 seconds.
- The archive was 88,482 bytes and contained 1,419 events.
- Two records matched UAE actor/location fields, but both pointed to one source
  URL.

Decision: technically reliable as a lightweight fallback, but the event coding
is too coarse to replace article search. It can support event-volume signals.

### Bayanat

- One resource returned 72 structured rows in 177 ms after handling Bayanat's
  double-encoded JSON response.
- The returned data was from 2019, so connectivity does not imply freshness.
- A second resource associated with a recently updated clean-energy portal page
  returned HTTP 200 after 14.1 seconds with an empty JSON payload.

Decision: **conditional**. A V2 adapter needs dataset discovery metadata,
per-dataset freshness rules, schema validation, nested-JSON decoding, timeouts,
and rejection of successful-but-empty responses.

### FCSC/UAE.Stat SDMX

- The fixture-based SDMX normalizer passed and produced official statistical
  records with dimensions, units, periods, and values.
- The documented live endpoint returned HTTP 403 from the current environment
  because of its Cloudflare access policy.

Decision: **blocked for live V2 use** until the deployed backend IP is tested or
FCSC supplies a machine-access/allowlist route.

## Incremental-information assessment

| Provider | New information compared with current providers | Confidence |
| --- | --- | --- |
| GDELT DOC | New cross-language domains and media-discovery breadth; limited new verified facts | Medium |
| GDELT raw events | Event frequency, actor, location, source-count and tone metadata | Medium-low |
| Bayanat | Potentially unique official UAE rows and measurements | High when current and non-empty |
| FCSC/UAE.Stat | High-value official national time series | High in principle; live access unverified |

## Required gates before V2

1. Test UAE.Stat from the actual deployed backend egress IP and obtain an
   allowlist route if it is still blocked.
2. Build a small curated Bayanat catalogue of business-relevant datasets and
   confirm at least five current resources return non-empty data.
3. Pilot GDELT with a single cached query, a global request interval, 429
   backoff, URL deduplication, and a relevance threshold.
4. Keep GDELT signals separate from primary-source citations; mark Bayanat and
   UAE.Stat records as primary only when source metadata, unit, period, and
   freshness are present.

