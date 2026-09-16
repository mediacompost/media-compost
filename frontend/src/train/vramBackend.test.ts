/**
 * The VRAM estimate is per-BACKEND, because activations are.
 *
 * Every constant in the registry was measured on Apple Silicon. Re-measured
 * on an RTX 5070 Ti (bf16, the project's own engines, batch-slope method)
 * activations came in far under those figures — 8.5x for SD 1.5, 3.8x for
 * SDXL, 2.7x for FLUX.2, 1.7x for Chroma — because CUDA has fused attention
 * and MPS does not, and how much of a model's activation budget IS attention
 * differs per architecture. The anchors below are those measurements, so a
 * change to the arithmetic has to answer to real runs.
 */

import test from "node:test";
import assert from "node:assert/strict";
import {
  activationConstants, backendOf, defaultTrainingConfig, deviceMemoryGb,
  estimateVram,
} from "./util.ts";
import type { TrainModelSpec, TrainingConfig } from "./api.ts";

const SDXL = {
  key: "sdxl", label: "SDXL 1.0", default_area: 1024, default_lr: 1e-4,
  lora_only: false, lora_mb_per_rank: 5.6, full_gb: 5.1,
  backbone_gb: 5.1, aux_gb: 1.8, act_gb: 30.0, ckpt_factor: 0.08,
  act_gb_cuda: 7.8, ckpt_factor_cuda: 0.077, te_act_gb: 1.3,
} as unknown as TrainModelSpec;

const SD15 = {
  key: "sd15", label: "SD 1.5", default_area: 512, default_lr: 1e-4,
  lora_only: false, lora_mb_per_rank: 1.2, full_gb: 1.7,
  backbone_gb: 1.7, aux_gb: 0.4, act_gb: 8.5, ckpt_factor: 0.53,
  act_gb_cuda: 1.0, ckpt_factor_cuda: 0.23, te_act_gb: 0.06,
} as unknown as TrainModelSpec;

/** A model whose CUDA numbers nobody has measured. */
const UNMEASURED = { ...SDXL, act_gb_cuda: 0, ckpt_factor_cuda: 0 } as
  unknown as TrainModelSpec;

const cfg = (model: TrainModelSpec,
             patch: Partial<TrainingConfig["hyper"]> = {}): TrainingConfig => {
  const c = defaultTrainingConfig(model);
  return { ...c, hyper: { ...c.hyper, ...patch } };
};

test("the backend comes from the pinned device", () => {
  const c = defaultTrainingConfig(SDXL);
  assert.equal(backendOf({ ...c, gpu: "cuda:1" }), "cuda");
  assert.equal(backendOf({ ...c, gpu: "mps" }), "mps");
  assert.equal(backendOf({ ...c, gpu: "cpu" }), "cpu");
});

test("`auto` means the machine's first device", () => {
  const c = { ...defaultTrainingConfig(SDXL), gpu: "auto" };
  assert.equal(backendOf(c, [{ id: "cuda:0", label: "RTX" }]), "cuda");
  assert.equal(backendOf(c, [{ id: "mps", label: "Apple" }]), "mps");
  // Nothing known: no backend, so the MPS (conservative) constants apply.
  assert.equal(backendOf(c, []), "");
});

test("an unmeasured model keeps the MPS constants on CUDA", () => {
  const got = activationConstants(UNMEASURED, "cuda");
  assert.equal(got.act, 30.0);
  assert.equal(got.ckpt, 0.08);
});

test("SDXL at 1024 batch 1, no checkpointing: 14.8 GB measured", () => {
  const e = estimateVram(cfg(SDXL, { batch_size: 1 }), SDXL, true, "cuda")!;
  // 5.1 + 1.8 weights, ~0.9 optimizer at the default rank, 7.8 activations.
  assert.ok(Math.abs(e.total - 14.8) < 1.5, `got ${e.total}`);
  assert.equal(e.activations, 7.8);
});

test("SDXL at 1024 batch 2, no checkpointing: 22.6 GB measured", () => {
  const e = estimateVram(cfg(SDXL, { batch_size: 2 }), SDXL, true, "cuda")!;
  assert.ok(Math.abs(e.total - 22.6) < 1.5, `got ${e.total}`);
});

test("SDXL with checkpointing: 7.6 GB measured", () => {
  const e = estimateVram(
    cfg(SDXL, { batch_size: 1, gradient_checkpointing: true }),
    SDXL, true, "cuda")!;
  assert.ok(Math.abs(e.total - 7.6) < 1.5, `got ${e.total}`);
});

test("SD 1.5 at 512 batch 1, no checkpointing: 3.0 GB measured", () => {
  const e = estimateVram(cfg(SD15, { batch_size: 1 }), SD15, true, "cuda")!;
  assert.ok(Math.abs(e.total - 3.0) < 1.0, `got ${e.total}`);
});

test("the same job estimates far higher on MPS, and that is the point", () => {
  const cuda = estimateVram(cfg(SDXL, { batch_size: 1 }), SDXL, true, "cuda")!;
  const mps = estimateVram(cfg(SDXL, { batch_size: 1 }), SDXL, false, "mps")!;
  assert.ok(mps.activations > cuda.activations * 3,
    `mps ${mps.activations} vs cuda ${cuda.activations}`);
});

