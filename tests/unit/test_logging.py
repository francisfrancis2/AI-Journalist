"""Unit tests for backend log scrubbing."""

from backend.logging_config import scrub_event_fields


class TestLogScrubbing:
    def test_scrubs_text_email_and_url_fields(self):
        event = {
            "topic": "How NVIDIA became the world's most valuable chip company",
            "query": "nvidia ai infrastructure spending 2026",
            "new_user": "vladimir@example.com",
            "url": "https://news.google.com/rss/search?q=nvidia&hl=en-US",
            "count": 3,
        }

        scrubbed = scrub_event_fields(None, "info", event)

        assert scrubbed["topic"].startswith("[redacted:")
        assert scrubbed["query"].startswith("[redacted:")
        assert scrubbed["new_user"] == "v***@example.com"
        assert scrubbed["url"] == "https://news.google.com/...?..."
        assert scrubbed["count"] == 3
