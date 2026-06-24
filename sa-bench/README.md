# sa-bench — SemiAnalysis InferenceMAX benchmark client

Vendored, **unmodified**, from SemiAnalysis's InferenceX repo:

> `SemiAnalysisAI/InferenceX` → `utils/bench_serving/`
> (`benchmark_serving.py`, `backend_request_func.py`, `benchmark_utils.py`, `encoding_dsv4.py`)

This is the exact client behind the `benchmark: { type: "sa-bench" }` blocks in their
`srt-slurm-recipes/vllm/deepseek-v4/8k1k/*.yaml` GB200 recipes. It is a fork of vLLM's
`benchmark_serving.py` with a DeepSeek-V4 chat encoder (`encoding_dsv4.py`, the `--dsv4`
flag) that emits the `<bos><｜User｜>…<｜Assistant｜><think>` framing the model expects.

We run it against the **llm-d front door** (the wide-ep-lws deployment's Istio gateway →
InferencePool) so the gateway routes prefill/decode appropriately, rather than hitting a
pod directly.

## Methodology (what the recipe actually does)

For the GB200 8k1k recipes, per concurrency point `C`:

| knob | value | flag |
|---|---|---|
| dataset | random tokens | `--dataset-name random` |
| input len | 8192 (fixed) | `--random-input-len 8192 --random-range-ratio 1.0` |
| output len | 1024 (fixed, forced) | `--random-output-len 1024 --ignore-eos` |
| load shape | closed-loop, `C` in flight | `--max-concurrency C --request-rate inf` |
| requests | `C × 10` | `--num-prompts $((C*10))` |
| warmups | `C × 2` (excluded) | `--num-warmups $((2*C))` |
| chat template | DeepSeek-V4 encoder | `--use-chat-template --dsv4 --trust-remote-code` |
| metrics | ttft, tpot, itl, e2el | `--percentile-metrics ttft,tpot,itl,e2el` |

`--request-rate inf` + `--max-concurrency C` = saturated closed loop (exactly `C`
requests in flight at all times). Each concurrency value is one point on the
latency-vs-throughput curve. `range_ratio 1.0` pins lengths exactly (lower=upper=seq_len),
and the client subtracts the chat-template token overhead so the final prompt lands at ~8192.

Concurrency sweeps from the upstream recipes:
- `disagg-gb200-mid-curve-megamoe` (1P/1D): **256 × 512 × 1024**
- `disagg-gb200-high-tpt-megamoe` (2P/1D): **4096**
- `disagg-gb200-max-tpt-megamoe`  (3P/1D): **4096**

## Running

From the repo root:

```bash
just sa-bench                       # mid-curve sweep: 256x512x1024, isl 8192, osl 1024
just sa-bench 4096                  # high/max-tpt point
just sa-bench 256x512x1024 8192 1024
just sa-bench-logs                  # follow the job
just sa-bench-results               # copy result JSONs locally to ./sa-bench-results/
```

Only the tokenizer is downloaded (needs `hf-secret`); the ~850 GB model weights are not.
