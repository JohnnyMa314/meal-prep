#!/usr/bin/env python3
"""
validate.py — the logic layer. Checks that the calorie/macro information is
internally consistent and that everything sums up, at four levels:

  1. Ingredient : stated kcal vs macro-implied kcal (Atwater 4/4/9)         [warn]
  2. Meal       : each meal's kcal == 4*P + 4*C + 9*F of its own macros     [warn]
  3. Day        : totals[day][who].kcal == sum(meal kcals) + shake          [FAIL]
  4. Cross-file : data.json reproduces from src/, grocery.json reproduces
                  from src/, and grocery.json sums from data.json's meals    [FAIL]
  5. Plan       : weekday protein floors + kcal within 15% of target        [warn]

Run before pushing (Phase 5 calls this). Exits non-zero if any hard check FAILS.

    python build/validate.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build as B          # noqa: E402
import grocery as G        # noqa: E402

ROOT = B.ROOT
SLOTS = ["breakfast", "lunch", "dinner"]
WEEKEND = {"saturday", "sunday"}
FLOOR = {"him": 180, "her": 100}

ATWATER_WARN = 0.15   # relative deviation flagged at ingredient level
MEAL_WARN = 0.12      # relative deviation flagged at meal level
KCAL_OFF = 0.15       # plan: day kcal allowed to be this far off target

n_fail = 0
n_warn = 0


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def hdr(t):
    print(f"\n{t}")
    print("-" * len(t))


def ok(msg):
    print(f"  [PASS] {msg}")


def warn(msg):
    global n_warn
    n_warn += 1
    print(f"  [WARN] {msg}")


def fail(msg):
    global n_fail
    n_fail += 1
    print(f"  [FAIL] {msg}")


def nut_of(nutrition, ing, amt):
    n = nutrition[ing]
    k = amt / 100.0 if n["basis"] == "100g" else amt
    return {m: n[m] * k for m in ("kcal", "p", "c", "fib", "f")}


def comp_totals(nutrition, comps, who):
    t = {m: 0.0 for m in ("kcal", "p", "c", "fib", "f")}
    for cp in comps:
        a = cp[who]
        if a:
            x = nut_of(nutrition, cp["ing"], a)
            for m in t:
                t[m] += x[m]
    return t


def atwater(p, c, f, fib=0):
    # Fiber-aware: dietary fiber yields ~2 kcal/g, not 4, and "carbs" here include it.
    return 4 * p + 4 * c + 9 * f - 2 * fib


def main():
    ingredients = load_json(os.path.join(B.SRC, "ingredients.json"))
    data = load_json(os.path.join(ROOT, "data.json"))
    grocery = load_json(os.path.join(ROOT, "grocery.json"))
    nutrition = data["nutrition"]

    # ---------- 1. ingredient calorie sanity ----------
    hdr("1. Ingredient calories vs macros (Atwater 4/4/9)")
    worst = None
    for ing, spec in ingredients.items():
        if ing.startswith("_"):
            continue
        implied = atwater(spec["p"], spec["c"], spec["f"], spec["fib"])
        kcal = spec["kcal"]
        rel = abs(kcal - implied) / max(kcal, 1)
        if worst is None or rel > worst[1]:
            worst = (spec["name"], rel, kcal, implied)
        if rel > ATWATER_WARN:
            warn(f"{spec['name']}: stated {kcal} kcal vs macro-implied {implied:.0f} "
                 f"({rel * 100:.0f}% off) -- check p/c/f or accept as a known outlier")
    if worst:
        ok(f"{sum(1 for k in ingredients if not k.startswith('_'))} ingredients checked; "
           f"largest gap {worst[0]} at {worst[1] * 100:.0f}%")

    # ---------- 2. meal calories vs its own macros ----------
    hdr("2. Meal calories vs macros")
    meals = load_json(os.path.join(B.SRC, "meals.json"))
    flagged = 0
    for mid, m in meals.items():
        if mid.startswith("_"):
            continue
        t = comp_totals(nutrition, m["components"], "him")
        if t["kcal"] == 0:
            continue
        implied = atwater(t["p"], t["c"], t["f"], t["fib"])
        rel = abs(t["kcal"] - implied) / t["kcal"]
        if rel > MEAL_WARN:
            flagged += 1
            warn(f"{m['name']}: {t['kcal']:.0f} kcal vs {implied:.0f} from macros ({rel * 100:.0f}% off)")
    if not flagged:
        ok(f"all {sum(1 for k in meals if not k.startswith('_'))} meals: calories agree with macros within {MEAL_WARN * 100:.0f}%")

    # ---------- 3. day totals sum up ----------
    hdr("3. Day totals = sum of meals (+ shake)")
    day_bad = 0
    for dk in data["weekOrder"]:
        for who in ("him", "her"):
            entry = data["totals"][dk][who]
            meal_sum = sum(mm["kcal"] for mm in entry["meals"])
            day_kcal = entry["kcal"]
            drift = abs(day_kcal - meal_sum)
            tol = len(entry["meals"]) + 1   # each meal kcal is independently rounded
            if drift > tol:
                day_bad += 1
                fail(f"{dk} {who}: day {day_kcal} != sum of meals {meal_sum} (drift {drift} > {tol})")
    if not day_bad:
        ok("every day/person: stored total matches the sum of its meal lines (within rounding)")

    # ---------- 4a. reproduction from src ----------
    hdr("4. Cross-file consistency")
    d_diffs = B.diff(B.build(), data)
    if d_diffs:
        fail(f"data.json does NOT reproduce from src/ ({len(d_diffs)} diffs, first: {d_diffs[0]})")
    else:
        ok("data.json reproduces exactly from src/ (build.py)")

    g_diffs = B.diff(G.compute(), grocery)
    if g_diffs:
        fail(f"grocery.json does NOT reproduce from src/ ({len(g_diffs)} diffs, first: {g_diffs[0]})")
    else:
        ok("grocery.json reproduces exactly from src/ (grocery.py)")

    # ---------- 4b. grocery sums from data.json's meals (independent path) ----------
    cooked, count = {}, {}
    for dk in data["weekOrder"]:
        day = data["days"][dk]
        for meal in day["meals"]:
            for cp in meal["comps"]:
                amt = cp["him"] + cp["her"]
                if not amt:
                    continue
                if nutrition[cp["ing"]]["basis"] == "unit":
                    count[cp["ing"]] = count.get(cp["ing"], 0) + amt
                else:
                    cooked[cp["ing"]] = cooked.get(cp["ing"], 0) + amt
        sh = day["shake"]
        count["koia"] = count.get("koia", 0) + sh["him"] + sh["her"]

    grocery_bad = 0
    for line in grocery["order"]:
        members = line["members"]
        if line.get("cooked_g") is not None:
            want = sum(cooked.get(mm, 0) for mm in members)
            if abs(want - line["cooked_g"]) > 0.5:
                grocery_bad += 1
                fail(f"grocery '{line['name']}': cooked_g {line['cooked_g']} != meals sum {want:.1f}")
        if line.get("count") is not None:
            want = sum(count.get(mm, 0) for mm in members)
            if abs(want - line["count"]) > 1e-6:
                grocery_bad += 1
                fail(f"grocery '{line['name']}': count {line['count']} != meals sum {want}")
    if not grocery_bad:
        ok("every grocery line sums from the actual meals in data.json")

    # ---------- 5. plan hits targets (weekdays) ----------
    hdr("5. Plan vs targets (weekdays only; weekends are breakfast-only by design)")
    plan_bad = 0
    for dk in data["weekOrder"]:
        if dk in WEEKEND:
            continue
        for who in ("him", "her"):
            e = data["totals"][dk][who]
            tgt = data["targets"][who]
            if e["p"] < FLOOR[who]:
                plan_bad += 1
                warn(f"{dk} {who}: protein {e['p']}g below floor {FLOOR[who]}g")
            off = abs(e["kcal"] - tgt["kcal"]) / tgt["kcal"]
            if off > KCAL_OFF:
                plan_bad += 1
                warn(f"{dk} {who}: {e['kcal']} kcal is {off * 100:.0f}% off target {tgt['kcal']}")
    if not plan_bad:
        ok("all weekdays: protein floors met and kcal within 15% of target")

    # ---------- summary ----------
    print()
    print("=" * 58)
    status = "FAILED" if n_fail else ("PASSED (with warnings)" if n_warn else "PASSED")
    print(f"Validation {status}: {n_fail} failure(s), {n_warn} warning(s).")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
