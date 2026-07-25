#!/usr/bin/env python3
"""
archive.py — snapshot the outgoing week into history/ before it's overwritten.

Runs BEFORE build.py. If src/week.json now carries a different weekId than the
currently committed data.json, the old compiled week is still on disk — so copy
it into history/<old-weekId>/ along with a human-readable plan + grocery list.

Idempotent: if that week is already archived, it does nothing.

    python build/archive.py
"""

import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
HIST = os.path.join(ROOT, "history")
SLOT_ORDER = ["breakfast", "lunch", "dinner"]


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def plan_markdown(data, grocery):
    """The paired record: what was planned, and what was bought for it."""
    wid = data.get("weekId", "unknown")
    out = [f"# Week {wid}", ""]

    out += ["## Grocery list", ""]
    if grocery:
        for line in grocery.get("order", []):
            out.append(f"- **{line['name']}** — {line['display']}")
        if grocery.get("staples"):
            out.append("")
            out.append(f"_Staples (buy when low): {', '.join(grocery['staples'])}_")
    else:
        out.append("_(no grocery.json at archive time)_")

    out += ["", "## Targets", ""]
    for who in ("him", "her"):
        t = data["targets"][who]
        out.append(f"- **{who}** — {t['kcal']} kcal · {t['p']}g P · {t['c']}g C · "
                   f"{t['fib']}g fiber · {t['f']}g fat")

    out += ["", "## Meal plan", "", "Amounts are **his / hers**.", ""]
    for dk in data["weekOrder"]:
        day = data["days"][dk]
        tot = data["totals"][dk]
        out.append(f"### {day['label']}")
        out.append(f"_his {tot['him']['kcal']} kcal / {tot['him']['p']}g P · "
                   f"hers {tot['her']['kcal']} / {tot['her']['p']}g P_")
        out.append("")
        for meal in day["meals"]:
            items = []
            for cp in meal["comps"]:
                if not (cp["him"] or cp["her"]):
                    continue
                lab = data["labels"][cp["ing"]]
                items.append(f"{lab['name']} {cp['him']}/{cp['her']}{lab['unit']}")
            out.append(f"- **{meal['name']}** — " + ", ".join(items))
            if meal.get("note"):
                out.append(f"  - _{meal['note']}_")
        sh = day.get("shake", {})
        if sh.get("him") or sh.get("her"):
            out.append(f"- **Koia shake** — {sh.get('him', 0)}/{sh.get('her', 0)} bottle")
        out.append("")
    return "\n".join(out) + "\n"


def main():
    data_path = os.path.join(ROOT, "data.json")
    grocery_path = os.path.join(ROOT, "grocery.json")
    if not os.path.exists(data_path):
        print("archive: no data.json yet — nothing to archive")
        return

    old = load(data_path)
    old_id = old.get("weekId")
    new_id = load(os.path.join(SRC, "week.json")).get("weekId")

    if not old_id or old_id == new_id:
        print(f"archive: weekId unchanged ({old_id}) — nothing to archive")
        return

    dest = os.path.join(HIST, old_id)
    if os.path.exists(dest):
        print(f"archive: {old_id} already archived")
        return

    os.makedirs(dest, exist_ok=True)
    shutil.copy2(data_path, os.path.join(dest, "data.json"))
    # the sources are already the NEW week, so only the compiled data.json holds
    # the old plan — keep it plus the readable pair below

    grocery = None
    if os.path.exists(grocery_path):
        shutil.copy2(grocery_path, os.path.join(dest, "grocery.json"))
        grocery = load(grocery_path)

    with open(os.path.join(dest, "plan.md"), "w", encoding="utf-8") as f:
        f.write(plan_markdown(old, grocery))

    print(f"archive: saved {old_id} -> history/{old_id}/ (now planning {new_id})")


if __name__ == "__main__":
    main()
