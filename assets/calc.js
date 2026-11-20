/* Shared calculations for the cable metal price tracker.
   Loaded by index.html in the browser and by scripts/test_calc.js in Node. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.Calc = factory();
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // Conductor weight per km for each sq mm of cross-section (kg).
  var DENSITY = { cu: 8.89, al: 2.703 };

  // Reduced neutral used in "3.5 core" cables, by phase conductor size (sq mm).
  var HALF_NEUTRAL = {
    25: 16, 35: 16, 50: 25, 70: 35, 95: 50, 120: 70, 150: 70, 185: 95,
    240: 120, 300: 150, 400: 185, 500: 240, 630: 300
  };

  var SIZES = [0.5, 0.75, 1, 1.5, 2.5, 4, 6, 10, 16, 25, 35, 50, 70, 95, 120,
               150, 185, 240, 300, 400, 500, 630, 800, 1000];

  /** Total conductor cross-section in sq mm for a cores x size cable. */
  function conductorArea(cores, size) {
    cores = Number(cores); size = Number(size);
    if (!(cores > 0) || !(size > 0)) return null;
    if (cores === 3.5) {
      var neutral = HALF_NEUTRAL[size];
      if (!neutral) return null; // 3.5 core is not made in this size
      return 3 * size + neutral;
    }
    return cores * size;
  }

  /** Conductor metal weight in kg per metre of cable. */
  function metalKgPerM(metal, area) {
    return area * DENSITY[metal] / 1000;
  }

  /** Rs per kg from USD per tonne, exchange rate and optional duty/premium %. */
  function inrPerKg(usdPerTonne, fx, upliftPct) {
    return usdPerTonne * fx / 1000 * (1 + (Number(upliftPct) || 0) / 100);
  }

  /**
   * Metal price for a date.
   * basis "day":   the last trading day on or before the date.
   * basis "month": the average of all trading days in that calendar month.
   * Returns null when there is no usable data on or before the date.
   */
  function priceOn(daily, date, metal, basis, upliftPct) {
    var i, row;
    if (basis === "month") {
      var ym = date.slice(0, 7), sumUsd = 0, sumFx = 0, sumInr = 0, n = 0;
      for (i = 0; i < daily.length; i++) {
        row = daily[i];
        if (row.d.slice(0, 7) !== ym || row[metal] == null || row.fx == null) continue;
        sumUsd += row[metal]; sumFx += row.fx;
        sumInr += inrPerKg(row[metal], row.fx, upliftPct); n++;
      }
      if (!n) return null;
      return { basis: "month", used: ym, days: n, usd: sumUsd / n, fx: sumFx / n, inr: sumInr / n };
    }
    for (i = daily.length - 1; i >= 0; i--) {
      row = daily[i];
      if (row.d <= date && row[metal] != null && row.fx != null) {
        return { basis: "day", used: row.d, days: 1, usd: row[metal], fx: row.fx,
                 inr: inrPerKg(row[metal], row.fx, upliftPct) };
      }
    }
    return null;
  }

  /**
   * Compares a quoted rate on date A with date B.
   * q: { metal, area, dateA, rateA, dateB, rateB (optional), qty (optional),
   *      basis, upliftPct }
   */
  function checkQuote(daily, q) {
    var a = priceOn(daily, q.dateA, q.metal, q.basis, q.upliftPct);
    var b = priceOn(daily, q.dateB, q.metal, q.basis, q.upliftPct);
    if (!a || !b) return null;
    var kg = metalKgPerM(q.metal, q.area);
    var metalA = kg * a.inr, metalB = kg * b.inr;
    var justifiedChange = metalB - metalA;
    var out = {
      a: a, b: b, kgPerM: kg,
      metalValueA: metalA, metalValueB: metalB,
      metalShareA: q.rateA > 0 ? metalA / q.rateA : null,
      nonMetalA: q.rateA - metalA,
      justifiedChange: justifiedChange,
      justifiedRateB: q.rateA + justifiedChange,
      qty: q.qty > 0 ? q.qty : null
    };
    if (q.rateB > 0) {
      out.rateB = q.rateB;
      out.actualChange = q.rateB - q.rateA;
      out.gap = q.rateB - out.justifiedRateB;          // + means dearer than metal explains
      out.gapPct = out.gap / out.justifiedRateB;
      out.nonMetalB = q.rateB - metalB;
      out.verdict = Math.abs(out.gapPct) < 0.04 ? "ok" : (out.gap > 0 ? "high" : "low");
      if (out.qty) out.gapTotal = out.gap * out.qty;
    }
    if (out.qty) out.justifiedTotal = justifiedChange * out.qty;
    return out;
  }

  /** Simple trailing moving average over n points; null until n points exist. */
  function movingAverage(values, n) {
    var out = [], sum = 0, count = 0, queue = [];
    for (var i = 0; i < values.length; i++) {
      var v = values[i];
      if (v != null) { queue.push(v); sum += v; count++; }
      if (queue.length > n) { sum -= queue.shift(); count--; }
      out.push(count === n ? sum / n : null);
    }
    return out;
  }

  return {
    DENSITY: DENSITY, HALF_NEUTRAL: HALF_NEUTRAL, SIZES: SIZES,
    conductorArea: conductorArea, metalKgPerM: metalKgPerM, inrPerKg: inrPerKg,
    priceOn: priceOn, checkQuote: checkQuote, movingAverage: movingAverage
  };
});
