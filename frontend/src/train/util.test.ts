// The VRAM estimate shown in the job editor's footer. Pure arithmetic over
// the config and the model's registry constants, so it is testable as-is —
// util.ts imports only types from api.ts, which `node --test` strips.
import test from "node:test";
import assert from "node:assert/strict";
import {
  adapterFamily, cadenceSteps, defaultDegradeVariant, defaultTrainingConfig,
  errText, fitsModel, toggleLocked,
  degradeFileCount, degradeMix, estimateVram, keptCheckpoints, lastActivity,
  looksLikeLocalPath, nestUserModels, resolutionList,
  unsupportedReasons,
} from "./util.ts";
import type {
  TrainDegradeVariant, TrainModelSpec, TrainingConfig,
} from "./api.ts";

const SDXL = {
  key: "sdxl", label: "SDXL 1.0", default_area: 1024, default_lr: 1e-4,
  lora_only: false, lora_mb_per_rank: 5.6, full_gb: 5.1,
  backbone_gb: 5.1, aux_gb: 1.8, act_gb: 30.0, ckpt_factor: 0.08,
  te_act_gb: 1.3,
} as unknown as TrainModelSpec;

const cfg = (patch: Partial<TrainingConfig["hyper"]> = {},
             buckets: Partial<TrainingConfig["buckets"]> = {}): TrainingConfig => {
  const c = defaultTrainingConfig(SDXL);
  return { ...c, hyper: { ...c.hyper, ...patch },
           buckets: { ...c.buckets, ...patch && buckets } };
};

test("an unknown model has no estimate rather than a wrong one", () => {
  assert.equal(estimateVram(cfg(), undefined), null);
});

test("a batch-1 SDXL run matches what the engine actually allocated", () => {
  // Measured on MPS: 7.5 GB resident after load, ~30 GB for one image's
  // forward+backward without checkpointing, ~2.5 GB with it.
  const plain = estimateVram(cfg({ batch_size: 1 }), SDXL)!;
  assert.ok(plain.total > 34 && plain.total < 42, `got ${plain.total}`);
  const ckpt = estimateVram(cfg({ batch_size: 1, gradient_checkpointing: true }),
                            SDXL)!;
  assert.ok(ckpt.total > 8 && ckpt.total < 12, `got ${ckpt.total}`);
});

test("weights are the backbone plus the frozen encoders", () => {
  const e = estimateVram(cfg({ batch_size: 1 }), SDXL)!;
  assert.equal(Math.round(e.weights * 10) / 10, 6.9);   // 5.1 + 1.8
});

test("activations scale with the batch", () => {
  const one = estimateVram(cfg({ batch_size: 1 }), SDXL)!;
  const four = estimateVram(cfg({ batch_size: 4 }), SDXL)!;
  assert.equal(Math.round(four.activations), Math.round(one.activations * 4));
  // The resident parts do not move with it.
  assert.equal(four.weights, one.weights);
  assert.equal(four.optimizer, one.optimizer);
});

test("gradient checkpointing is the big lever, and it only moves activations", () => {
  const off = estimateVram(cfg({ batch_size: 8 }), SDXL)!;
  const on = estimateVram(cfg({ batch_size: 8, gradient_checkpointing: true }), SDXL)!;
  // Measured on this project's SDXL engine: checkpointing leaves 8%.
  assert.ok(on.activations < off.activations / 4);
  assert.equal(on.weights, off.weights);
  // The configuration that ran out of memory on a 64 GB machine must read as
  // implausible, and the recommended fix as comfortable.
  assert.ok(off.total > 50, `expected >50 GB, got ${off.total}`);
  const fixed = estimateVram(cfg({ batch_size: 1, gradient_checkpointing: true }), SDXL)!;
  assert.ok(fixed.total < 12, `expected <12 GB, got ${fixed.total}`);
});

test("resolution scales activations by area, not by side", () => {
  const full = estimateVram(cfg({ batch_size: 1 }), SDXL)!;
  const half = estimateVram(cfg({ batch_size: 1 }, { resolutions: [512] }),
                            SDXL)!;
  assert.ok(Math.abs(half.activations - full.activations / 4) < 1e-9);
});

test("fp32 doubles the resident weights", () => {
  const bf16 = estimateVram(cfg({ batch_size: 1 }), SDXL)!;
  const fp32 = estimateVram(cfg({ batch_size: 1, precision: "fp32" }), SDXL)!;
  assert.equal(fp32.weights, bf16.weights * 2);
});

test("quantization shrinks the backbone only", () => {
  const none = estimateVram(cfg({ batch_size: 1 }), SDXL)!;
  const nf4 = estimateVram(cfg({ batch_size: 1, quantization: "nf4" }), SDXL)!;
  // 5.1 * nf4_scale + 1.8 against 5.1 + 1.8. This read 5.1/4 + 1.8 = 3.08
  // while nf4 was assumed to reach its theoretical quarter; the SDXL fixture
  // declares no `nf4_scale`, so it now takes the 0.35 default.
  assert.equal(Math.round(nf4.weights * 100) / 100,
               Math.round((5.1 * 0.35 + 1.8) * 100) / 100);
  assert.ok(nf4.weights < none.weights);
  // …and the AUX term is untouched either way, which is what this is about.
  assert.equal(Math.round((nf4.weights - 5.1 * 0.35) * 100) / 100, 1.8);
});

