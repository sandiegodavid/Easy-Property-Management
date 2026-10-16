import { expect, test } from "@playwright/test";
import { leaseLastCoveredOn } from "../src/shared/lease-dates";

test("lease end displays the last covered calendar day without changing its boundary", () => {
  for (const [boundary, expected] of [
    ["2027-05-01", "2027-04-30"],
    ["2027-10-01", "2027-09-30"],
    ["2028-03-01", "2028-02-29"],
    ["2027-03-01", "2027-02-28"],
    ["2027-01-01", "2026-12-31"],
    ["2027-03-15", "2027-03-14"],
    ["2027-11-08", "2027-11-07"],
  ]) {
    expect(leaseLastCoveredOn(boundary)).toBe(expected);
  }
  expect(leaseLastCoveredOn(null)).toBeNull();
});
