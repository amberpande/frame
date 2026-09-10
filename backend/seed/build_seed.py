"""Build the local DuckDB fixture.

The whole stack runs against this so development needs no warehouse
credentials. The data tells one deliberate story, because a fixture of uniform
noise makes every ranking look correct:

  * 1 Sep - a vendor master migration spikes VENDOR_BANK and breaks
    INVOICE_MATCH, which stays broken.
  * 3 Sep - the break cascades into PAYMENT_RECON, two days downstream.
  * 3 Sep - an unrelated access recertification window opens, lifting
    ACCESS_RECERT sixfold. It is a separate cause, not part of the migration.
  * Throughout - KYC_REFRESH quietly improves, which a severity ranking that
    only looks at regressions would miss entirely.

Two causes and one improvement, because a human scanning a grid would blame
everything on a single incident.

    python seed/build_seed.py
"""

from __future__ import annotations

import csv
import math
import random
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb  # noqa: E402

from frame.config import DATA_DIR, DUCKDB_PATH  # noqa: E402

START = date(2026, 6, 25)
END = date(2026, 9, 8)

MIGRATION = date(2026, 9, 1)
CASCADE = date(2026, 9, 3)
RECERT = date(2026, 9, 3)
KYC_FIX = date(2026, 9, 2)

REGIONS = {"AMER": 1.0, "EMEA": 0.72, "APAC": 0.46}

# Legal entity follows region, as it does in a real group structure.
ENTITY_BY_REGION = {
    "AMER": ["US Operations"],
    "EMEA": ["EU Holdings", "UK Services"],
    "APAC": ["APAC Trading"],
}

# Tail vendors generate disproportionately many matching exceptions, which is
# the finding these dashboards exist to surface.
VENDOR_TIERS = [("Strategic", 0.16), ("Preferred", 0.36), ("Tail", 0.48)]
TAIL_HEAVY = {"INVOICE_MATCH", "TAX_ID", "VENDOR_BANK"}

# reason_code -> (team, process, base daily count, mean age, mean amount)
REASONS = {
    "INVOICE_MATCH": ("Accounts Payable", "P2P", 42, 6.5, 12_400),
    "PAYMENT_RECON": ("Treasury", "P2P", 24, 9.0, 48_000),
    "VENDOR_BANK": ("Master Data", "P2P", 11, 4.0, 31_000),
    "DUP_PAYMENT": ("Accounts Payable", "P2P", 7, 12.0, 76_000),
    "ACCESS_RECERT": ("Compliance", "R2R", 5, 18.0, 0),
    "KYC_REFRESH": ("Compliance", "KYC", 30, 22.0, 0),
    "TAX_ID": ("Master Data", "P2P", 9, 15.0, 4_200),
    "FX_RATE": ("Treasury", "R2R", 13, 3.5, 22_500),
    "GL_MAPPING": ("Accounts Receivable", "O2C", 18, 7.5, 9_800),
}


def ramp(day: date, start: date, days: int, peak: float) -> float:
    """1.0 before `start`, easing to `peak` over `days`."""
    if day < start:
        return 1.0
    progress = min((day - start).days / days, 1.0)
    return 1.0 + (peak - 1.0) * progress


def decay(day: date, start: date, days: int, peak: float) -> float:
    """Spike to `peak` on `start`, then back to 1.0 over `days`."""
    if day < start:
        return 1.0
    elapsed = (day - start).days
    if elapsed >= days:
        return 1.0
    return 1.0 + (peak - 1.0) * (1.0 - elapsed / days)


def story_multiplier(reason: str, day: date) -> float:
    if reason == "INVOICE_MATCH":
        return ramp(day, MIGRATION, 3, 2.45)
    if reason == "PAYMENT_RECON":
        return ramp(day, CASCADE, 4, 1.9)
    if reason == "VENDOR_BANK":
        return decay(day, MIGRATION, 13, 3.1)
    if reason == "ACCESS_RECERT":
        return ramp(day, RECERT, 1, 6.0)
    if reason == "KYC_REFRESH":
        # A gradual drift never looks anomalous to a z-score, and should not.
        # The automation that lands on 2 Sep is a step, so severity sees it —
        # signed negative, ranked alongside the regressions, styled as good.
        span = (END - START).days or 1
        drift = 1.0 - 0.15 * ((day - START).days / span)
        return drift * (0.48 if day >= KYC_FIX else 1.0)
    return 1.0


def seasonality(day: date) -> float:
    return 0.55 if day.weekday() >= 5 else 1.0


def pick_vendor_tier(rng: random.Random, reason: str) -> str:
    weights = [w for _, w in VENDOR_TIERS]
    if reason in TAIL_HEAVY:
        weights = [0.08, 0.27, 0.65]
    return rng.choices([t for t, _ in VENDOR_TIERS], weights=weights)[0]