test("int8 shrinks a UNet by what it MEASURES, not by a flat half", () => {
  // The saving is a fact about the model, not about the scheme: quantizers
  // convert `Linear` layers and a UNet is mostly `Conv2d`. Measured on an M4
  // Max, SD 1.5's UNet goes 1.72 -> 1.45 GB at int8 — 0.84, not 0.5 — so a
  // flat half promised twice the saving the run makes, which is the direction
  // that says a job fits when it does not.
  const unet = { ...SDXL, int8_scale: 0.84 } as unknown as TrainModelSpec;
  const q = estimateVram(cfg({ batch_size: 1, quantization: "int8" }), unet)!;
  assert.equal(Math.round(q.weights * 100) / 100,
               Math.round((5.1 * 0.84 + 1.8) * 100) / 100);

  // A DiT really is all Linear, and keeps the old half.
  const dit = { ...SDXL, int8_scale: 0.5 } as unknown as TrainModelSpec;
  const d = estimateVram(cfg({ batch_size: 1, quantization: "int8" }), dit)!;
  assert.equal(Math.round(d.weights * 100) / 100, 5.1 / 2 + 1.8);

  // A model with no measurement keeps the old behaviour exactly.
  const unmeasured = { ...SDXL } as unknown as TrainModelSpec;
  delete (unmeasured as Record<string, unknown>).int8_scale;
  const u = estimateVram(cfg({ batch_size: 1, quantization: "int8" }),
                         unmeasured)!;
  assert.equal(u.weights, d.weights);
});

test("quantizing the text encoder takes its own measured factor", () => {
  const m = { ...SDXL, int8_scale: 0.5, int8_te_scale: 0.79 } as
    unknown as TrainModelSpec;
  const off = estimateVram(cfg({ batch_size: 1, quantization: "int8" }), m)!;
  const on = estimateVram(
    cfg({ batch_size: 1, quantization: "int8", quantize_text_encoder: true }),
    m)!;
  assert.equal(Math.round(off.weights * 100) / 100, 5.1 / 2 + 1.8);
  assert.equal(Math.round(on.weights * 100) / 100,
               Math.round((5.1 / 2 + 1.8 * 0.79) * 100) / 100);
  // …and nothing at all without a scheme to apply.
  const noScheme = estimateVram(
    cfg({ batch_size: 1, quantize_text_encoder: true }), m)!;
  assert.equal(noScheme.weights, 5.1 + 1.8);
});

test("nf4 shrinks by what it MEASURES, and it is nowhere near a quarter", () => {
  // The theoretical figure is 0.25 and nothing reaches it: measured on an
  // RTX 5070 Ti, FLUX.2 Klein keeps 0.29, SDXL 0.41 and SD 1.5 0.81, because
  // bitsandbytes keeps per-block scales and converts only `Linear`. The flat
  // quarter promised SD 1.5 at 0.82 GB where the run wants 1.80 — a whole GB
  // in the direction that says a job fits when it does not.
  const unet = { ...SDXL, nf4_scale: 0.81 } as unknown as TrainModelSpec;
  const q = estimateVram(cfg({ batch_size: 1, quantization: "nf4" }), unet)!;
  assert.equal(Math.round(q.weights * 100) / 100,
               Math.round((5.1 * 0.81 + 1.8) * 100) / 100);

  // A model nobody has measured takes the default, which sits ABOVE every
  // DiT reading rather than below them — an estimate that is too small is
  // the one that strands a run.
  const unmeasured = { ...SDXL } as unknown as TrainModelSpec;
  delete (unmeasured as Record<string, unknown>).nf4_scale;
  const u = estimateVram(cfg({ batch_size: 1, quantization: "nf4" }),
                         unmeasured)!;
  assert.equal(Math.round(u.weights * 100) / 100,
               Math.round((5.1 * 0.35 + 1.8) * 100) / 100);
  assert.ok(u.weights > 5.1 * 0.25 + 1.8, "must not use the theoretical 0.25");

  // nf4 still saves more than int8 on the same model, or the option would be
  // pointless — the correction is to the size of the saving, not its sign.
  const i8 = estimateVram(cfg({ batch_size: 1, quantization: "int8" }),
                          { ...SDXL, int8_scale: 0.59 } as unknown as
                          TrainModelSpec)!;
  const n4 = estimateVram(cfg({ batch_size: 1, quantization: "nf4" }),
                          { ...SDXL, nf4_scale: 0.41 } as unknown as
                          TrainModelSpec)!;
  assert.ok(n4.weights < i8.weights);
});

test("the nf4 text encoder takes its own factor too", () => {
  const m = { ...SDXL, nf4_scale: 0.29, nf4_te_scale: 0.35 } as
    unknown as TrainModelSpec;
  const on = estimateVram(
    cfg({ batch_size: 1, quantization: "nf4", quantize_text_encoder: true }),
    m)!;
  assert.equal(Math.round(on.weights * 100) / 100,
               Math.round((5.1 * 0.29 + 1.8 * 0.35) * 100) / 100);
});

