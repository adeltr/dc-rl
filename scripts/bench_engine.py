"""Mesure du temps d'une simulation annuelle (sans cache) et décision surrogate (> 3 s)."""
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twin.engine import simulate  # noqa: E402
from twin.params import TwinParams  # noqa: E402

SURROGATE_THRESHOLD_S = 3.0
CASES = {
    "base (NY, 20 MW, charge 100 %)": {"site_id": "us_ny_jfk"},
    "trace Alibaba": {"site_id": "us_ny_jfk", "load": {"mode": "trace"}},
    "batterie + tarif horaire": {"site_id": "us_ny_jfk", "battery": {"power_mw": 10, "energy_mwh": 40},
                                 "price": {"mode": "tou", "tou_default_usd_per_mwh": 90, "tou_periods": [
                                     {"price_usd_per_mwh": 220, "start_hour": 17, "end_hour": 21}]}},
    "campus 200 MW (10 halls)": {"site_id": "us_va_leesburg", "geometry": {"n_halls": 10, "kw_per_rack": 40}},
}

if __name__ == "__main__":
    simulate(TwinParams(site_id="us_ny_jfk"))  # chauffe : imports, lecture des fichiers
    worst = 0.0
    for name, cfg in CASES.items():
        durations = []
        for _ in range(5):
            t0 = time.perf_counter()
            simulate(TwinParams.model_validate(cfg))
            durations.append(time.perf_counter() - t0)
        median = statistics.median(durations)
        worst = max(worst, max(durations))
        print(f"{name:34s} médiane {median:.3f} s   max {max(durations):.3f} s")
    decision = "surrogate requis" if worst > SURROGATE_THRESHOLD_S else "surrogate non requis"
    print(f"pire cas {worst:.3f} s (seuil {SURROGATE_THRESHOLD_S} s) -> {decision}")