test("no backend named falls back to the conservative constants", () => {
  const none = estimateVram(cfg(SDXL, { batch_size: 1 }), SDXL)!;
  const mps = estimateVram(cfg(SDXL, { batch_size: 1 }), SDXL, true, "mps")!;
  assert.equal(none.activations, mps.activations);
});

/* THE AREA EXPONENT — activations against the pixel count.
 *
 * `act_gb` is defined at the model's own `default_area`, so the exponent can
 * only ever bend the curve AWAY from it. Fitted from readings at several
 * sizes; 1 is "nobody has measured this" and is the linear rule the estimate
 * applied before any of it. */

const EXP = { ...SDXL, act_exp: 1.2, act_exp_cuda: 0 } as
  unknown as TrainModelSpec;

const res = (model: TrainModelSpec, px: number): TrainingConfig => {
  const c = defaultTrainingConfig(model);
  return { ...c, buckets: { ...c.buckets, resolutions: [px] } };
};

test("at the model's own resolution the exponent changes nothing", () => {
  // The ratio is 1 there, and 1 to any power is 1 — so a measured exponent
  // can never move the case the constant was measured in.
  const flat = estimateVram(res(SDXL, 1024), SDXL, true, "mps")!;
  const bent = estimateVram(res(EXP, 1024), EXP, true, "mps")!;
  assert.equal(bent.activations, flat.activations);
});

test("above the native size a superlinear exponent costs MORE", () => {
  // 1536px is 2.25x the pixels of 1024. Linear says 2.25x the activations;
  // the measured curve says 2.25^1.2 = 2.67x, and under-promising here is
  // what makes the editor say a job will not fit when it will not.
  const flat = estimateVram(res(SDXL, 1536), SDXL, true, "mps")!;
  const bent = estimateVram(res(EXP, 1536), EXP, true, "mps")!;
  assert.ok(bent.activations > flat.activations,
    `${bent.activations} vs ${flat.activations}`);
  assert.ok(Math.abs(bent.activations / 30.0 - Math.pow(2.25, 1.2)) < 0.01);
});

test("below it the same exponent costs less", () => {
  const flat = estimateVram(res(SDXL, 512), SDXL, true, "mps")!;
  const bent = estimateVram(res(EXP, 512), EXP, true, "mps")!;
  assert.ok(bent.activations < flat.activations);
  // Measured on an M4 Max: 4.06 GB/image at 512, against the 7.5 the linear
  // rule predicts from a 30 GB constant at 1024.
  assert.ok(Math.abs(bent.activations - 5.2) < 1.0, `${bent.activations}`);
});

test("an unmeasured exponent is the linear rule, exactly as before", () => {
  assert.equal(activationConstants(SDXL, "mps").exp, 1);
  // …and a model measured on CUDA but whose exponent was not falls back to
  // the MPS figure rather than to 1 — the same direction `act_gb_cuda` takes.
  const both = { ...SDXL, act_exp: 1.4, act_exp_cuda: 0 } as
    unknown as TrainModelSpec;
  assert.equal(activationConstants(both, "cuda").exp, 1.4);
  const measured = { ...both, act_exp_cuda: 1.05 } as unknown as TrainModelSpec;
  assert.equal(activationConstants(measured, "cuda").exp, 1.05);
});

// ---------------------------------------------------------------------------
// Which card the estimate is compared AGAINST.

const gpuBox = (...totals: number[]) => totals.map((gb, i) => ({
  key: `gpu${i}`, label: `card ${i}`,
  stats: [{ key: "mem_total", label: "of", value: gb, unit: "GB" }],
})) as unknown as Parameters<typeof deviceMemoryGb>[0];

test("a job pinned to a card is measured against THAT card", () => {
  // The failure this replaces: the biggest card in the machine was the budget
  // for every job, so a run pinned to the small one was told it fitted.
  assert.equal(deviceMemoryGb(gpuBox(24, 8), "cuda:1"), 8);
  assert.equal(deviceMemoryGb(gpuBox(24, 8), "cuda:0"), 24);
});

test("with no card named, the biggest one is still the answer", () => {
  assert.equal(deviceMemoryGb(gpuBox(24, 8)), 24);
  assert.equal(deviceMemoryGb(gpuBox(24, 8), "auto"), 24);
});

test("a device that reports no total does not report zero", () => {
  // An Apple GPU row carries utilization and no memory at all — the memory is
  // unified and the system row has it. "0 GB, nothing fits" would be worse
  // than the machine-wide answer.
  const apple = [
    { key: "system", label: "Apple M4 Pro",
      stats: [{ key: "mem_total", label: "of", value: 64, unit: "GB" }] },
    { key: "gpu0", label: "Apple M4 Pro",
      stats: [{ key: "util", label: "GPU", value: 12, unit: "%" }] },
  ] as unknown as Parameters<typeof deviceMemoryGb>[0];
  assert.equal(deviceMemoryGb(apple, "mps"), 64);
  assert.equal(deviceMemoryGb(apple, "cuda:0"), 64, "and a bad pin falls back");
});