test("offloading the text encoder frees ALL of it, not a share", () => {
  // Quantizing shrinks the encoder; offloading takes it off the card, so no
  // scheme applied to it can matter and the offload has to win.
  const m = { ...SDXL, nf4_scale: 0.29, nf4_te_scale: 0.35 } as
    unknown as TrainModelSpec;
  const quantized = estimateVram(
    cfg({ batch_size: 1, quantization: "nf4", quantize_text_encoder: true }),
    m)!;
  const offloaded = estimateVram(
    cfg({ batch_size: 1, quantization: "nf4", quantize_text_encoder: true,
          offload_text_encoder: true }), m)!;
  assert.ok(offloaded.weights < quantized.weights);
  // What is left of aux is the VAE's residual, not the encoder's factor.
  assert.equal(Math.round(offloaded.weights * 100) / 100,
               Math.round((5.1 * 0.29 + 1.8 * 0.04) * 100) / 100);

  // It works without any quantization at all — the two are independent.
  const plain = estimateVram(cfg({ batch_size: 1 }), m)!;
  const plainOff = estimateVram(
    cfg({ batch_size: 1, offload_text_encoder: true }), m)!;
  assert.ok(plainOff.weights < plain.weights);
  assert.equal(Math.round(plainOff.weights * 100) / 100,
               Math.round((5.1 + 1.8 * 0.04) * 100) / 100);

  // ACTIVATIONS ARE UNTOUCHED. The encoder's weights leave; the backbone's
  // per-image cost does not change, which is what measurement showed
  // (SD 1.5: 1.07 GB/image either way).
  assert.equal(plainOff.activations, plain.activations);
});

test("a full finetune is dominated by optimizer state", () => {
  const lora = estimateVram(cfg({ batch_size: 1 }), SDXL)!;
  const full = estimateVram({ ...cfg({ batch_size: 1 }), method: "full" }, SDXL)!;
  assert.ok(full.optimizer > 10 * lora.optimizer);
  assert.ok(full.optimizer > full.weights + full.activations);
});

test("attention slicing only counts where the engine will really slice", () => {
  // "auto" never slices now — on MPS it returns NaN, on CUDA the fused
  // kernels are better — so the estimate must not promise the saving.
  const auto = estimateVram(cfg({ batch_size: 2 }), SDXL)!;
  const on = estimateVram(cfg({ batch_size: 2, attention_slicing: "on" }),
                          SDXL, true)!;
  const onButRefused = estimateVram(
    cfg({ batch_size: 2, attention_slicing: "on" }), SDXL, false)!;
  assert.ok(on.activations < auto.activations);
  assert.equal(onButRefused.activations, auto.activations);
});

test("lastActivity is the newest moment the job passed through", () => {
  // A finished run: the end is the last thing that happened.
  assert.equal(lastActivity({
    created_at: 100, queued_at: 200, started_at: 300, finished_at: 400,
  }), 400);
  // Running: no end yet, so the start is.
  assert.equal(lastActivity({
    created_at: 100, queued_at: 200, started_at: 300, finished_at: null,
  }), 300);
  // A fresh draft has only its creation; nulls never win.
  assert.equal(lastActivity({ created_at: 100 }), 100);
  assert.equal(lastActivity({}), 0);
  // AND `queued_at` IS IGNORED, however new it looks. It is the queue's
  // POSITION stamp, rewritten for every waiting job on any reorder, so a job
  // whose real moments are old must go on reading old.
  assert.equal(lastActivity({
    created_at: 100, started_at: 300, finished_at: 400, queued_at: 900,
  } as Parameters<typeof lastActivity>[0] & { queued_at: number }), 400);
});

test("keptCheckpoints counts the UNION of the window and the milestones", () => {
  const cfg = defaultTrainingConfig();
  cfg.hyper.steps = 2000;
  cfg.hyper.checkpoint_every = 100;   // 19 snapshots (the last step writes none)

  // Window only — the classic rolling behaviour.
  cfg.hyper.checkpoint_keep = 4;
  cfg.hyper.checkpoint_keep_every = 0;
  assert.equal(keptCheckpoints(cfg), 4);

  // Milestones only: every 4th of 19 snapshots.
  cfg.hyper.checkpoint_keep = 0;
  cfg.hyper.checkpoint_keep_every = 4;
  assert.equal(keptCheckpoints(cfg), 4);   // #4, #8, #12, #16

  // Both: the window plus the milestones BEFORE it (those inside are
  // already counted, and counting them twice is how an estimate lies).
  cfg.hyper.checkpoint_keep = 3;
  assert.equal(keptCheckpoints(cfg), 3 + Math.floor((19 - 3) / 4));

  // Neither rule: the newest snapshot always survives, so never 0.
  cfg.hyper.checkpoint_keep = 0;
  cfg.hyper.checkpoint_keep_every = 0;
  assert.equal(keptCheckpoints(cfg), 1);

  // Snapshots off entirely: nothing is kept, whatever the other numbers say.
  cfg.hyper.checkpoint_every = 0;
  assert.equal(keptCheckpoints(cfg), 0);
});

