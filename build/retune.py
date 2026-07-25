#!/usr/bin/env python3
"""
retune.py — re-portion saved recipes so the week hits the current macro targets.

When targets change, the saved recipes in meals.json still carry their old
portions. This nudges each recipe's component amounts (protein down / carb up /
added-fat down, etc.) until every day's totals land near target.

Recipes are shared across days (egg scramble runs Mon + Fri), so this is a
least-squares fit across the whole week rather than a per-day solve: each day
proposes a correction, and a recipe applies the average of the days it appears in.

    python build/retune.py            # dry run — show the diff, change nothing
    python build/retune.py --write    # apply to src/meals.json

By default only `him` is retuned (`--who her` for hers). Veg, fruit and oils are
left alone; milk is scaled with oats so the overnight-oats hydration ratio holds.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
SLOTS = ["breakfast", "lunch", "dinner"]
MACROS = ("kcal", "p", "c", "fib", "f")

# which roles move, and in which direction the error pushes them
ADJUST_ROLES = {"protein", "carb"}
FAT_INGS = {"avocado", "cheese", "olive_oil", "sesame_oil", "butter"}   # fat levers
FIXED_INGS = {"chia"}                     # chia is a fixed 10g garnish
LINK_TO_OATS = "milk"                     # keep the 1:2 oats:liquid ratio

BOUNDS = {                                # (min_factor, max_factor) vs original
    "default": (0.45, 2.6),
    "tortilla": (1.0, 2.0),               # a big wrap can take a second tortilla
    "egg": (0.67, 1.67),
}
# Absolute sanity bounds — what a portion should actually look like on a plate.
# Without these the fit is happy to serve a 400g sweet potato next to an 85g steak.
# The legume caps also hold fiber down: lentils/beans are the fiber bombs.
ABS = {
    "ground_beef": (110, 240), "chicken_breast": (110, 240), "chicken_thigh": (110, 240),
    "shrimp": (110, 240), "steak": (130, 230), "egg": (2, 4),
    "greek_yogurt": (120, 220), "edamame": (30, 110),
    "rice": (110, 360), "farro": (110, 330), "lentils": (60, 200), "beans": (0, 140),
    "sweet_potato": (110, 360), "oats": (40, 110), "tortilla": (100, 200),
    "avocado": (0, 90), "cheese": (0, 30), "milk": (120, 300),
    "olive_oil": (1, 4), "sesame_oil": (1, 4), "butter": (1, 3),
}
WEIGHT = {"p": 1.0, "c": 0.85, "f": 0.9, "fib": 1.1}   # fiber pushes back hard
ABS_MIN = 5.0
ITERS, DAMP = 500, 0.25


def load(name):
    with open(os.path.join(SRC, name), encoding="utf-8") as f:
        return json.load(f)


def nut(ing_tbl, ing, amt):
    n = ing_tbl[ing]
    k = amt / 100.0 if n["basis"] == "100g" else amt
    return {m: n[m] * k for m in MACROS}


def day_recipes(week, meals):
    """[(day_key, [recipe_id, ...]), ...] — only string-id slots can be retuned."""
    out = []
    for dk in week["weekOrder"]:
        ids = []
        for sk in SLOTS:
            sv = week["days"][dk]["slots"].get(sk)
            if isinstance(sv, str):
                ids.append(sv)
            elif isinstance(sv, dict) and "meal" in sv:
                ids.append(sv["meal"])
        out.append((dk, ids))
    return out


def totals_for(ing_tbl, meals, amounts, ids, shake, who):
    t = {m: 0.0 for m in MACROS}
    for rid in ids:
        for i, cp in enumerate(meals[rid]["components"]):
            a = amounts[(rid, i)] if who == "him" else cp["her"]
            if a:
                x = nut(ing_tbl, cp["ing"], a)
                for m in t:
                    t[m] += x[m]
    if shake:
        x = nut(ing_tbl, "koia", shake)
        for m in t:
            t[m] += x[m]
    return t


def bounds_for(ing):
    return BOUNDS.get(ing, BOUNDS["default"])


def round_amt(ing_tbl, ing, x):
    if ing_tbl[ing]["basis"] == "unit":
        return max(1.0, round(x))
    return max(ABS_MIN, round(x / 5.0) * 5.0)


def main():
    write = "--write" in sys.argv
    who = "her" if "--who" in sys.argv and sys.argv[sys.argv.index("--who") + 1] == "her" else "him"

    ing_tbl = {k: v for k, v in load("ingredients.json").items() if not k.startswith("_")}
    meals = load("meals.json")
    week = load("week.json")
    tgt = week["targets"][who]
    drs = day_recipes(week, meals)

    used = sorted({rid for _, ids in drs for rid in ids})
    orig = {}
    for rid in used:
        for i, cp in enumerate(meals[rid]["components"]):
            orig[(rid, i)] = float(cp[who])
    amounts = dict(orig)

    # which components are levers, by role
    def role(ing):
        r = ing_tbl[ing].get("role", "extra")
        if ing in FAT_INGS:
            return "fat"
        return r

    for _ in range(ITERS):
        prop = {}                                  # (rid,i) -> [deltas]
        for dk, ids in drs:
            shake = week["days"][dk]["shake"][who]
            t = totals_for(ing_tbl, meals, amounts, ids, shake, who)
            err = {k: t[k] - tgt[k] for k in ("p", "c", "f", "fib")}
            # contribution pools for this day
            pools = {"p": [], "c": [], "f": [], "fib": []}
            for rid in ids:
                for i, cp in enumerate(meals[rid]["components"]):
                    ing, a = cp["ing"], amounts[(rid, i)]
                    if a <= 0 or ing in FIXED_INGS or ing == LINK_TO_OATS:
                        continue
                    r = role(ing)
                    if r == "protein" and "protein" in ADJUST_ROLES:
                        pools["p"].append((rid, i, nut(ing_tbl, ing, a)["p"]))
                    elif r == "carb" and "carb" in ADJUST_ROLES:
                        pools["c"].append((rid, i, nut(ing_tbl, ing, a)["c"]))
                        # carbs also carry the fiber correction: when fiber is over,
                        # this pulls the legumes down and lets rice/potato take over
                        pools["fib"].append((rid, i, nut(ing_tbl, ing, a)["fib"]))
                    elif r == "fat":
                        pools["f"].append((rid, i, nut(ing_tbl, ing, a)["f"]))
            for key in ("p", "c", "f", "fib"):
                pool = pools[key]
                tot = sum(x[2] for x in pool)
                if tot <= 0 or abs(err[key]) < 1e-9:
                    continue
                for rid, i, contrib in pool:
                    ing = meals[rid]["components"][i]["ing"]
                    per = nut(ing_tbl, ing, 1.0)[key]          # macro per gram/unit
                    if per <= 0:
                        continue
                    d = -err[key] * WEIGHT[key] * (contrib / tot) / per
                    prop.setdefault((rid, i), []).append(d)

        moved = 0.0
        for key, ds in prop.items():
            d = sum(ds) / len(ds)                              # shared recipes: average
            rid, i = key
            ing = meals[rid]["components"][i]["ing"]
            lo, hi = bounds_for(ing)
            alo, ahi = ABS.get(ing, (ABS_MIN, 1e9))
            new = amounts[key] + DAMP * d
            new = max(max(orig[key] * lo, alo), min(min(orig[key] * hi, ahi), new))
            moved += abs(new - amounts[key])
            amounts[key] = new
        if moved < 0.5:
            break

    # keep the oats:liquid ratio — milk follows oats within each recipe
    for rid in used:
        comps = meals[rid]["components"]
        oats_idx = [i for i, c in enumerate(comps) if c["ing"] == "oats"]
        milk_idx = [i for i, c in enumerate(comps) if c["ing"] == LINK_TO_OATS]
        if oats_idx and milk_idx:
            i0 = oats_idx[0]
            f = amounts[(rid, i0)] / orig[(rid, i0)] if orig[(rid, i0)] else 1.0
            for j in milk_idx:
                amounts[(rid, j)] = orig[(rid, j)] * f

    for key in amounts:
        rid, i = key
        amounts[key] = round_amt(ing_tbl, meals[rid]["components"][i]["ing"], amounts[key])

    # ---- report ----
    print(f"Retuning `{who}` amounts to: "
          f"{tgt['kcal']} kcal · {tgt['p']}g P · {tgt['c']}g C · {tgt['fib']}g fib · {tgt['f']}g fat\n")
    changed = [(k, orig[k], amounts[k]) for k in sorted(amounts) if orig[k] != amounts[k]]
    cur_rid = None
    for (rid, i), o, n in changed:
        if rid != cur_rid:
            print(f"  {meals[rid]['name']}  [{rid}]")
            cur_rid = rid
        ing = meals[rid]["components"][i]["ing"]
        u = ing_tbl[ing]["unit"]
        print(f"      {ing_tbl[ing]['name']:<22} {o:>6.0f}{u} -> {n:>6.0f}{u}   ({n - o:+.0f})")
    print(f"\n  {len(changed)} component amount(s) changed across {len({r for (r, _), _, _ in changed})} recipe(s).\n")

    print(f"  {'DAY':<11}{'KCAL':>16}{'PROTEIN':>14}{'CARB':>13}{'FIBER':>12}{'FAT':>12}")
    print("  " + "-" * 76)
    acc = {m: 0.0 for m in MACROS}
    for dk, ids in drs:
        t = totals_for(ing_tbl, meals, amounts, ids, week["days"][dk]["shake"][who], who)
        for m in acc:
            acc[m] += t[m]
        print(f"  {week['days'][dk]['label']:<11}"
              f"{t['kcal']:>10.0f} ({t['kcal'] - tgt['kcal']:+4.0f})"
              f"{t['p']:>8.0f} ({t['p'] - tgt['p']:+4.0f})"
              f"{t['c']:>7.0f} ({t['c'] - tgt['c']:+4.0f})"
              f"{t['fib']:>6.0f} ({t['fib'] - tgt['fib']:+4.0f})"
              f"{t['f']:>6.0f} ({t['f'] - tgt['f']:+4.0f})")
    n = len(drs)
    print("  " + "-" * 76)
    print(f"  {'AVG':<11}"
          f"{acc['kcal'] / n:>10.0f} ({acc['kcal'] / n - tgt['kcal']:+4.0f})"
          f"{acc['p'] / n:>8.0f} ({acc['p'] / n - tgt['p']:+4.0f})"
          f"{acc['c'] / n:>7.0f} ({acc['c'] / n - tgt['c']:+4.0f})"
          f"{acc['fib'] / n:>6.0f} ({acc['fib'] / n - tgt['fib']:+4.0f})"
          f"{acc['f'] / n:>6.0f} ({acc['f'] / n - tgt['f']:+4.0f})")

    if not write:
        print("\n  (dry run — nothing written. Re-run with --write to apply.)")
        return
    for (rid, i), amt in amounts.items():
        v = int(amt) if float(amt).is_integer() else amt
        meals[rid]["components"][i][who] = v
    with open(os.path.join(SRC, "meals.json"), "w", encoding="utf-8") as f:
        json.dump(meals, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("\n  wrote src/meals.json")


if __name__ == "__main__":
    main()
