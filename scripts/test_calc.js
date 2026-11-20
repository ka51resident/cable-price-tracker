// Checks the quote maths against hand-worked examples. Run: node scripts/test_calc.js
const assert = require("assert");
const Calc = require("../assets/calc.js");
const near = (a, b, tol) => assert.ok(Math.abs(a - b) <= tol, `${a} not within ${tol} of ${b}`);

// Conductor area and weight
assert.strictEqual(Calc.conductorArea(4, 25), 100);
assert.strictEqual(Calc.conductorArea(3.5, 240), 840);   // 3 x 240 + 120
assert.strictEqual(Calc.conductorArea(3.5, 35), 121);    // 3 x 35 + 16
assert.strictEqual(Calc.conductorArea(3.5, 10), null);   // not a real cable
near(Calc.metalKgPerM("al", 100), 0.2703, 1e-9);
near(Calc.metalKgPerM("cu", 40), 0.3556, 1e-9);

// Fixed price history for the comparisons
const daily = [
  { d: "2026-08-27", cu: 14490, al: 3212.5, fx: 95.5 },
  { d: "2026-08-28", cu: 14535, al: 3222, fx: 95.5 },
  { d: "2026-11-17", cu: 13225.5, al: 3060.5, fx: 93.9 },
];
near(Calc.inrPerKg(14490, 95.5, 0), 1383.795, 1e-6);
near(Calc.inrPerKg(1000, 100, 10), 110, 1e-9);

// Weekend date falls back to the last trading day
assert.strictEqual(Calc.priceOn(daily, "2026-08-30", "cu", "day", 0).used, "2026-08-28");
assert.strictEqual(Calc.priceOn(daily, "2026-08-01", "cu", "day", 0), null);
near(Calc.priceOn(daily, "2026-08-15", "cu", "month", 0).usd, 14512.5, 1e-9);

// 4C x 25 aluminium: 282 on 27 Aug, 220.16 on 17 Nov
let r = Calc.checkQuote(daily, { metal: "al", area: 100, dateA: "2026-08-27", rateA: 282, dateB: "2026-11-17", rateB: 220.16, qty: 1000, basis: "day", upliftPct: 0 });
near(r.a.inr, 306.79, 0.01); near(r.b.inr, 287.38, 0.01);
near(r.justifiedChange, -5.25, 0.01);
near(r.justifiedRateB, 276.75, 0.01);
near(r.gap, -56.59, 0.01);
assert.strictEqual(r.verdict, "low");
near(r.gapTotal, -56590, 10);

// 1C x 10 copper flexible with no new rate: only the fair rate is returned
r = Calc.checkQuote(daily, { metal: "cu", area: 10, dateA: "2026-08-27", rateA: 194, dateB: "2026-11-17", basis: "day", upliftPct: 0 });
near(r.justifiedChange, -12.62, 0.01);
assert.strictEqual(r.verdict, undefined);

// Small gaps are noise
r = Calc.checkQuote(daily, { metal: "cu", area: 10, dateA: "2026-08-27", rateA: 194, dateB: "2026-11-17", rateB: 185, basis: "day", upliftPct: 0 });
assert.strictEqual(r.verdict, "ok");
r = Calc.checkQuote(daily, { metal: "cu", area: 10, dateA: "2026-08-27", rateA: 194, dateB: "2026-11-17", rateB: 200, basis: "day", upliftPct: 0 });
assert.strictEqual(r.verdict, "high");

// Moving average
assert.deepStrictEqual(Calc.movingAverage([1, 2, 3, 4], 2), [null, 1.5, 2.5, 3.5]);
console.log("calc tests passed");
