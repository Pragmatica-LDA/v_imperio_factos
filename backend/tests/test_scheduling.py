from datetime import datetime, timedelta, timezone

from core.parameters import DEFAULTS
from crawl.scheduling import PARAM_KEYS, compute

P = {k: float(DEFAULTS[k][0]) for k in PARAM_KEYS}
NOW = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)


def test_hot_topic_min_interval():
    c = compute(now=NOW, published_at=NOW - timedelta(hours=1), temperature=99, late_done=False, p=P)
    assert c.next_at == NOW + timedelta(hours=P["revisit.min_interval_h"])


def test_cooling_topic_interpolates():
    mid = (P["topics.hot_threshold"] + P["topics.cold_threshold"]) / 2
    c = compute(now=NOW, published_at=NOW, temperature=mid, late_done=False, p=P)
    h = (c.next_at - NOW).total_seconds() / 3600
    assert P["revisit.min_interval_h"] < h < P["revisit.max_interval_h"]


def test_cold_topic_only_late_revisit():
    c = compute(now=NOW, published_at=NOW, temperature=0.0, late_done=False, p=P)
    assert c.next_at == NOW + timedelta(days=P["revisit.late_days"])
    assert "tardia" in c.reason


def test_cold_topic_after_late_stops():
    c = compute(now=NOW, published_at=NOW - timedelta(days=8), temperature=0.0, late_done=True, p=P)
    assert c.next_at is None


def test_no_topic_window():
    c = compute(now=NOW, published_at=NOW - timedelta(hours=1), temperature=None, late_done=False, p=P)
    assert c.next_at == NOW + timedelta(hours=P["revisit.no_topic_interval_h"])
    c = compute(now=NOW, published_at=NOW - timedelta(hours=60), temperature=None, late_done=False, p=P)
    assert c.next_at == NOW - timedelta(hours=60) + timedelta(days=P["revisit.late_days"])