test("training the text encoder is a real term, not a nudge", () => {
  // Measured on SDXL at 1024, batch 1, the backbone checkpointed and the
  // encoder not (encoder-side checkpointing did not exist yet): peak
  // 10.14 -> 11.45 GB. The old estimate moved by ~0.2 (an optimizer
  // multiplier), so a run that fit on paper could still die from the
  // encoder's retained activations.
  const off = estimateVram(cfg({}), SDXL, false)!;
  const on = estimateVram(cfg({ train_text_encoder: true }), SDXL, false)!;
  const delta = on.total - off.total;
  assert.ok(delta > 1.2 && delta < 1.8, `got ${delta.toFixed(2)} GB`);
  // And it scales with the batch: one prompt per image.
  const batched = estimateVram(
    cfg({ train_text_encoder: true, batch_size: 4 }), SDXL, false)!;
  assert.ok(batched.activations > on.activations * 3, "did not scale with batch");
  // The engine checkpoints a trained encoder whenever the run checkpoints,
  // and the estimate applies the same factor to it: the term shrinks.
  const ckOff = estimateVram(cfg({ gradient_checkpointing: true }), SDXL, false)!;
  const ckOn = estimateVram(
    cfg({ gradient_checkpointing: true, train_text_encoder: true }), SDXL, false)!;
  const ckDelta = ckOn.activations - ckOff.activations;
  assert.ok(ckDelta > 0 && ckDelta < delta / 3, `got ${ckDelta.toFixed(2)} GB`);
});

test("the large-encoder switch takes T5 out of the estimate, where the model has one", () => {
  // FLUX.1-shaped: T5-XXL beside CLIP-L. Off, only CLIP-L trains — a few
  // hundredths of a GB against T5's several, and a far smaller adapter.
  const flux = { ...SDXL, te_act_gb: 12.0, te_pooled_act_gb: 0.06,
    te_params_m_per_rank: 0.86, te_pooled_params_m_per_rank: 0.074,
  } as TrainModelSpec;
  const off = estimateVram(cfg({}), flux, false)!;
  const both = estimateVram(cfg({ train_text_encoder: true }), flux, false)!;
  const small = estimateVram(
    cfg({ train_text_encoder: true, train_text_encoder_large: false }), flux, false)!;
  assert.ok(both.activations - off.activations > 11, "T5 not counted");
  assert.ok(small.activations - off.activations < 0.1, "CLIP-L alone costs T5's share");
  assert.ok(small.optimizer < both.optimizer, "the adapter did not shrink with it");
  // The adapter's parameters are counted from the model's figure, not as a
  // flat share of the backbone's: T5's adapter at rank 16 is ~0.86M x 16 x
  // 16 bytes ≈ 0.22 GB of AdamW state, plus the backbone's own.
  assert.ok(both.optimizer - off.optimizer > 0.2, `got ${(both.optimizer - off.optimizer).toFixed(3)}`);
  // A model with no small encoder beside its large one ignores the switch:
  // Chroma's T5 is its only encoder, and "off" would be nothing to train.
  const chroma = { ...SDXL, te_act_gb: 12.0, te_params_m_per_rank: 0.786 } as TrainModelSpec;
  const a = estimateVram(cfg({ train_text_encoder: true }), chroma, false)!;
  const b = estimateVram(
    cfg({ train_text_encoder: true, train_text_encoder_large: false }), chroma, false)!;
  assert.equal(a.total, b.total);
});

test("a model with no text encoder to train costs nothing for it", () => {
  const flux = { ...SDXL, te_act_gb: 0 } as TrainModelSpec;
  const off = estimateVram(cfg({ gradient_checkpointing: true }), flux, false)!;
  const on = estimateVram(
    cfg({ gradient_checkpointing: true, train_text_encoder: true }), flux, false)!;
  assert.equal(on.activations, off.activations);
});

