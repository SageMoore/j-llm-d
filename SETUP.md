# sa-bench end-to-end setup

Run the SemiAnalysis InferenceMAX "sa-bench" client against a DeepSeek-V4-Pro
wide-ep-lws deployment. You need **two repos**:

- **this repo** (`sage-j-llm-d`) — the sa-bench harness + the per-user istio Gateway.
- **`sage-llm-d`** — the model-server deployments (`oci-sglang-*`, `oci-mid-curve`, …)
  and the wide-ep-lws router values.

Everything is keyed off `$USER`: the gateway, the router release, and the model-server
labels all resolve to `${USER}-wide-ep-...`, so two people can share one namespace.

## Prerequisites
- `kubectl`, `helm`, `just`, `jq`, `envsubst`; a `.env` here with `KUBECONFIG` and `HF_TOKEN`.
- The **istio GatewayClass** installed in the cluster (the gateway provider).
- A clone of `sage-llm-d`; set `REPO_ROOT` to it below.

```bash
export REPO_ROOT=/path/to/sage-llm-d
export NAMESPACE=vllm
export RELEASE="${USER}-wide-ep"          # gateway -> ${USER}-wide-ep-inference-gateway-istio (matches SA_GATEWAY)
export GAIE_VERSION=v1.5.0
export ROUTER_CHART_VERSION=v0

# CRDs + namespace (skip if already present)
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api-inference-extension/releases/download/${GAIE_VERSION}/v1-manifests.yaml
# LeaderWorkerSet controller: install per https://lws.sigs.k8s.io/docs/installation/ if missing
kubectl create namespace ${NAMESPACE} --dry-run=client -o yaml | kubectl apply -f -

# TWO HF-token secrets (model servers use llm-d-hf-token; the sa-bench job uses hf-secret)
kubectl create secret generic llm-d-hf-token -n ${NAMESPACE} --from-literal=HF_TOKEN=$HF_TOKEN --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic hf-secret      -n ${NAMESPACE} --from-literal=HF_TOKEN=$HF_TOKEN --dry-run=client -o yaml | kubectl apply -f -
```

## 1. Front door — gateway (this repo)
```bash
just deploy-gateway     # renders gateway.yaml with your $USER and applies it
```
Creates `Gateway ${USER}-wide-ep-inference-gateway`; istio reconciles it into
`svc/${USER}-wide-ep-inference-gateway-istio` (the sa-bench target).

## 2. Front door — router + EPP + HTTPRoute (sage-llm-d, helm)
```bash
helm install ${RELEASE} \
    oci://ghcr.io/llm-d/charts/llm-d-router-gateway-dev \
    -f ${REPO_ROOT}/guides/recipes/router/base.values.yaml \
    -f ${REPO_ROOT}/guides/recipes/router/features/httproute-flags.yaml \
    -f ${REPO_ROOT}/guides/wide-ep-lws/router/wide-ep-lws.values.yaml \
    --set provider.name=istio \
    -n ${NAMESPACE} --version ${ROUTER_CHART_VERSION}
```
Discovers model-server pods by label `llm-d.ai/guide: wide-ep-lws` (model-agnostic).

## 3. Model server — pick one deployment (sage-llm-d, kustomize)
```bash
kubectl apply -n ${NAMESPACE} -k ${REPO_ROOT}/guides/wide-ep-lws/modelserver/gpu/vllm-deepseek-v4/deployments/oci-sglang-conc512-8p16d
```
Other points: `oci-sglang-conc1536-16p16d`, `oci-sglang-conc4096-32p16d`, `oci-mid-curve`, …
Pods take **7–10 min** to become Ready (large MoE startup).

## 4. Verify + benchmark
```bash
kubectl -n ${NAMESPACE} get pods                                          # epp, gateway, prefill/decode
kubectl -n ${NAMESPACE} get svc ${USER}-wide-ep-inference-gateway-istio    # SA_BASE_URL target
# from this repo:
just sa-bench 512                          # positional args; ISL/OSL default to 8192/1024
just sa-bench-logs                         # wait for "sa-bench complete"
just sa-bench-results conc512
just sa-bench-summary 24 sa-bench-results/conc512    # NUM_GPUS = TOTAL prefill+decode GPUs
```
`sa-bench-summary` NUM_GPUS per point: conc512 8P/16D=24, conc1536 16P/16D=32,
conc4096 32P/16D=48.

## Teardown
```bash
kubectl delete -n ${NAMESPACE} -k ${REPO_ROOT}/guides/wide-ep-lws/modelserver/gpu/vllm-deepseek-v4/deployments/oci-sglang-conc512-8p16d
helm uninstall ${RELEASE} -n ${NAMESPACE}
just delete-gateway
```
