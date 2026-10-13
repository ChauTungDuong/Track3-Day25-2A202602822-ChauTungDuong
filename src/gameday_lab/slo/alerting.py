"""Part E — Multi-window, multi-burn-rate alerting (Google SRE Workbook, ch. 5).

Input: per-minute ``total`` and ``bad`` request counts for a 30-day window.

burn_rate(window) = error_ratio(window) / (1 - SLO)

A rule fires at minute i when BOTH its long and its short window (ending at i,
inclusive) burn at least ``burn_rate``. The long window says "this is
significant"; the short window says "it is still happening" (so the alert
resets quickly after recovery).

Tests: tests/test_alerting.py, then `make slo`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlertRule:
    name: str
    severity: str  # "page" or "ticket"
    long_min: int
    short_min: int
    burn_rate: float


# SRE Workbook defaults for a 30-day SLO window
DEFAULT_RULES: tuple[AlertRule, ...] = (
    AlertRule("fast_burn_2pct_1h", "page", 60, 5, 14.4),
    AlertRule("slow_burn_5pct_6h", "page", 360, 30, 6.0),
    AlertRule("budget_leak_10pct_3d", "ticket", 4320, 360, 1.0),
)


@dataclass(frozen=True)
class AlertEvent:
    rule: str
    severity: str
    start_min: int  # first minute the rule fired
    end_min: int  # first minute it stopped firing (exclusive)


class WindowSums:
    """O(1) sum of any window, via prefix sums. Build once, query many times.

    43,200 minutes x 6 windows: recomputing every window with sum() is far too slow.
    """

    def __init__(self, values: list[int]) -> None:
        self.pref = [0] * (len(values) + 1)
        for i, v in enumerate(values):
            self.pref[i + 1] = self.pref[i] + v

    def sum(self, end_inclusive: int, length: int) -> int:
        start = max(0, end_inclusive - length + 1)
        end = max(0, min(len(self.pref) - 1, end_inclusive + 1))
        if start >= end:
            return 0
        return self.pref[end] - self.pref[start]


class BurnRateAlerter:
    def __init__(self, slo: float = 0.995, rules: tuple[AlertRule, ...] = DEFAULT_RULES) -> None:
        if not 0 < slo < 1:
            raise ValueError("slo must be in (0, 1)")
        self.slo = slo
        self.rules = rules

    def burn_rate(self, total: WindowSums, bad: WindowSums, end: int, length: int) -> float:
        tot = total.sum(end, length)
        if tot == 0:
            return 0.0
        b = bad.sum(end, length)
        return (b / tot) / (1.0 - self.slo)

    def evaluate(self, total: list[int], bad: list[int]) -> list[AlertEvent]:
        w_total = WindowSums(total)
        w_bad = WindowSums(bad)
        n = len(total)
        events: list[AlertEvent] = []

        for rule in self.rules:
            start_min: int | None = None
            for i in range(n):
                burn_long = self.burn_rate(w_total, w_bad, i, rule.long_min)
                burn_short = self.burn_rate(w_total, w_bad, i, rule.short_min)
                fires = (burn_long >= rule.burn_rate and burn_short >= rule.burn_rate)
                if fires:
                    if start_min is None:
                        start_min = i
                else:
                    if start_min is not None:
                        events.append(AlertEvent(rule.name, rule.severity, start_min, i))
                        start_min = None
            if start_min is not None:
                events.append(AlertEvent(rule.name, rule.severity, start_min, n))

        events.sort(key=lambda e: e.start_min)
        return events


def error_budget_report(total: list[int], bad: list[int], slo: float = 0.995) -> dict[str, float | bool]:
    reqs = sum(total)
    allowed_bad = round((1.0 - slo) * reqs, 1)
    bad_count = sum(bad)
    avail = round(1.0 - bad_count / reqs, 6) if reqs else 1.0
    consumed = round(bad_count / allowed_bad, 4) if allowed_bad else 0.0
    remaining = round(1.0 - consumed, 4)
    freeze = (remaining <= 0.0)
    return {
        "requests": reqs,
        "allowed_bad": allowed_bad,
        "bad": bad_count,
        "availability": avail,
        "budget_consumed": consumed,
        "budget_remaining": remaining,
        "freeze_releases": freeze,
    }
