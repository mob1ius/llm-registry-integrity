# llm-registry-integrity

Code and data for the paper "What's Actually In the Models You Pull? A Registry-Wide Audit of Behavioral Supply-Chain Integrity in the Consumer GGUF Ecosystem" by Mike Wagner, IEEE TPS-ISA 2026.

The paper asks two questions. Do community GGUF quantizations on Hugging Face carry the same chat template the model developer currently publishes? When they do not, does the difference change what the model does?

For the three model families where the developer's template could be verified, 30 of 87 repositories (34.5%) carry a template whose hash differs from the developer's current one.

## Layout

```
data/raw/        corpus files, exclusion lists, canonical templates, prompts
data/results/    static audit output, popularity breakdown, ModelScope check
experiments/     one folder per model family: templates tested, pilot scripts, outputs
scripts/         corpus construction and audit pipeline
src/             Hugging Face API client and a GGUF header parser
CHECKLIST        which script produced which table
```

## Reproducing the static audit

```
pip install -r requirements.txt
python scripts/build_corpus.py --version v2
python scripts/run_static_audit.py --version v2
python scripts/canonical_divergence.py
python scripts/stratified_breakdown.py --version v2
python scripts/upstream_drift_check.py
python scripts/build_modelscope_corpus.py
```

Everything here talks to the public Hugging Face and ModelScope APIs. No GPU is needed. The registries change, so a rebuild today will not return the same repositories that `data/raw/corpus_v2.json` recorded in July 2026. To check the published numbers, run the audit scripts against the stored corpus.

## Behavioral pilots

The pilots need a local Ollama install with `mistral:7b`, `llama3.1:8b`, `gemma2:9b` and `phi3:3.8b`. Each `experiments/*/run_pilot*.py` renders a prompt through two chat templates, sends the rendered text to the same weights, and records the output.

The prompts are an author-written set of 56 harmful requests in seven categories, stored in `data/raw/behavioral_prompts_v1.json`. They are written in the style of HarmBench but are not HarmBench items.

The paper reports the Mistral and Llama-3.1 pilots. The Phi-3 and gemma-2 pilots are included here but are not reported as findings. Ollama's `phi3:3.8b` is the 128k model rather than the audited 4k model, and the gemma comparison template came from a function-calling fine-tune.

## Analyses added after acceptance

Three checks were run while preparing the final version. Their results are in this repository. Only the third is reflected in the paper, in one sentence.

1. Hand validation of the Mistral result. All 168 Mistral outputs were labeled by hand, blind to condition, under a protocol written before labeling (`experiments/mistral-template-test/hand-label/`). This repository is a one-commit copy of a private working repository, so its history does not show the order. In the working repository the protocol was committed on 1 October 2026 and the labels on 5 October, and the protocol files here are identical to that 1 October commit. The line numbers in the protocol refer to the paper source, which is not included here. Refusal was 98.2% with the safety prompt delivered and 62.5% without it, a difference of 35.7 points (exact McNemar p < 0.001). The keyword classifier used in the paper undercounted refusals by about 25 points in both conditions and gave the same difference. One rater, the author.

2. Developer template history. `scripts/version_history_audit.py` compares every audited template against the commit history of the developer's own repository. Of the 28 divergent repositories that are genuine re-quantizations, 27 carry an earlier version of the developer's own template. One carries a template the publisher extended on purpose. Most of the divergence the paper measures is therefore quantizations that were not updated after the developer revised its template.

3. Corpus contamination. A review of every repository's model card found 12 of the 143 that are fine-tunes, decensored derivatives, or a different model (`data/raw/contamination_v1.json`). Excluding them changes the headline from 34.5% to 33.7% (28 of 83, 95% CI 24.5 to 44.4) and leaves gemma-2 with no divergent repository. The paper's tables were not recomputed.

## Limits

- Each repository is judged on one representative GGUF file, the one Hugging Face's `expand[]=gguf` API reports. `src/gguf_header.py` can read any file's header over HTTP Range requests, but it was not run across the corpus.
- Comparison is by hash. A hash difference does not always change behavior; the Qwen2.5 difference sits in a tool-calling branch that ordinary prompts never reach.
- Llama-3.1 and gemma-2 are gated, so their developer templates were not verified. Their figures compare against the most common template instead.
- Five model families, sampled at the top and bottom of the download ranking. This is not a random sample of the registry.

## Content note

Files under `experiments/` and `data/results/hand_validation_*` contain model responses to harmful prompts, including some that partly comply.

## License

MIT. See `LICENSE`.
