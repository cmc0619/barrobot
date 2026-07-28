import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { parseMeasureMl } from "../src/domain/measure.js";

describe("parseMeasureMl", () => {
  for (const [measure, expected] of [
    ["30 ml", 30],
    ["3 cl", 30],
    ["1 oz", 29.57],
    ["1 1/2 oz", 44.36],
    ["2 tbsp", 29.57],
    ["1/2 cup", 118.29],
  ] as const) {
    it(`converts ${measure}`, () => {
      assert.equal(parseMeasureMl(measure), expected);
    });
  }

  it("leaves ambiguous and solid measures manual", () => {
    assert.equal(parseMeasureMl("1 lime wedge"), null);
    assert.equal(parseMeasureMl("to taste"), null);
    assert.equal(parseMeasureMl("some"), null);
  });
});
