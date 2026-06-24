#!/usr/bin/env python3
"""Summarize sa-bench result JSONs as points on the SemiAnalysis InferenceMAX
"Token Throughput per GPU vs. Interactivity" curve.

For each concurrency stage it computes:
  * interactivity (tok/s/user)  = 1000 / mean_TPOT_ms   (the chart's X axis; ~1/TPOT)
  * throughput / GPU (tok/s/gpu) = output_throughput / NUM_GPUS   (the chart's Y axis)

NUM_GPUS must be the *total* GPUs in the P+D deployment, since InferenceMAX
amortizes prefill GPUs into the per-GPU cost:
  mid-curve  (1P/1D, DEP8) = 16    high-tpt (2P/1D) = 24    max-tpt (3P/1D) = 32

Usage:  python3 sa-bench/summarize.py [RESULTS_DIR] [NUM_GPUS]
        (defaults: ./sa-bench-results  16)
Stdlib only — runs locally on the JSONs pulled by `just sa-bench-results`.
"""
import glob
import json
import os
import sys


def load(path):
    with open(path) as f:
        return json.load(f)


def main():
    results_dir = sys.argv[1] if len(sys.argv) > 1 else "sa-bench-results"
    num_gpus = int(sys.argv[2]) if len(sys.argv) > 2 else 16

    files = sorted(glob.glob(os.path.join(results_dir, "**", "*.json"), recursive=True))
    if not files:
        print(f"No result JSONs found under {results_dir!r}. "
              f"Run `just sa-bench-results` first.", file=sys.stderr)
        sys.exit(1)

    rows = []
    for path in files:
        try:
            d = load(path)
        except (json.JSONDecodeError, OSError) as e:
            print(f"skip {path}: {e}", file=sys.stderr)
            continue
        # pytorch-benchmark-format sidecar files don't have these keys.
        if "output_throughput" not in d or "max_concurrency" not in d:
            continue
        conc = d.get("max_concurrency")
        completed = d.get("completed", 0) or 0
        num_prompts = d.get("num_prompts", 0) or 0
        out_tps = d.get("output_throughput", 0.0) or 0.0
        total_tps = d.get("total_token_throughput", 0.0) or 0.0
        tpot = d.get("mean_tpot_ms", 0.0) or 0.0
        ttft = d.get("mean_ttft_ms", 0.0) or 0.0
        e2el = d.get("mean_e2el_ms", 0.0) or 0.0

        failed = completed == 0
        interactivity = (1000.0 / tpot) if tpot > 0 else 0.0
        per_user_share = (out_tps / conc) if conc else 0.0
        # InferenceMAX chart Y = TOTAL (input+output) tokens/s / total GPUs.
        total_per_gpu = total_tps / num_gpus if num_gpus else 0.0
        out_per_gpu = out_tps / num_gpus if num_gpus else 0.0

        rows.append({
            "conc": conc, "completed": completed, "num_prompts": num_prompts,
            "failed": failed, "out_tps": out_tps, "total_tps": total_tps,
            "total_per_gpu": total_per_gpu, "out_per_gpu": out_per_gpu,
            "tpot": tpot, "interactivity": interactivity,
            "per_user_share": per_user_share, "ttft": ttft, "e2el": e2el,
            "file": os.path.basename(path),
        })

    rows.sort(key=lambda r: (r["conc"] is None, r["conc"]))

    print(f"\nsa-bench summary  ({results_dir},  NUM_GPUS={num_gpus})")
    print("=" * 110)
    hdr = (f"{'conc':>6}  {'ok/total':>11}  {'total/GPU':>10}  "
           f"{'out tok/s':>10}  {'TPOT ms':>8}  {'interact':>9}  "
           f"{'/user':>7}  {'TTFT s':>7}")
    print(hdr)
    print(f"{'':>6}  {'':>11}  {'(chart Y)':>10}  {'(total)':>10}  {'':>8}  "
          f"{'1/TPOT(X)':>9}  {'eff':>7}  {'(mean)':>7}")
    print("-" * 110)
    for r in rows:
        flag = "  FAILED" if r["failed"] else ""
        print(f"{r['conc']:>6}  {r['completed']:>5}/{r['num_prompts']:<5}  "
              f"{r['total_per_gpu']:>10.0f}  {r['out_tps']:>10.0f}  "
              f"{r['tpot']:>8.1f}  {r['interactivity']:>9.1f}  "
              f"{r['per_user_share']:>7.1f}  {r['ttft']/1000:>7.1f}{flag}")
    print("=" * 110)

    good = [r for r in rows if not r["failed"]]
    if good:
        print("\n# plottable: interactivity(tok/s/user), TOTAL-tput_per_gpu(tok/s/gpu)  [X, Y for the InferenceMAX chart]")
        for r in good:
            print(f"{r['interactivity']:.2f}, {r['total_per_gpu']:.2f}   # conc={r['conc']}")
    if any(r["failed"] for r in rows):
        print("\n** Some stages FAILED (0 completed) — those points are not valid. "
              "Re-run after the server is stable.", file=sys.stderr)


if __name__ == "__main__":
    main()