test("a setting the GPU or model can't do says so before the run does", () => {
  const c = defaultTrainingConfig(SDXL);
  const q = (patch: Partial<TrainingConfig["hyper"]>, device: string,
             model = SDXL) =>
    unsupportedReasons({ ...c, hyper: { ...c.hyper, ...patch } }, model, device);

  // Nothing wrong with the defaults on an NVIDIA GPU — except the one row
  // that is about the METHOD rather than the machine: half-precision masters
  // are a full-finetune setting and the default config is a LoRA.
  assert.deepEqual(q({}, "cuda:0"),
    { rows: { "hyper.bf16_masters": "only for a full finetune" }, values: {} });

  // …and on a full finetune it is offered, until something else rules it out.
  const qf = (patch: Partial<TrainingConfig["hyper"]> = {}) =>
    unsupportedReasons({ ...c, method: "full", hyper: { ...c.hyper, ...patch } },
                       SDXL, "cuda:0").rows["hyper.bf16_masters"];
  assert.equal(qf(), undefined);
  assert.match(qf({ precision: "fp32" }), /full precision/);
  // Prodigy derives one learning rate across every parameter, so it cannot be
  // stepped one at a time — which is how the fp32 buffer stays one tensor.
  assert.match(qf({ optimizer: "prodigy" }), /Prodigy/);

  // WHAT CANNOT RUN IS A VALUE, NOT THE ROW. Quantization used to be refused
  // as a whole off NVIDIA — so a row set to "None", which every machine does,
  // wore a chip reading "NVIDIA only".
  assert.equal(q({}, "mps").rows["hyper.quantization"], undefined);
  assert.deepEqual(Object.keys(q({}, "mps").values["hyper.quantization"]),
                   ["fp8", "nf4"]);
  assert.equal(q({}, "mps").values["hyper.quantization"].none, undefined);

  // The reason is per value, because they differ: fp8 is a torch dtype the
  // device either has or hasn't, and nf4 goes through bitsandbytes.
  assert.match(q({}, "mps").values["hyper.quantization"].fp8, /Ada/);
  assert.match(q({}, "cpu").values["hyper.quantization"].nf4, /NVIDIA/);
  assert.equal(q({}, "cuda:1").values["hyper.quantization"], undefined);

  // **int8 IS offered off CUDA**, and that is the point of the quanto path:
  // it runs on Apple silicon, where it is what makes the largest models
  // trainable at all (Qwen-Image 57.7 GB of weights -> 37.5).
  assert.equal(q({}, "mps").values["hyper.quantization"].int8, undefined);
  assert.equal(q({}, "cpu").values["hyper.quantization"].int8, undefined);

  // Quantizing the text encoder conflicts with nothing a chip can say: an
  // unset `quantization` does not put one on the row — that is the default
  // state, and the toggle is merely disabled there — and TRAINING the
  // encoder no longer does either (QLoRA over the encoder is what lets
  // T5-XXL train on a 32 GB card). Offloading is the one that still does.
  assert.equal(q({}, "mps").rows["hyper.quantize_text_encoder"], undefined);
  assert.equal(q({ train_text_encoder: true }, "cuda:0")
                 .rows["hyper.quantize_text_encoder"], undefined);
  assert.match(q({ train_text_encoder: true }, "cuda:0")
                 .rows["hyper.offload_text_encoder"], /training the text encoder/);
  assert.match(q({}, "cpu").values["hyper.optimizer"].adamw_8bit, /NVIDIA/);
  assert.equal(q({}, "cuda:0").values["hyper.optimizer"], undefined);

  // fp16 is not refused on Apple silicon, it is IGNORED — the run trains in
  // fp32 at twice the memory, which is exactly the kind of thing worth
  // saying while choosing rather than in a log.
  assert.match(q({}, "mps").values["hyper.precision"].fp16, /fp32/);
  assert.equal(q({}, "mps").values["hyper.precision"].bf16, undefined);
  assert.equal(q({}, "cuda:0").values["hyper.precision"], undefined);

  // Attention slicing is the machine's answer, not the device's.
  const noSlice = unsupportedReasons(c, SDXL, "mps", false);
  assert.ok(noSlice.values["hyper.attention_slicing"].on);
  assert.equal(noSlice.values["hyper.attention_slicing"].off, undefined);
  assert.equal(
    unsupportedReasons(c, SDXL, "mps").values["hyper.attention_slicing"],
    undefined);

  // A model whose engine trains no text encoder disables the setting — a ROW
  // reason, since there is no other value to offer.
  const flux = { ...SDXL, te_act_gb: 0, lora_only: true } as TrainModelSpec;
  assert.equal(q({}, "cuda:0", flux).rows["hyper.train_text_encoder"],
               "this model has none");
  assert.equal(q({}, "cuda:0").rows["hyper.train_text_encoder"], undefined);
  // …and its Method row keeps LoRA selectable with the other entry out of
  // reach, rather than going dead as a whole.
  assert.ok(q({}, "cuda:0", flux).values["method"].full);
  assert.equal(q({}, "cuda:0", flux).values["method"].lora, undefined);

  // A full finetune leaves nothing to quantize and no adapter to train: both
  // are rows, and the quantization VALUES then say nothing — the row is
  // already off, and two reasons on one control is one too many.
  const full = unsupportedReasons({ ...c, method: "full" }, SDXL, "cuda:0");
  assert.match(full.rows["hyper.quantization"], /nothing to quantize/);
  assert.match(full.rows["hyper.train_text_encoder"], /LoRA/);
  assert.equal(full.values["hyper.quantization"], undefined);
});

test("Chroma's native resolution is reported as bigger than a 64 GB machine", () => {
  // Measured on MPS: 25.70 GB resident, and batch 1 at 1024 with gradient
  // checkpointing peaks at 66.2 GB — the machine is already swapping. The
  // constants before this were SDXL's scaled by parameter count and said
  // ~36 GB, four times under on the model least able to afford it.
  const CHROMA = {
    key: "chroma", default_area: 1024, default_lr: 3e-4, lora_only: true,
    lora_mb_per_rank: 4.0, full_gb: 0, backbone_gb: 17.8, aux_gb: 7.9,
    act_gb: 133.0, ckpt_factor: 0.30, te_act_gb: 0,
  } as unknown as TrainModelSpec;
  const c = defaultTrainingConfig(CHROMA);
  const est = estimateVram(
    { ...c, hyper: { ...c.hyper, gradient_checkpointing: true } }, CHROMA, false)!;
  assert.ok(est.total > 60 && est.total < 72, `got ${est.total.toFixed(1)} GB`);
  // Its weights alone are most of a consumer card.
  assert.ok(est.weights > 25 && est.weights < 27, `${est.weights.toFixed(1)} GB`);
});

// ---- degradation variants ----------------------------------------------------

const VARIANT = (over: Partial<TrainDegradeVariant> = {}) => ({
  ...defaultDegradeVariant(), tags: ["jpeg_artifacts"], ...over,
});

