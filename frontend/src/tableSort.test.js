import test from "node:test";
import assert from "node:assert/strict";
import { compareTableValues } from "./tableSort.js";

test("numeric columns sort numbers and numeric strings by value", () => {
  const values = ["10", 2, "1.5"].sort((a, b) => compareTableValues(a, b, { numeric: true }));
  assert.deepEqual(values, ["1.5", 2, "10"]);
  const descending = [...values].sort((a, b) => compareTableValues(a, b, {
    numeric: true, direction: "desc",
  }));
  assert.deepEqual(descending, ["10", 2, "1.5"]);
});

test("text columns retain string ordering and nulls stay last in either direction", () => {
  const values = [null, "10", "2", "A"].sort((a, b) => compareTableValues(a, b));
  assert.deepEqual(values, ["10", "2", "A", null]);
  const descending = [null, "A", "2", "10"].sort((a, b) => compareTableValues(a, b, {
    direction: "desc",
  }));
  assert.deepEqual(descending, ["A", "2", "10", null]);
});

test("equal values remain equal and identifiers keep leading zeroes", () => {
  assert.equal(compareTableValues("1000000002", "1000000002"), 0);
  assert.ok(compareTableValues("00100", "0100") < 0);
});
