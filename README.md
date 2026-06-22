# PITH v2 — Inter-Agent Payload Compressor (SIZE_GATE = 10 000 chars)

> *"Natural systems that evolve toward efficiency follow logarithmic distributions. Language did. Our agents should too."*

PITH eliminates token waste in multi-agent AI pipelines. It compresses verbose inter-agent payloads using **Shannon local information scoring** validated by Benford's Law structural integrity — zero external dependencies, no API calls, works offline.

---

## Dual Nature

PITH ships as two complementary interfaces from a single codebase:

| Mode | Interface | Use case |
|------|-----------|----------|
| **Claude Code Skill** | `pith.skill` + `scripts/compress.py` | Trigger by phrase, orchestration, no install |
| **MCP Server** | `src/mcp_server_pith/` + `pyproject.toml` | Universal JSON-RPC tool callable by any MCP client |

Both interfaces share identical compression logic. The skill is for contextual activation by a Claude agent; the MCP server is for programmatic integration into any client that speaks the Model Context Protocol.

---

## Why 10 000 Characters?

The SIZE_GATE floor exists for two independent reasons:

**1. Benford statistical stability.** Benford's Law MAD is a ratio computed over sentence-length first-digit frequencies. It becomes statistically reliable only when the sample is large enough: at least ~50–100 sentences. An average English sentence is 80–100 characters, so 10 000 chars ≈ 100–125 sentences — the minimum corpus for a low-variance MAD estimate. Below this threshold, a single unusually long or short sentence can move MAD by several percentage points, causing the Benford gate to misfire (false-positive rollback) and degrading compression quality unpredictably.

**2. Context ROI.** Token-level pruning has non-zero per-token overhead: Shannon scoring, threshold lookup, whitelist check, polarity checksum. On a 500-char payload this overhead exceeds the savings. On a 10 000+ char payload, the overhead is amortised across hundreds of tokens and the net reduction (typically 25–50%) far outweighs the cost. Below the gate, the correct action is passthrough — zero processing, zero risk, < 1 ms.

These two constraints converge on the same floor. `SIZE_GATE = 10000` is the point where statistical validity and computational ROI both hold.

---

## Theory: Why Agents Overpay

### The Nash Equilibrium of Inter-Agent Communication

In game theory, a Nash equilibrium is a strategy profile where no player can improve their outcome by unilaterally deviating. Applied to multi-agent communication, the equilibrium is the state where each agent transmits the *minimum information* the receiving agent needs to act optimally.

Every token above that minimum is a deviation from equilibrium: a pure cost with no strategic return.

In practice, agents violate this equilibrium systematically. An agent returning a tool result includes preamble, transitional prose, filler acknowledgements, and connector sentences — none of which affect the next agent's decision. Over a five-agent chain, this compounds: each agent inherits the verbosity of all predecessors, producing thousands of wasted tokens before the final answer.

PITH is the enforcement mechanism for Nash equilibrium in agent communication: it automatically finds and removes the tokens that carry no strategic information.

### Shannon Information: Measuring Token Value Exactly

Claude Shannon's information theory (1948) defines the self-information of an event with probability *P* as:

```
I(w) = -log₂(P(w))    bits
```

Applied to language: a word appearing with frequency *P(w) = count(w) / total* carries *I(w) = -log₂(P(w))* bits of information. Rare words carry more bits; common words carry fewer.

**PITH v2 computes I(w) locally within each payload** — no external corpus, no model call. P(w) is the empirical word frequency in the input text itself. This means:

- "the" appearing 40 times in a 200-word text: I("the") = -log₂(0.2) ≈ 2.3 bits
- "photovoltaic" appearing once: I("photovoltaic") = -log₂(0.005) ≈ 7.6 bits

Tokens below the information threshold (determined by `target_reduction`) are pruned. Tokens at or above the threshold are kept.

### Why the Lookup Table Eliminates Computational Latency

Every Shannon computation calls `log₂`. In Python, `math.log2(n)` involves a C-level function call with floating-point arithmetic — fast, but called thousands of times for a large payload.

PITH v2 uses a **global LOG_CACHE dictionary** (`dict[int, float]`):