test("a fresh config carries the degradation section", () => {
  // What stops `configFromPreset` handing `undefined` to the editor's inputs
  // for a preset saved before this existed.
  assert.deepEqual(defaultTrainingConfig(SDXL).degrade, { variants: [] });
});

test("the mix says what the run will draw, as ratios to a clean visit", () => {
  const c = defaultTrainingConfig(SDXL);
  const mix = degradeMix({
    ...c,
    degrade: { variants: [VARIANT({ weight: 0.25 }), VARIANT({ weight: 0.5 })] },
  });
  // 1 : 0.25 : 0.5 over a mass of 1.75.
  assert.equal(mix.clean, 57.14);
  assert.deepEqual(mix.parts.map((p) => p.visits), [14.29, 28.57]);
  // And it adds up — the point of stating it at all.
  const total = mix.clean + mix.parts.reduce((a, p) => a + p.visits, 0);
  assert.ok(Math.abs(total - 100) < 0.05, `${total}`);
});

test("a variant that would do nothing is left out of the mix", () => {
  const c = defaultTrainingConfig(SDXL);
  // No tags = an unmarked bad picture, which the backend drops; weight 0 = off.
  const mix = degradeMix({
    ...c,
    degrade: { variants: [VARIANT({ tags: [] }), VARIANT({ weight: 0 })] },
  });
  assert.equal(mix.clean, 100);
  assert.deepEqual(mix.parts, []);
});

test("a gated variant is marked as such, because its share is of a subset", () => {
  const c = defaultTrainingConfig(SDXL);
  const mix = degradeMix({
    ...c,
    degrade: {
      variants: [VARIANT({ require_tags: ["high_quality"] }),
                 VARIANT({ name: "plain" })],
    },
  });
  assert.deepEqual(mix.parts.map((p) => p.gated), [true, false]);
  // A named variant is called by its name, an unnamed one by its method.
  assert.deepEqual(mix.parts.map((p) => p.label), ["jpeg", "plain"]);
});

test("the cached-file count is what multiplies when variations are raised", () => {
  const c = defaultTrainingConfig(SDXL);
  const one = { ...c, degrade: { variants: [VARIANT()] } };
  assert.equal(degradeFileCount(one, 400), 400);
  const three = { ...c, degrade: { variants: [VARIANT({ variations: 3 })] } };
  assert.equal(degradeFileCount(three, 400), 1200);
  // Two variants add rather than multiply each other.
  assert.equal(degradeFileCount(
    { ...c, degrade: { variants: [VARIANT(), VARIANT({ variations: 2 })] } },
    100), 300);
  assert.equal(degradeFileCount(c, 400), 0);
});

// ---- adding a model ---------------------------------------------------------

test("a hub id is told from a path by its own shape", () => {
  for (const repo of ["owner/repo", "stabilityai/sdxl-turbo", "a/b"]) {
    assert.equal(looksLikeLocalPath(repo), false, repo);
  }
  for (const path of [
    "/models/sdxl", "~/models/sdxl", "./sdxl", "../sdxl",
    "C:\\models\\sdxl", "C:/models/sdxl", "models\\sdxl",
    "/a/b/c.safetensors", "sdxl.safetensors", "some/deep/folder",
    "sdxl",                       // one segment: not a repo id
  ]) {
    assert.equal(looksLikeLocalPath(path), true, path);
  }
  // Nothing typed is neither, and must not flip the field's meaning.
  assert.equal(looksLikeLocalPath(""), false);
  assert.equal(looksLikeLocalPath("   "), false);
});

test("a user model is listed under the built-in it is based on", () => {
  const m = (key: string, user?: boolean, base?: string): TrainModelSpec =>
    ({ ...SDXL, key, label: key, user: !!user, base: base ?? "" });
  const nested = nestUserModels([
    m("sdxl"), m("mine", true, "sdxl"), m("sd15"), m("other", true, "sd15"),
  ]);
  assert.deepEqual(nested.map((x) => [x.model.key, x.child]),
    [["sdxl", false], ["mine", true], ["sd15", false], ["other", true]]);
});

test("a user model whose base is gone still appears", () => {
  const m = (key: string, user?: boolean, base?: string): TrainModelSpec =>
    ({ ...SDXL, key, label: key, user: !!user, base: base ?? "" });
  const nested = nestUserModels([m("sdxl"), m("orphan", true, "vanished")]);
  assert.deepEqual(nested.map((x) => x.model.key), ["sdxl", "orphan"]);
});

// ---- the activation SHAPE ---------------------------------------------------
// Activations are a polynomial in the pixel count, not a power law: a constant
// part (a conditioning sequence has no pixels in it), a linear part (per-image
// token work) and a quadratic part (a materialized N x N attention matrix,
// which a fused kernel never allocates). Measured by fitting area sweeps.

const SHAPED = {
  ...SDXL, act_gb_cuda: 10, ckpt_factor_cuda: 0.1,
  act_const_share_cuda: 0.25,
} as unknown as TrainModelSpec;

const acts = (m: TrainModelSpec, res: number, backend: string) =>
  estimateVram({ ...cfg({ batch_size: 1 }),
                 buckets: { ...cfg().buckets, resolutions: [res] } },
               m, true, backend)!.activations;

