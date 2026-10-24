# Running the LLM fallback with Ollama

Nothing here is required: without it the app works exactly as before.

## 1. Install and pull a model (Windows)

1. Install Ollama from https://ollama.com/download (it starts a background service on `http://127.0.0.1:11434`).
2. Pull a model that fits your GPU. With 4 GB of VRAM:

   | model | size | note |
   |---|---|---|
   | `qwen2.5:3b` | ~1.9 GB | default; follows JSON schemas reliably |
   | `llama3.2:3b` | ~2.0 GB | alternative |
   | `qwen2.5:1.5b` | ~1.0 GB | fastest, weakest on names |
   | `llama3.1:8b` | ~4.9 GB | does not fit a 4 GB GPU: Ollama puts some layers on the GPU and the rest on the CPU, so it is several times slower and wants ~8 GB of free RAM |

   ```
   ollama pull qwen2.5:3b
   ollama run qwen2.5:3b "say hi"     # quick check, then /bye
   ollama ps                          # shows whether it is running on GPU or CPU
   ```

## 2. Use it

```
python -m stmtai.llm.evaluate --kind scan_medium --limit 12 --out data/runs/llm_medium
```

Add `--no-model` to score only the deterministic rules, which needs no Ollama. Reads the cached OCR for the scans (or runs RapidOCR on first use), asks the model about the cells the arithmetic
could not settle, and scores the answers against the synthetic ground truth. `report.md` has the table;
`answers.jsonl` has every raw answer and why it was accepted or blocked.

To compare models on dropped-letter repair, the one error type left after the rules, use the controlled probe. It
damages real descriptions from the ground truth the way OCR does, mixes in undamaged ones as controls, and
reports how many the model restores and how many it wrongly changes:

```
python -m stmtai.llm.probe --model qwen2.5:3b --out data/runs/probe_3b
python -m stmtai.llm.probe --model llama3.1:8b --out data/runs/probe_8b
python -m stmtai.llm.probe --model llama3.1:8b --hints --out data/runs/probe_8b_hints   # also shows names seen elsewhere
```

Every probe report also lists two no-model baselines (the statement's own repeated names, and names seen on other
statements), so a model has to beat those to be worth its cost.

To switch it on in the app:

```
set STMTAI_LLM=ollama:qwen2.5:3b
python -m stmtai.api
```

`GET /health` then shows `"llm": "ollama:qwen2.5:3b"`, and each statement's `meta.llm` records how many cells were
asked, proposed, blocked (and why) and how long the model took.

## 3. If something is off

| symptom | cause |
|---|---|
| `cannot reach Ollama ... Is ollama serve running?` | start the Ollama app, or run `ollama serve` |
| `model '...' is not pulled` | `ollama pull <model>` |
| very slow | `ollama ps` shows CPU: the model did not fit on the GPU; try a smaller one |
| every answer blocked as `too_many_edits` | the model is rewriting names; try another model or check `answers.jsonl` |

Other settings: `OLLAMA_HOST` (default `http://127.0.0.1:11434`), `STMTAI_LLM_MODEL` (default model when
`STMTAI_LLM=ollama`).