```python
LOG_CACHE: dict[int, float] = {}

def _log2(n: int) -> float:
    v = LOG_CACHE.get(n)
    if v is None:
        v = math.log2(n) if n > 0 else 0.0
        LOG_CACHE[n] = v
    return v
```

Word counts are always integers. The dictionary lookup is O(1) at the C level — Python's dict is a hash map with C-implemented `get()`. After the first call for a given count, every subsequent call for the same count is a pure hash lookup with no floating-point computation. Across a 500-word payload with repeated word frequencies, this eliminates the majority of `math.log2` calls.

This keeps PITH v2 in Python stdlib — no NumPy, no external dependencies — while matching the performance of native implementations for realistic payload sizes.

### Benford's Law: Structural Integrity Gate

Frank Benford (1938) observed that in naturally occurring numerical datasets, leading digits follow a logarithmic distribution: ~30.1% begin with 1, ~17.6% with 2, decreasing to ~4.6% for 9.

Sentence lengths in natural human writing exhibit the same signature. PITH computes the **Mean Absolute Deviation (MAD)** of sentence-length first digits from the Benford curve:

```
MAD = Σ |observed_pct(d) - benford_pct(d)| / 9    for d in {1..9}
```

If compression causes MAD to exceed 2× the original, PITH halves the pruning aggressiveness and retries (max 3 attempts). The compressor cannot produce output structurally more artificial than its input.

---

## Architecture (v2)

```
INPUT PAYLOAD (verbose agent output)
         │
         ▼
┌────────────────────────────────────────────────┐
│  1. SIZE GATE                                  │
│     If payload < 10 000 chars → passthrough    │
│     Returns immediately (< 1ms)                │
│     Guarantees ≥ 100 sentences for Benford     │
└─────────────────────┬──────────────────────────┘
                      │
                      ▼
┌────────────────────────────────────────────────┐
│  2. PARSER                                     │
│     Quarantine: code blocks, inline code,      │
│     JSON, URLs, file paths, XML/HTML tags      │
│     → These are NEVER scored or removed        │
└─────────────────────┬──────────────────────────┘
                      │ natural language only
                      ▼
┌────────────────────────────────────────────────┐
│  3. SHANNON LOCAL PROFILING                    │
│     Count word frequencies in payload          │
│     I(w) = log₂(total) - LOG_CACHE[count(w)]  │
│     O(1) log2 via global LUT                   │
└─────────────────────┬──────────────────────────┘
                      │
                      ▼
┌────────────────────────────────────────────────┐
│  4. ADAPTIVE TOKEN PRUNING (per sentence)      │
│     Filler pre-pass: drop boilerplate sentences│
│     Threshold = all_scores[target_reduction×N] │
│     Whitelist: if/not/never/nor/etc. → kept    │
│     Prune tokens where I(w) < threshold        │
└─────────────────────┬──────────────────────────┘
                      │
                      ▼
┌────────────────────────────────────────────────┐
│  5. POLARITY MICRO-CHECKSUM (per sentence)     │
│     Count negation particles before pruning    │
│     Count again after pruning                  │
│     If counts differ → restore original sent.  │
└─────────────────────┬──────────────────────────┘
                      │
                      ▼
┌────────────────────────────────────────────────┐
│  6. BENFORD MACRO GATE (retry loop)            │
│     Compute MAD of sentence-length digits      │
│     If MAD > 2× original → halve reduction,    │
│     re-run pruning. Max 3 attempts.            │
└─────────────────────┬──────────────────────────┘
                      │
                      ▼
┌────────────────────────────────────────────────┐
│  7. REASSEMBLER + META-CONTEXT RECEPTOR        │
│     Restore quarantined blocks                 │
│     Wrap output in XML envelope                │
└─────────────────────┬──────────────────────────┘
                      │
                      ▼
OUTPUT:
<pith_optimization_layer version='2.0' engine='shannon_local' ratio='0.65'>
  <compressed payload>
</pith_optimization_layer>
```

**Passthrough conditions** (PITH skips compression automatically):
- Payload below 10 000 chars (size gate — guarantees Benford stability and positive ROI)
- Fewer than 3 sentences after parsing
- Input is pure JSON or pure code (fully quarantined, nothing to compress)

---

## Module Reference

