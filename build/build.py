#!/usr/bin/env python3
"""
build.py — compile the three hand-edited source files into data.json.

    src/ingredients.json  (nutrition + labels + grocery block)
    src/meals.json        (favorites library)
    src/week.json         (assignment: day/slot -> meal_id, shakes, targets, weekId)
        |
        v
    data.json             (SAME SHAPE the app + widget already consume)

Phase 1 is a pure refactor: the emitted data.json must be semantically identical
to the current one. Run `python build/verify.py` to prove it.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")

SLOT_LABEL = {"breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner"}
SLOT_ORDER = ["breakfast", "lunch", "dinner"]
SHAKE_ING = "koia"


def rnd(x):
    """Round half to even (banker's) — matches how the committed totals block was generated.
    Python's built-in round() already does this; kept as a named helper for clarity."""
    return int(round(x))


def load(name):
    with open(os.path.join(SRC, name), encoding="utf-8") as f:
        return json.load(f)


def nut_of(nutrition, ing, amt):
    n = nutrition[ing]
    k = amt / 100.0 if n["basis"] == "100g" else amt
    return {m: n[m] * k for m in ("kcal", "p", "c", "fib", "f")}


def meal_totals(nutrition, comps, who):
    t = {m: 0.0 for m in ("kcal", "p", "c", "fib", "f")}
    for cp in comps:
        a = cp[who]
        if a:
            x = nut_of(nutrition, cp["ing"], a)
            for m in t:
                t[m] += x[m]
    return t


def build():
    ingredients = load("ingredients.json")
    meals = load("meals.json")
    week = load("week.json")

    # nutrition + labels: every real ingredient (skip _comment), grocery block stripped.
    nutrition, labels = {}, {}
    for ing, spec in ingredients.items():
        if ing.startswith("_"):
            continue
        nutrition[ing] = {k: spec[k] for k in ("basis", "kcal", "p", "c", "fib", "f")}
        labels[ing] = {"name": spec["name"], "unit": spec["unit"]}

    targets = week["targets"]
    order = week["weekOrder"]

    days = {}
    for dk in order:
        wd = week["days"][dk]
        meal_objs = []
        for slot in SLOT_ORDER:
            if slot not in wd["slots"]:
                continue
            sv = wd["slots"][slot]
            if isinstance(sv, str):
                mid, note_override = sv, None
            else:
                mid, note_override = sv["meal"], sv.get("note", None)
            m = meals[mid]
            obj = {"name": SLOT_LABEL[slot] + " — " + m["name"], "tag": m["tag"]}
            if m.get("lpr"):
                obj["lpr"] = True
            note = note_override if note_override is not None else m.get("note", "")
            if note:
                obj["note"] = note
            obj["comps"] = [dict(cp) for cp in m["components"]]
            # stash the clean name for the totals block
            obj["_clean"] = m["name"]
            meal_objs.append(obj)

        days[dk] = {
            "label": wd["label"],
            "sub": wd["sub"],
            "meals": [{k: v for k, v in mo.items() if k != "_clean"} for mo in meal_objs],
            "shake": {"ing": SHAKE_ING, "him": wd["shake"]["him"], "her": wd["shake"]["her"]},
        }

    # precomputed totals block (consumed only by the Scriptable widget)
    totals = {}
    for dk in order:
        wd = week["days"][dk]
        # rebuild meal_objs with clean names for this day
        day_meals = []
        for slot in SLOT_ORDER:
            if slot not in wd["slots"]:
                continue
            sv = wd["slots"][slot]
            mid = sv if isinstance(sv, str) else sv["meal"]
            day_meals.append(meals[mid])

        entry = {"label": wd["label"], "sub": wd["sub"]}
        for who in ("him", "her"):
            floor = 180 if who == "him" else 100
            tot = {m: 0.0 for m in ("kcal", "p", "c", "fib", "f")}
            mlist = []
            for m in day_meals:
                mt = meal_totals(nutrition, m["components"], who)
                for k in tot:
                    tot[k] += mt[k]
                if mt["kcal"] > 0:
                    mlist.append({"name": m["name"], "kcal": rnd(mt["kcal"])})
            sk = wd["shake"][who]
            if sk:
                x = nut_of(nutrition, SHAKE_ING, sk)
                for k in tot:
                    tot[k] += x[k]
                mlist.append({"name": labels[SHAKE_ING]["name"], "kcal": rnd(x["kcal"])})
            entry[who] = {
                "kcal": rnd(tot["kcal"]), "p": rnd(tot["p"]), "c": rnd(tot["c"]),
                "fib": rnd(tot["fib"]), "f": rnd(tot["f"]),
                "floorMet": tot["p"] >= floor,
                "target": targets[who]["kcal"], "ptarget": targets[who]["p"],
                "meals": mlist,
            }
        totals[dk] = entry

    return {
        "nutrition": nutrition,
        "labels": labels,
        "targets": targets,
        "days": days,
        "weekOrder": order,
        "weekId": week["weekId"],
        "totals": totals,
    }


def diff(a, b, path="$"):
    """Recursively collect semantic differences between two JSON structures."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k not in b:
                out.append(f"{path}.{k} : only in candidate")
        for k in b:
            if k not in a:
                out.append(f"{path}.{k} : only in committed")
        for k in a:
            if k in b:
                out += diff(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path} : array len {len(a)} vs {len(b)}")
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                out += diff(x, y, f"{path}[{i}]")
    elif isinstance(a, bool) or isinstance(b, bool):
        if bool(a) != bool(b):
            out.append(f"{path} : bool {a} vs {b}")
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if abs(a - b) > 1e-6:
            out.append(f"{path} : num {a} vs {b}")
    elif a != b:
        out.append(f"{path} : {a!r} vs {b!r}")
    return out


def main():
    data = build()
    if "--verify" in sys.argv:
        with open(os.path.join(ROOT, "data.json"), encoding="utf-8") as f:
            committed = json.load(f)
        diffs = diff(data, committed)
        if not diffs:
            print("PASS: candidate data.json is semantically identical to committed data.json.")
        else:
            print(f"FAIL: {len(diffs)} difference(s):")
            for d in diffs[:40]:
                print("  " + d)
            sys.exit(1)
        return
    out = os.path.join(ROOT, "data.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print("wrote", out)


if __name__ == "__main__":
    main()
