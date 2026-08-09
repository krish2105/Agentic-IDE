import assert from "node:assert/strict";
import { test } from "node:test";
import { allows3D, allowsPostProcessing, detectQualityTier, isQualityTier } from "./quality.ts";

const CAPABLE = { webglTier: 2 as const, deviceMemory: 16, hardwareConcurrency: 10 };

test("no WebGL means off, whatever else the machine has", () => {
  assert.equal(
    detectQualityTier({ ...CAPABLE, webglTier: 0, reducedMotion: false }),
    "off",
  );
});

test("reduced motion caps at minimal rather than off", () => {
  // The user asked for less motion, not less product: they still get the
  // 2D IDE in full, just without the shader field and the 3D scenes.
  assert.equal(detectQualityTier({ ...CAPABLE, reducedMotion: true }), "minimal");
});

test("save-data is treated as an explicit user signal, not a hint", () => {
  assert.equal(
    detectQualityTier({ ...CAPABLE, reducedMotion: false, saveData: true }),
    "minimal",
  );
});

test("a strong machine with no contrary signal gets ultra", () => {
  assert.equal(detectQualityTier({ ...CAPABLE, reducedMotion: false }), "ultra");
});

test("webgl1 or a modest machine lands on balanced", () => {
  assert.equal(
    detectQualityTier({ ...CAPABLE, webglTier: 1, reducedMotion: false }),
    "balanced",
  );
  assert.equal(
    detectQualityTier({ ...CAPABLE, deviceMemory: 4, reducedMotion: false }),
    "balanced",
  );
});

test("a weak machine lands on minimal", () => {
  assert.equal(
    detectQualityTier({ ...CAPABLE, deviceMemory: 2, reducedMotion: false }),
    "minimal",
  );
  assert.equal(
    detectQualityTier({ ...CAPABLE, hardwareConcurrency: 2, reducedMotion: false }),
    "minimal",
  );
});

test("missing optional fields do not crash the probe", () => {
  // Firefox hides deviceMemory; Safari hides both. Absent must not mean weak.
  assert.equal(detectQualityTier({ webglTier: 2, reducedMotion: false }), "ultra");
});

test("capability helpers agree with the tier ordering", () => {
  assert.equal(allows3D("ultra"), true);
  assert.equal(allows3D("balanced"), true);
  assert.equal(allows3D("minimal"), false);
  assert.equal(allows3D("off"), false);

  // Post-processing is the most expensive thing in the scene: Ultra only.
  assert.equal(allowsPostProcessing("ultra"), true);
  assert.equal(allowsPostProcessing("balanced"), false);
});

test("isQualityTier rejects anything not in the union", () => {
  assert.equal(isQualityTier("ultra"), true);
  assert.equal(isQualityTier("potato"), false);
  assert.equal(isQualityTier(null), false);
});