| Module | Role | Key Mechanism |
|--------|------|---------------|
| **Size Gate** | Fast-exit for sub-threshold payloads | `len(text) < 10000` — ensures Benford stability (≥100 sentences) and positive compute ROI |
| **Shannon LUT** | O(1) log₂ lookups | Global `LOG_CACHE: dict[int, float]` indexed by word count |
| **Filler Pre-Pass** | Sentence-level boilerplate removal | `FILLER_PATTERNS` regex: *"I believe"*, *"No errors"*, *"The search was"*, etc. |
| **Adaptive Pruner** | Token-level information pruning | Threshold = `all_scores[int(reduction × N)]`; keep if `I(w) >= threshold` |
| **Syntactic Cage** | Logical connectors always kept | `LOGICAL_WHITELIST`: if, not, never, nor, but, because, and, or, etc. |
| **Polarity Micro-Checksum** | Prevents meaning inversion | Negation particle count before/after pruning; rollback on mismatch |
| **Benford Gate** | Structural integrity enforcement | MAD > 2× original → `current_reduction *= 0.5`, retry (max 3) |
| **Meta-Context Receptor** | Output envelope | `<pith_optimization_layer version='2.0' engine='shannon_local' ratio='…'>` |

---

## Installation

### Mode 1: Claude Code Skill (no install)

Place the repository contents in your Claude Code skills directory or install via the skill manager. PITH activates contextually based on trigger phrases — no configuration required.

**Trigger phrases** (from `pith.skill`):
- *"compress this for the next agent"*
- *"pith this output"*
- *"slim down this payload"*
- *"reduce context before passing"*
- *"this tool result is too long"*
- *"optimize this handoff"*
- Proactive trigger: any intermediate agent output > ~300 tokens in a multi-agent chain

### Mode 2: MCP Server

#### Via `uvx` (recommended — no install)

```bash
uvx mcp-server-pith
```

#### Via `pip`

```bash
pip install mcp-server-pith
python -m mcp_server_pith
```

#### Claude Desktop configuration

```json
{
  "mcpServers": {
    "pith": {
      "command": "uvx",
      "args": ["mcp-server-pith"]
    }
  }
}
```

On Windows (CP1252 terminal):

```json
{
  "mcpServers": {
    "pith": {
      "command": "cmd",
      "args": ["/c", "uvx", "mcp-server-pith"]
    }
  }
}
```

#### From source

```bash
git clone https://github.com/VjAlbert/pith-skill.git
cd pith-skill
uv sync --locked
uv run mcp-server-pith
```

### Mode 3: Standalone CLI (zero dependencies)

```bash
# No install — pure Python stdlib
python3 scripts/compress.py --help
```

---

## CLI Reference

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--payload TEXT` | string | — | Text to compress. Alternative to stdin pipe. |
| `--ratio FLOAT` | float | `0.7` | Keep ratio (0.1–1.0). `target_reduction = 1 - ratio`. |
| `--json` | flag | off | Output full JSON object with compressed text + metadata. |

### Compression ratio guide

| Flag | Ratio | Reduction | Best For |
|------|-------|-----------|----------|
| *(default)* | `0.7` | 30% | Most agent tool results and reasoning traces |
| `--ratio 0.8` | 0.8 | 20% | Sensitive outputs where context loss is risky |
| `--ratio 0.5` | 0.5 | 50% | Bulk search results, long summaries |
| `--ratio 0.3` | 0.3 | 70% | Context window critical — use with caution |

### CLI usage examples

```bash
# Pipe from stdin
echo "Your verbose agent output here..." | python3 scripts/compress.py

# Explicit payload
python3 scripts/compress.py --payload "Long agent result..." --ratio 0.5

# JSON output for programmatic use
python3 scripts/compress.py --payload "Long agent result..." --json

# Aggressive compression via pipe
cat agent_output.txt | python3 scripts/compress.py --ratio 0.4