test("the shares are defined AT the native area, so they cancel there", () => {
  // Whatever the split, the estimate at the model's own resolution is act_gb
  // exactly — which is what makes every existing constant survive the change.
  assert.equal(Math.round(acts(SHAPED, 1024, "cuda") * 1000) / 1000, 10);
});

test("a constant share stops activations collapsing at small resolutions", () => {
  // Half the side is a QUARTER of the pixels. Purely linear that is 2.5 GB;
  // with a quarter of the cost independent of the picture it is 2.5 + 2.5.
  const half = acts(SHAPED, 512, "cuda");
  assert.ok(Math.abs(half - (0.25 * 10 + 0.75 * 10 * 0.25)) < 1e-9,
            `got ${half}`);
  // And it must be ABOVE what the old linear rule predicted, or the change
  // would have made small-resolution runs look cheaper than they are.
  assert.ok(half > 10 * 0.25);
});

test("a quadratic share is what unfused attention costs, and only there", () => {
  // MPS materializes the score matrix; CUDA does not. The same model must
  // therefore grow differently per backend rather than per family.
  const mps = { ...SDXL, act_gb: 10, act_quad_share: 0.6,
                act_gb_cuda: 10, act_const_share_cuda: 0.25,
              } as unknown as TrainModelSpec;
  // Twice the side is 4x the pixels and 16x the square, so 0.4*4 + 0.6*16.
  const grew = acts(mps, 2048, "mps") / acts(mps, 1024, "mps");
  assert.ok(Math.abs(grew - 11.2) < 1e-9, `quadratic growth, got ${grew}`);
  // The same model on CUDA: 0.25 + 0.75*4, i.e. it grows a THIRD as fast,
  // which is the whole reason the shape is per backend.
  const cuda = acts(mps, 2048, "cuda") / acts(mps, 1024, "cuda");
  assert.ok(Math.abs(cuda - 3.25) < 1e-9, `affine growth on cuda, got ${cuda}`);
});

test("an unmeasured model keeps its exponent rather than dropping to linear", () => {
  // The fallback matters in the dangerous direction: those exponents are
  // superlinear, so ignoring them would quietly LOWER every estimate that has
  // no measured share.
  const old = { ...SDXL, act_gb: 10, act_exp: 1.8 } as unknown as TrainModelSpec;
  const quarterPixels = acts(old, 512, "mps");
  assert.ok(Math.abs(quarterPixels - 10 * Math.pow(0.25, 1.8)) < 1e-9,
            `got ${quarterPixels}`);
});

// ---- the OPTIMIZER term -----------------------------------------------------

test("optimizer state is counted from trainable parameters, not file size", () => {
  // `lora_mb_per_rank` sizes the FILE a run writes and was wrong by up to 5x
  // as a parameter count, in both directions. 16 bytes a parameter is the
  // master copy, the gradient and Adam's two moments.
  const m = { ...SDXL, lora_params_m_per_rank: 1.45 } as unknown as TrainModelSpec;
  const got = estimateVram(cfg({ rank: 16, optimizer: "adamw" }), m)!.optimizer;
  assert.ok(Math.abs(got - (1.45 * 16 * 1e6 * 16) / 1e9) < 1e-9, `got ${got}`);
});

test("a model with no measured parameter count keeps the old derivation", () => {
  const got = estimateVram(cfg({ rank: 16 }), SDXL)!.optimizer;
  assert.ok(got > 0, "an unmeasured model still reports an optimizer cost");
});

test("quantization raises activations rather than leaving them alone", () => {
  // The weights it shrinks are dequantized per operation, and those buffers
  // are live memory: measured x1.62 (SD 1.5) and x1.52 (FLUX.2 Klein) at the
  // same resolution. Modelling only the weight saving under-predicted exactly
  // the runs people quantize.
  const plain = estimateVram(cfg({ batch_size: 1 }), SDXL)!;
  const int8 = estimateVram(cfg({ batch_size: 1, quantization: "int8" }), SDXL)!;
  assert.ok(int8.activations > plain.activations,
            `int8 should hold MORE per image, got ${int8.activations} vs ${plain.activations}`);
  assert.ok(Math.abs(int8.activations / plain.activations - 1.6) < 1e-9);
  // …while still saving on the weights, which is the point of doing it.
  assert.ok(int8.weights < plain.weights);
});

test("a cadence countdown reads the RUN's figure, never the overruled one", () => {
  // The run has reported: that is the answer, whatever the config says.
  assert.equal(cadenceSteps(120, 2, 500), 120);
  assert.equal(cadenceSteps(10, 0, 10), 10);
  // Not started yet. A STEP cadence is exact without the run...
  assert.equal(cadenceSteps(0, 0, 500), 500);
  assert.equal(cadenceSteps(undefined, undefined, 500), 500);
  // ... and an EPOCH one is not knowable, so it draws no dot rather than a
  // countdown to the step field the epoch setting overruled.
  assert.equal(cadenceSteps(0, 2, 500), 0);
  assert.equal(cadenceSteps(undefined, 2, 500), 0);
  // Nothing set at all is nothing to count down to.
  assert.equal(cadenceSteps(0, 0, 0), 0);
});