def pick_priority(rng: random.Random, amount: float, age: int) -> str:
    """Priority tracks money and age, so it is not just a third random column."""
    if amount > 60_000 or age > 45:
        return "P1"
    if amount > 12_000 or age > 20:
        return "P2" if rng.random() > 0.15 else "P1"
    return "P3" if rng.random() > 0.25 else "P2"


def build() -> None:
    rng = random.Random(20260812)
    rows: list[tuple] = []
    next_id = 1

    day = START
    while day <= END:
        for reason, (team, process, base, mean_age, mean_amount) in REASONS.items():
            for region, region_mult in REGIONS.items():
                target = (
                    base
                    * region_mult
                    * story_multiplier(reason, day)
                    * seasonality(day)
                    * rng.lognormvariate(0.0, 0.11)
                )
                # ~15% are already closed, so the metric's status filter has
                # real work to do rather than being decorative.
                total = max(0, int(round(target / 0.85)))
                for _ in range(total):
                    roll = rng.random()
                    status = "CLOSED" if roll < 0.15 else ("PENDING" if roll < 0.42 else "OPEN")
                    age = max(0, int(rng.expovariate(1.0 / mean_age)))
                    amount = (
                        round(rng.lognormvariate(math.log(mean_amount), 0.85), 2)
                        if mean_amount
                        else 0.0
                    )
                    rows.append(
                        (
                            f"EX{next_id:08d}",
                            day,
                            team,
                            reason,
                            region,
                            process,
                            rng.choice(ENTITY_BY_REGION[region]),
                            pick_vendor_tier(rng, reason),
                            pick_priority(rng, amount, age),
                            status,
                            age,
                            amount,
                        )
                    )
                    next_id += 1
        day += timedelta(days=1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DUCKDB_PATH))
    con.execute("DROP TABLE IF EXISTS fct_exception")
    con.execute(
        """
        CREATE TABLE fct_exception (
            exception_id  VARCHAR,
            as_of_date    DATE,
            team          VARCHAR,
            reason_code   VARCHAR,
            region        VARCHAR,
            process       VARCHAR,
            entity        VARCHAR,
            vendor_tier   VARCHAR,
            priority      VARCHAR,
            status        VARCHAR,
            age_days      INTEGER,
            amount_usd    DOUBLE
        )
        """
    )
    # Bulk load via CSV rather than executemany. Row-at-a-time insertion of
    # ~28k rows took minutes on a loaded machine; COPY takes under a second and
    # is what you would use against a real warehouse anyway.
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / "fct_exception.csv"
        with staged.open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)
        con.execute(
            f"COPY fct_exception FROM '{staged.as_posix()}' "
            "(FORMAT CSV, HEADER FALSE, DATEFORMAT '%Y-%m-%d')"
        )
    con.execute("CREATE INDEX idx_fct_exception_date ON fct_exception(as_of_date)")

    # A pre-aggregated daily summary, grained to team only — the shape every
    # warehouse accumulates. Metrics sourced from it cannot legally be sliced
    # by reason code or region, which is what the grain guard is for.
    con.execute("DROP TABLE IF EXISTS agg_team_sla")
    con.execute(
        """
        CREATE TABLE agg_team_sla AS
        SELECT
            as_of_date,
            team,
            SUM(CASE WHEN age_days > 10 AND status IN ('OPEN','PENDING') THEN 1 ELSE 0 END)
                AS breached_count,
            SUM(CASE WHEN status IN ('OPEN','PENDING') THEN 1 ELSE 0 END)
                AS total_count
        FROM fct_exception
        GROUP BY 1, 2
        """
    )

    # A view, because most of a real warehouse is views and their SQL carries
    # the business rules that column types cannot: which rows count as "open",
    # what the aging buckets are, how severity is banded.
    con.execute("DROP VIEW IF EXISTS v_open_exception")
    con.execute(
        """
        CREATE VIEW v_open_exception AS
        SELECT
            exception_id,
            as_of_date,
            team,
            reason_code,
            region,
            entity,
            vendor_tier,
            priority,
            age_days,
            amount_usd,
            CASE
                WHEN age_days > 30 THEN 'Over 30 days'
                WHEN age_days > 10 THEN '11 to 30 days'
                ELSE '10 days or less'
            END AS aging_bucket,
            CASE WHEN amount_usd > 50000 THEN TRUE ELSE FALSE END AS is_material
        FROM fct_exception
        WHERE status IN ('OPEN', 'PENDING')
        """
    )

    total, days, first, last = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT as_of_date), MIN(as_of_date), MAX(as_of_date) "
        "FROM fct_exception"
    ).fetchone()
    open_count = con.execute(
        "SELECT COUNT(*) FROM fct_exception WHERE status IN ('OPEN','PENDING')"
    ).fetchone()[0]
    con.close()

    print(f"wrote {DUCKDB_PATH}")
    print(f"  {total:,} rows over {days} days  ({first} -> {last})")
    print(f"  {open_count:,} open or pending")


if __name__ == "__main__":
    build()