# Capture compressed output
COMPRESSED=$(echo "$RAW_OUTPUT" | python3 scripts/compress.py)
```

### Output format

**Default (human-readable):**
```
[PITH v2.0 | ✓ | -38% tokens | benford:4.1% | compressed]
<pith_optimization_layer version='2.0' engine='shannon_local' ratio='0.620'>
<compressed payload here>
</pith_optimization_layer>
```

**JSON (`--json`):**
```json
{
  "compressed": "<pith_optimization_layer ...>\n...\n</pith_optimization_layer>",
  "meta": {
    "action": "compressed",
    "original_tokens": 487,
    "compressed_tokens": 302,
    "ratio": 0.620,
    "saved_pct": 38.0,
    "sentences_original": 22,
    "sentences_kept": 18,
    "original_benford_mad": 4.1,
    "compressed_benford_mad": 4.2,
    "benford_ok": true,
    "preserved_blocks": 0,
    "engine": "shannon_local",
    "version": "2.0"
  }
}
```

Header legend: `✓` = Benford gate passed, `⚠` = structural warning (MAD elevated), `passthrough` = compression skipped automatically.

---

## MCP Tools

When running as an MCP server, PITH exposes two tools over JSON-RPC:

### `compress`

Compress a payload and return the result with a metadata header string.

**Input schema:**
```json
{
  "payload": "string (required)",
  "ratio": "number 0.1–1.0 (optional, default: 0.7)"
}
```

**Output:** plain text with `[PITH v2.0 | ✓ | -N% tokens | benford:X% | action]` header followed by `<pith_optimization_layer>` XML envelope.

### `compress_with_metadata`

Same compression, returns a JSON object with full metadata.

**Output:** JSON object with `compressed` and `meta` fields (see schema above).

---

## Python Integration

### Direct import (package installed)

```python
from mcp_server_pith.compress import compress, DEFAULT_RATIO

text = "Your verbose inter-agent payload..."
compressed_text, meta = compress(text, target_ratio=DEFAULT_RATIO)

if meta["action"] == "compressed":
    print(f"Compressed {meta['saved_pct']:.0f}%: {meta['original_tokens']} → {meta['compressed_tokens']} tokens")
    print(f"Engine: {meta['engine']} v{meta['version']}")
    print(f"Benford MAD: {meta['compressed_benford_mad']:.1f}% ({'✓' if meta['benford_ok'] else '⚠'})")
else:
    print(f"Passthrough: {meta.get('reason', 'payload too short')}")
```

### Subprocess (no import — any Python version)

```python
import subprocess, json

def pith(payload: str, ratio: float = 0.7) -> tuple[str, dict]:
    result = subprocess.run(
        ["python3", "scripts/compress.py", "--ratio", str(ratio), "--json"],
        input=payload, capture_output=True, text=True,
        cwd="/path/to/pith-skill"
    )
    data = json.loads(result.stdout)
    return data["compressed"], data["meta"]

raw = agent_research.run("Find information about X")
compressed, meta = pith(raw)
print(f"Saved {meta['saved_pct']:.0f}%")
agent_synthesis.run(compressed)
```

---

## Testing

### Run v2 unit tests

```bash
# Full suite (v2 unit tests + eval suite)
uv run pytest

# v2 unit tests only (SIZE_GATE, Shannon >=, Filler, Benford stability)
uv run pytest tests/test_pith_v2.py -v

# Eval suite only (end-to-end passthrough + metadata assertions)
uv run pytest tests/test_evals.py -v