test("a conflicting toggle locks OFF, never on", () => {
  // The whole rule: a disabled control must not be the only way out of the
  // state it is in. Turning the text encoder's training on used to disable
  // the offload row while it was ON — a config the backend refuses, with the
  // one control that could have fixed it greyed out.
  assert.equal(toggleLocked(true, false), true);   // cannot be turned ON
  assert.equal(toggleLocked(true, true), false);   // ... but always off
  assert.equal(toggleLocked(false, true), false);
  assert.equal(toggleLocked(false, false), false);
});

test("offloading says why while the encoder is trained; quantizing is allowed", () => {
  const base = defaultTrainingConfig(undefined);
  const on = unsupportedReasons(
    { ...base, method: "lora",
      hyper: { ...base.hyper, train_text_encoder: true } },
    undefined, "cuda:0", true);
  // Offloading is refused by the backend in that combination, so the row
  // carries the chip that says so — it was disabled with nothing but its
  // hint, which is the one thing on screen that could have explained it.
  // QUANTIZING a trained encoder is the QLoRA the backbone has always had,
  // and it is what lets T5-XXL train on a 32 GB card: no chip.
  assert.equal(on.rows["hyper.quantize_text_encoder"], undefined);
  assert.ok(on.rows["hyper.offload_text_encoder"]);
  const off = unsupportedReasons(
    { ...base, method: "lora" }, undefined, "cuda:0", true);
  assert.equal(off.rows["hyper.offload_text_encoder"], undefined);
});

test("a refusal is shown in words, without the error's class name", () => {
  class ApiError extends Error {
    constructor(m: string) { super(m); this.name = "ApiError"; }
  }
  assert.equal(errText(new ApiError("the GPU is busy")), "the GPU is busy");
  assert.equal(errText(new Error("plain")), "plain");
  assert.equal(errText(new ApiError('{"detail":"no queries"}')), "no queries");
  // A bare string still reads as itself.
  assert.equal(errText("something went wrong"), "something went wrong");
});


// ---- which adapters fit which model -----------------------------------------

const FAMILY = [
  { key: "sdxl", base: "" },
  { key: "flux2_klein", base: "" },
  { key: "flux2_klein_9b", base: "" },
  { key: "user:mine", base: "sdxl" },
  { key: "user:yours", base: "sdxl" },
] as unknown as TrainModelSpec[];

test("a custom model's adapters are the base model's adapters", () => {
  // The bug this rule fixes: an adapter trained on plain SDXL, or on another
  // SDXL finetune, could not be picked for a custom SDXL model at all.
  assert.equal(adapterFamily(FAMILY, "user:mine"), "sdxl");
  assert.ok(fitsModel(FAMILY, "sdxl", "user:mine"));
  assert.ok(fitsModel(FAMILY, "user:yours", "user:mine"));
  assert.ok(fitsModel(FAMILY, "user:mine", "sdxl"));
});

test("two releases of one architecture are not one family", () => {
  // FLUX.2 Klein 4B and 9B share an engine and are different transformers —
  // an adapter for one loads into the other with every key rejected. The
  // architecture groups the MODELS page; it does not answer this.
  assert.ok(!fitsModel(FAMILY, "flux2_klein", "flux2_klein_9b"));
});

test("a model that is gone is its own family", () => {
  // A job naming a deleted custom model must not silently read as one of
  // somebody else's, so an unknown key answers only to itself.
  assert.equal(adapterFamily(FAMILY, "user:deleted"), "user:deleted");
  assert.ok(!fitsModel(FAMILY, "user:deleted", "sdxl"));
  assert.ok(fitsModel(FAMILY, "user:deleted", "user:deleted"));
});


test("the resolutions are a SET of sizes, smallest first, never empty", () => {
  // The order fixes every index in the run's manifest, and a size named
  // twice is one size — so the picker normalizes rather than storing the
  // order things were ticked in. The backend applies the same rule and is
  // the authority; this is here so the editor shows what was stored.
  assert.deepEqual(resolutionList([768, 512, 768]), [512, 768]);
  // 0 IS A MEMBER — the model's own size — so it survives and sorts first.
  assert.deepEqual(resolutionList([512, 0]), [0, 512]);
  // Naming nothing is naming the model's own size: a run trains at some
  // size, and the config substitutes this back anyway.
  assert.deepEqual(resolutionList([]), [0]);
  // Nothing is ever stored as NaN — the rule every number field here
  // follows — and a size has to fit the buckets to be one.
  assert.deepEqual(resolutionList([512, NaN, -64, 768.4, 9999]), [512, 768]);
  // At most five, whatever is handed over: the backend refuses a longer
  // list, so the editor may not build one.
  assert.deepEqual(resolutionList([64, 128, 192, 256, 320, 384]),
                   [64, 128, 192, 256, 320]);
});

test("a bigger resolution raises the estimate and a smaller one does not", () => {
  // A batch holds one bucket, so what a card has to survive is the LARGEST
  // size the run trains at. An estimate reading the base alone would
  // under-report exactly the case somebody added the setting for.
  const plain = estimateVram(cfg({}, { resolutions: [1024] }), SDXL)!;
  const lower = estimateVram(cfg({}, { resolutions: [512, 1024] }), SDXL)!;
  const higher = estimateVram(cfg({}, { resolutions: [1024, 1536] }), SDXL)!;
  assert.equal(lower.total, plain.total);
  assert.ok(higher.total > plain.total,
            `${higher.total} should exceed ${plain.total}`);
});
