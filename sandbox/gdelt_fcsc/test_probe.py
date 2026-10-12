import json
import tempfile
import unittest
from pathlib import Path

import probe


class ProbeTests(unittest.TestCase):
    def test_gdelt_deduplicates_urls_and_measures_increment(self):
        payload = json.loads((probe.FIXTURES / "gdelt_articles.json").read_text())
        baseline = json.loads((probe.FIXTURES / "existing_sources.json").read_text())

        records = probe.normalize_gdelt(payload)
        analysis = probe.analyze_gdelt(records, baseline)

        self.assertEqual(len(records), 3)
        self.assertEqual(analysis["unique_domains"], 3)
        self.assertEqual(analysis["novel_vs_baseline"], 2)
        self.assertEqual(analysis["overlap_vs_baseline"], 1)

    def test_bayanat_extracts_schema_year_range_and_freshness(self):
        payload = json.loads((probe.FIXTURES / "bayanat_resource.json").read_text())
        dataset = probe.normalize_bayanat(payload, title="Clean energy")
        analysis = probe.analyze_official_dataset(dataset)

        self.assertEqual(dataset["row_count"], 4)
        self.assertEqual(analysis["year_range"], [2022, 2025])
        self.assertEqual(analysis["incremental_assessment"], "useful_primary_statistics")

    def test_fcsc_sdmx_flattens_series(self):
        payload = json.loads((probe.FIXTURES / "fcsc_sdmx.json").read_text())

        records = probe.normalize_fcsc_sdmx(payload)

        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]["MEASURE"], "Population")
        self.assertEqual(records[-1]["TIME_PERIOD"], "2024")
        self.assertEqual(records[-1]["value"], 11290000)

    def test_empty_http_200_is_not_success(self):
        result = probe.FetchResult(
            provider="bayanat",
            endpoint="https://example.test",
            ok=False,
            status_code=200,
            latency_ms=1,
            error="empty_response_body",
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "empty_response_body")

    def test_double_encoded_bayanat_json_is_decoded(self):
        inner = json.dumps([{"year": "2025", "value": "12"}])

        payload = probe._parse_json_body(json.dumps(inner))

        self.assertEqual(payload, [{"year": "2025", "value": "12"}])

    def test_gdelt_raw_event_row_filters_and_normalizes_uae(self):
        row = [""] * 61
        row[0] = "123"
        row[7] = "UAE"
        row[26] = "010"
        row[28] = "01"
        row[31] = "8"
        row[32] = "3"
        row[33] = "5"
        row[34] = "1.25"
        row[52] = "Dubai, Dubayy, United Arab Emirates"
        row[59] = "20261007120000"
        row[60] = "https://example.ae/story"

        event = probe._normalize_gdelt_event_row(row)

        self.assertIsNotNone(event)
        self.assertEqual(event["location"], "Dubai, Dubayy, United Arab Emirates")
        self.assertEqual(event["article_count"], 5)
        self.assertEqual(event["average_tone"], 1.25)

    def test_mock_run_writes_parseable_results(self):
        with tempfile.TemporaryDirectory() as directory:
            result = probe.evaluate("mock", probe._mock_fetches())
            output = Path(directory) / "result.json"
            output.write_text(json.dumps(result), encoding="utf-8")

            restored = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(restored["providers"]["gdelt"]["verdict"], "pass")
            self.assertEqual(restored["providers"]["bayanat"]["verdict"], "pass")
            self.assertEqual(restored["providers"]["fcsc_uaestat"]["verdict"], "pass")


if __name__ == "__main__":
    unittest.main()
