"""Monte Carlo simulation of project cost and schedule risk.

The project is fictional: the 33kV Eastvale Substation Upgrade for a made-up
company, Northvale Grid Services. All numbers are invented for learning.

Method in one paragraph
-----------------------
Each risk has a probability of happening and a three-point estimate
(minimum, most likely, maximum) for its cost and its delay. In each of
N simulated projects we (1) decide whether each risk happens, (2) if it does,
draw a cost and a delay from a triangular distribution, and (3) add everything
to the baseline estimate. The spread of the N totals gives percentiles such as
P50 and P80, which are used to set a contingency.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.ticker
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REGISTER_PATH = ROOT / "data" / "risk_register.csv"
OUTPUT_DIR = ROOT / "outputs"

# Baseline estimate before any discrete risks (cost in GBP thousands, time in weeks).
# "Base uncertainty" is the normal estimating error on the baseline itself:
# (minimum, most likely, maximum).
BASELINE_COST_K = 12_000
BASELINE_WEEKS = 52
BASE_COST_TRI = (11_400, 12_000, 13_200)
BASE_WEEKS_TRI = (48, 52, 60)

# Not every delay lands on the critical path (some work runs in parallel).
# Assumption: 60% of each risk delay extends the overall programme.
CRITICAL_PATH_SHARE = 0.60

N_RUNS = 10_000
SEED = 42


def triangular_inverse(u, low, likely, high):
    """Turn uniform random numbers u (0 to 1) into triangular(low, likely, high) values.

    This is the inverse of the triangular cumulative distribution. numpy has
    rng.triangular, but writing it out makes the method visible and matches
    the formula used in the Excel version.
    """
    u = np.asarray(u, dtype=float)
    split = (likely - low) / (high - low)
    left = low + np.sqrt(u * (high - low) * (likely - low))
    right = high - np.sqrt((1 - u) * (high - low) * (high - likely))
    return np.where(u < split, left, right)


def load_register(path=REGISTER_PATH):
    return pd.read_csv(path)


def simulate(register, n_runs=N_RUNS, seed=SEED):
    """Run the simulation and return one row per simulated project."""
    rng = np.random.default_rng(seed)
    out = {}

    # Baseline estimating uncertainty
    out["Baseline estimate"] = triangular_inverse(rng.random(n_runs), *BASE_COST_TRI)
    base_weeks = triangular_inverse(rng.random(n_runs), *BASE_WEEKS_TRI)

    delay_cols = {}
    for r in register.itertuples(index=False):
        happens = rng.random(n_runs) < r.probability
        # The same random draw drives cost and delay, so a "bad" outcome is bad on both.
        u = rng.random(n_runs)
        cost = triangular_inverse(u, r.cost_min_k, r.cost_likely_k, r.cost_max_k)
        delay = triangular_inverse(u, r.delay_min_wks, r.delay_likely_wks, r.delay_max_wks)
        out[f"{r.risk_id} {r.risk}"] = np.where(happens, cost, 0.0)
        delay_cols[r.risk_id] = np.where(happens, delay, 0.0)

    results = pd.DataFrame(out)
    results["Total cost (GBP k)"] = results.sum(axis=1)
    # Simplifying assumption: a fixed share of each delay reaches the critical path.
    results["Total duration (weeks)"] = base_weeks + CRITICAL_PATH_SHARE * sum(delay_cols.values())
    return results


def percentile_table(results):
    rows = []
    for col, baseline in [("Total cost (GBP k)", BASELINE_COST_K),
                          ("Total duration (weeks)", BASELINE_WEEKS)]:
        s = results[col]
        rows.append({
            "measure": col,
            "baseline": baseline,
            "mean": s.mean(),
            "P50": s.quantile(0.50),
            "P80": s.quantile(0.80),
            "P90": s.quantile(0.90),
            "contingency_at_P80": s.quantile(0.80) - baseline,
            "chance_of_finishing_within_baseline": (s <= baseline).mean(),
        })
    return pd.DataFrame(rows).round(3)


def sensitivity(results):
    """Rank correlation of each cost driver with the total cost."""
    drivers = [c for c in results.columns if not c.startswith("Total")]
    corr = results[drivers + ["Total cost (GBP k)"]].rank().corr()["Total cost (GBP k)"]
    return corr.drop("Total cost (GBP k)").sort_values(ascending=False)


# ---------- charts ----------
BLUE, ORANGE, GREY = "#1F3864", "#C55A11", "#7F7F7F"


def _style(ax, title, xlabel, ylabel):
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", color=BLUE)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.spines[["top", "right"]].set_visible(False)


def plot_histogram(series, baseline, title, xlabel, path=None):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.hist(series, bins=60, color=BLUE, alpha=0.85)
    for q, colour in [(0.5, GREY), (0.8, ORANGE)]:
        v = series.quantile(q)
        ax.axvline(v, color=colour, linestyle="--", linewidth=2)
        ax.text(v, ax.get_ylim()[1] * (0.97 if q == 0.5 else 0.88), f" P{int(q * 100)}: {v:,.0f} ",
                color=colour, va="top", fontsize=10,
                bbox=dict(facecolor="white", edgecolor="none", pad=1.5))
    ax.axvline(baseline, color="black", linewidth=1.5)
    ax.text(baseline, ax.get_ylim()[1] * 0.97, f" Baseline: {baseline:,.0f} ", ha="right",
            fontsize=10, va="top", bbox=dict(facecolor="white", edgecolor="none", pad=1.5))
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    _style(ax, title, xlabel, "Number of simulated projects")
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=150)
    return fig


def plot_s_curve(series, baseline, title, xlabel, path=None):
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.sort(series.values)
    y = np.arange(1, len(x) + 1) / len(x)
    ax.plot(x, y, color=BLUE, linewidth=2)
    for q in (0.5, 0.8, 0.9):
        v = series.quantile(q)
        ax.plot([x.min(), v], [q, q], color=GREY, linestyle=":")
        ax.plot([v, v], [0, q], color=GREY, linestyle=":")
        ax.text(v, q - 0.06, f"P{int(q * 100)} = {v:,.0f}", ha="left", fontsize=9)
    ax.axvline(baseline, color="black", linewidth=1.5)
    ax.set_ylim(0, 1.02)
    _style(ax, title, xlabel, "Chance of finishing at or below this value")
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=150)
    return fig


def plot_tornado(corr, path=None):
    fig, ax = plt.subplots(figsize=(8, 5))
    s = corr.sort_values()
    labels = [i.split(" ", 1)[1] if i[0] == "R" else i for i in s.index]
    ax.barh(labels, s.values, color=BLUE)
    _style(ax, "What drives the total cost", "Rank correlation with total cost", "")
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=150)
    return fig


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    register = load_register()
    results = simulate(register)
    table = percentile_table(results)
    drivers = sensitivity(results)

    table.to_csv(OUTPUT_DIR / "results_summary.csv", index=False)
    drivers.rename("rank_correlation_with_total_cost").to_csv(OUTPUT_DIR / "cost_drivers.csv")

    cost, weeks = results["Total cost (GBP k)"], results["Total duration (weeks)"]
    plot_histogram(cost, BASELINE_COST_K, "Total project cost, 10,000 simulated projects",
                   "Total cost (GBP thousands)", OUTPUT_DIR / "cost_histogram.png")
    plot_s_curve(cost, BASELINE_COST_K, "Cost S-curve", "Total cost (GBP thousands)",
                 OUTPUT_DIR / "cost_s_curve.png")
    plot_histogram(weeks, BASELINE_WEEKS, "Project duration, 10,000 simulated projects",
                   "Duration (weeks)", OUTPUT_DIR / "schedule_histogram.png")
    plot_tornado(drivers, OUTPUT_DIR / "cost_drivers.png")

    print(table.to_string(index=False))
    print("\nTop cost drivers (rank correlation with total cost):")
    print(drivers.round(2).to_string())


if __name__ == "__main__":
    main()