# Run eval runner directly
python3 tests/run_evals.py
```

> **Note on SIZE_GATE = 10 000:** All short eval payloads (< 10 000 chars) correctly
> return passthrough. Compression tests in `test_pith_v2.py` use synthetically generated
> payloads exceeding the threshold. Run `uv run pytest -v` to verify all 22 tests pass.

### Test coverage

| Test class | What it verifies |
|------------|-----------------|
| `TestSizeGate` | Payloads < 300 chars return unchanged in < 1ms |
| `TestShannonIntegrity` | Rare words (acronyms, technical terms) survive pruning; LOG_CACHE populated |
| `TestPolarityProtection` | Whitelist words never pruned; negation particles preserved; rollback triggers |
| `TestBenfordGate` | No infinite loop; retries bounded by `MAX_RETRIES`; threshold halves on failure |
| `TestMetaContextReceptor` | Output wrapped in `<pith_optimization_layer>` XML with version and engine attrs |
| Eval suite (TC01–TC08) | End-to-end: filler removal, code/URL/JSON preservation, passthrough, Benford metadata |

---

## Benchmarks

From eval suite (`tests/evals.json`, 8 test cases):

| Payload type | Ratio | Savings | Benford |
|---|---|---|---|
| Verbose web search result | `0.7` (default) | ~30% | ✓ |
| Verbose web search result | `0.4` (aggressive) | ~55% | ✓ |
| Code execution result + explanation | `0.7` | ~25% (code intact) | ✓ |
| Short payload (< 300 chars) | — | 0% passthrough | ✓ |
| JSON payload | — | filler removed | ✓ |
| Payload with inline URLs | `0.7` | ~30% (URLs intact) | ✓ |
| `--json` metadata output | `0.3` | Includes full meta | ✓ |

---

## Comparison

| Tool | Target | Mechanism |
|------|--------|-----------|
| **Caveman** | Agent → User output | Rewrites prose to caveman style |
| **LLMLingua** | User → Agent prompt | Token-level perplexity pruning (requires model) |
| **Selective Context** | Retrieved documents | Key sentence extraction |
| **PITH** | **Agent → Agent handoff** | Shannon local I(w) + Benford integrity gate |

PITH fills the gap no other tool targets: the payload exchanged *between* agents in a pipeline.

Key differentiators:
- Zero external dependencies (no model call, no corpus, no API)
- O(1) log₂ via global LOG_CACHE — deterministic, fast, pure Python stdlib
- Logical whitelist protects connectors; polarity checksum prevents meaning inversion
- Structural integrity gate prevents over-compression (Benford MAD)
- Works on any text without training or adaptation

---

## Limitations

- Requires ≥ 3 sentences for meaningful compression; shorter payloads pass through unchanged
- Shannon scoring is local to the payload — a word rare in the input but common globally still scores as rare
- Benford validation is most reliable on texts with 8+ sentences
- Not suitable for legally sensitive content where exact phrasing is contractually required
- Filler pre-pass uses regex matching — unconventional filler phrasing may not be caught

---

## What Is Always Preserved

The parser quarantines these structures before any processing and reinserts them unchanged:

| Structure | Pattern |
|-----------|---------|
| Fenced code blocks | ` ```...``` ` |
| Inline code | `` `...` `` |
| JSON objects | `{...}` (≥ 10 chars) |
| JSON arrays | `[...]` (≥ 10 chars) |
| URLs | `https?://...` |
| File paths | `/word/word/...` (2+ segments) |
| XML/HTML tags | `<tag>...</tag>` |

Additionally, the `LOGICAL_WHITELIST` ensures these words are never pruned: `if`, `then`, `else`, `because`, `not`, `never`, `non`, `but`, `however`, `although`, `unless`, `nor`, `neither`, `without`, `no`, `and`, `or`.

---

## Project Structure

```
pith-skill/
├── src/
│   └── mcp_server_pith/     # MCP server package (pip-installable)
│       ├── __init__.py
│       ├── __main__.py
│       ├── compress.py      # Core v2 compression logic (Shannon LUT + Benford gate)
│       └── server.py        # MCP tool registration + JSON-RPC handler
├── scripts/
│   └── compress.py          # Standalone CLI (same v2 logic, no install required)
├── tests/
│   ├── evals.json           # 8 eval test cases
│   ├── run_evals.py         # Eval runner
│   ├── test_evals.py        # Pytest entry point for eval suite
│   └── test_pith_v2.py      # v2 unit tests (Shannon, polarity, Benford, XML receptor)
├── pyproject.toml           # Build config (hatchling + uv)
├── uv.lock                  # Locked dependency tree
├── pith.skill               # Claude Code skill manifest + instructions
├── SKILL.md                 # Skill documentation
└── README.md                # This file
```

---

## Author

Created by **Albert** ([@VjAlbert](https://github.com/VjAlbert)) — developer, game theory enthusiast, and Benford's Law advocate. PITH emerged from the observation that multi-agent AI systems systematically deviate from the Nash equilibrium of communication, and that both Shannon's information theory and Benford's Law are measurable signatures of that equilibrium.

---

## Related

- [video-analyzer](https://github.com/VjAlbert/video-analyzer) — bridges video files and Claude Projects
- [Anthropic MCP Servers](https://github.com/modelcontextprotocol/servers) — the reference MCP server repository
- [Anthropic Skills](https://github.com/anthropics/skills) — the official Claude Code skills repository

---

## License

MIT
