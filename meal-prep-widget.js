// Meal Prep — Scriptable home-screen widget
// Reads data.json from GitHub Pages — the compiled output of the week builder,
// the same file the web app reads, so the widget always matches the plan.
//
// SETUP (once):
//   1. Scriptable → + → paste this whole file → name it "Meal Prep".
//   2. Home screen → long-press → + → Scriptable → add a Medium widget.
//   3. Long-press the widget → Edit Widget → Script = "Meal Prep".
//      In the "Parameter" field type  him  or  her.
//      (Add it twice with different parameters for two separate tiles.)
//
// TO UPDATE THE PLAN: export week.json from builder.html into src/, run
//   python build/build.py && python build/grocery.py && python build/validate.py
// then push. The widget picks it up on its next refresh.

const GH_USER = "JohnnyMa314";
const REPO    = "meal-prep";
const BASE    = `https://${GH_USER}.github.io/${REPO}`;

// which person: widget parameter "her" -> hers, anything else -> his
const who = (args.widgetParameter || "him").toString().trim().toLowerCase() === "her" ? "her" : "him";

// palette (matches the app)
const PAPER = new Color("F7F4EE"), INK = new Color("201F1A"), MUTED = new Color("6F6A5D");

const w = new ListWidget();
w.backgroundColor = PAPER;
w.setPadding(14, 16, 14, 16);

try {
  // cache-bust so a fresh push shows up on the next refresh instead of a stale copy
  const req = new Request(`${BASE}/data.json?t=${Date.now()}`);
  req.headers = { "Cache-Control": "no-cache" };
  const data = await req.loadJSON();

  // The plan is weekdays only. If today isn't in it (weekend), fall back to the
  // first planned day and say so rather than crashing on an out-of-range index.
  const idx = (new Date().getDay() + 6) % 7;            // 0 = Monday
  const inPlan = idx < data.weekOrder.length;
  const dayKey = inPlan ? data.weekOrder[idx] : data.weekOrder[0];
  const day = data.totals[dayKey];
  if (!day || !day[who]) throw new Error(`no plan for ${dayKey}`);
  const T = day[who];

  // header: "Friday, Jul 10" on a planned day, "Monday · next up" otherwise
  const df = new DateFormatter(); df.dateFormat = "MMM d";
  const title = w.addText(inPlan ? `${day.label}, ${df.string(new Date())}` : `${day.label} · next up`);
  title.font = Font.semiboldSystemFont(15); title.textColor = INK;

  w.addSpacer(7);

  // big kcal + % of target
  const big = w.addStack(); big.bottomAlignContent();
  const n = big.addText(T.kcal.toLocaleString());
  n.font = Font.mediumSystemFont(28); n.textColor = INK;
  big.addSpacer(6);
  const pctTarget = Math.round(T.kcal / T.target * 100);
  const of = big.addText(`kcal · ${pctTarget}% of target`);
  of.font = Font.systemFont(12); of.textColor = MUTED;

  w.addSpacer(6);

  // daily totals (info only): protein · carbs · fiber — how much you're eating today
  const macros = w.addStack(); macros.centerAlignContent();
  const addMacro = (label, grams) => {
    const lb = macros.addText(label + " "); lb.font = Font.systemFont(12); lb.textColor = MUTED;
    const vv = macros.addText(grams + "g");  vv.font = Font.mediumSystemFont(12); vv.textColor = INK;
  };
  addMacro("Protein", T.p); macros.addSpacer();
  addMacro("Carbs", T.c);   macros.addSpacer();
  addMacro("Fiber", T.fib);

  w.addSpacer(9);

  // meal lines (name … kcal)
  const meals = T.meals || [];
  meals.slice(0, 4).forEach((m, i) => {
    const r = w.addStack();
    const nm = r.addText(m.name); nm.font = Font.systemFont(12); nm.textColor = MUTED; nm.lineLimit = 1;
    r.addSpacer();
    const kc = r.addText(String(m.kcal)); kc.font = Font.mediumSystemFont(12); kc.textColor = INK;
    if (i < Math.min(meals.length, 4) - 1) w.addSpacer(3);
  });

  w.addSpacer();   // absorb slack so content stays top-aligned

  // tap opens the app, jumping straight to this day
  w.url = `${BASE}/#${dayKey}`;
} catch (e) {
  const err = w.addText("Couldn't load the plan");
  err.font = Font.semiboldSystemFont(14); err.textColor = INK;
  const hint = w.addText(String((e && e.message) || e));
  hint.font = Font.systemFont(11); hint.textColor = MUTED;
}

// let iOS refresh roughly hourly (it decides the real cadence)
w.refreshAfterDate = new Date(Date.now() + 60 * 60 * 1000);

if (config.runsInWidget) Script.setWidget(w);
else w.presentMedium();
Script.complete();
