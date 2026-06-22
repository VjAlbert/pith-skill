# PITH — Inter-Agent Payload Compressor

> *"Natural systems that evolve toward efficiency follow logarithmic distributions. Language did. Our agents should too."*

PITH eliminates token waste in multi-agent AI pipelines. It compresses verbose inter-agent payloads using Zipf word-density scoring validated by Benford's Law structural integrity check — zero external dependencies, no API calls, works offline.

---

## Dual Nature

PITH ships as two complementary interfaces from a single codebase:

| Mode | Interface | Use case |
|------|-----------|----------|
| **Claude Code Skill** | `pith.skill` + `scripts/compress.py` | Trigger by phrase, orchestration, no install |
| **MCP Server** | `src/mcp_server_pith/` + `pyproject.toml` | Universal JSON-RPC tool callable by any MCP client |

Both interfaces share identical compression logic. The skill is for contextual activation by a Claude agent; the MCP server is for programmatic integration into any client that speaks the Model Context Protocol.

---

## Theory: Why Agents Overpay

### The Nash Equilibrium of Inter-Agent Communication

In game theory, a Nash equilibrium is a strategy profile where no player can improve their outcome by unilaterally deviating. Applied to multi-agent communication, the equilibrium is the state where each agent transmits the *minimum information* the receiving agent needs to act optimally.

Every token above that minimum is a deviation from equilibrium: a pure cost with no strategic return.

In practice, agents violate this equilibrium systematically. An agent returning a tool result includes preamble, transitional prose, filler acknowledgements, and connector sentences — none of which affect the next agent's decision. Over a five-agent chain, this compounds: each agent inherits the verbosity of all predecessors, producing thousands of wasted tokens before the final answer.

PITH is the enforcement mechanism for Nash equilibrium in agent communication: it automatically finds and removes the tokens that carry no strategic information.

### Zipf's Law: Identifying High-Information Sentences

George Kingsley Zipf (1949) demonstrated that in natural language, word frequency follows a power law. The most common word appears roughly twice as often as the second most common, three times the third, and so on — a hyperbolic distribution.

The compression consequence is mathematically elegant: **rare words carry more information per token**. A sentence dense with low-frequency (long, technical, domain-specific) vocabulary carries more information per token than a sentence full of common connectives.

PITH uses **word length ≥ 7 characters** as a zero-latency proxy for Zipf rarity. Empirically, rare words are systematically longer; this heuristic requires no external corpus, no model call, and no runtime dependencies. Each sentence receives a density score:

```
score = (n_dense / n_content) × 0.6 + min(mean_word_length / 12, 1.0) × 0.4
```

Where `n_dense` = words with ≥ 7 chars not in a common-long-word exclusion list, and `n_content` = non-stopword words with length > 2. Sentences matching known filler patterns (e.g., *"I believe"*, *"The search was"*, *"No errors"*) receive a 75% score penalty. The top N% of sentences by score are retained.

### Benford's Law: Structural Integrity Gate

Frank Benford (1938) observed that in naturally occurring numerical datasets, leading digits follow a logarithmic distribution: ~30.1% of numbers begin with 1, ~17.6% with 2, ~12.5% with 3, decreasing to ~4.6% for 9.

Sentence lengths in natural human writing exhibit the same signature. Short sentences dominate (first digit 1–3), long sentences are rare (first digit 7–9), and the distribution approximates the Benford logarithmic curve. This is a consequence of natural language having evolved toward communicative efficiency under cognitive constraints.

AI-generated text and over-compressed text systematically deviate from this distribution. They tend toward uniform sentence lengths, producing a flatter first-digit distribution. The **Mean Absolute Deviation (MAD)** from the expected Benford distribution is therefore a structural integrity signal:

```
MAD = Σ |observed_pct(d) - benford_pct(d)| / 9    for d in {1..9}
```

**Empirical validation on 5 texts, 82 segments:**

| Text | MAD | Verdict |
|------|-----|---------|
| Darwin, *On the Origin of Species* (1859) | 5.0% | ✓ natural |
| Melville, *Moby-Dick* (1851) | 3.1% | ✓ natural |
| AI-generated scientific text | 7.5% | ✗ artificial |
| AI-generated narrative text | 13.7% | ✗ artificial |

PITH uses this as its compression quality gate: if compression increases MAD beyond 2× the original, the ratio is relaxed by 2 sentences and the compression is retried (max 3 attempts). The compressor cannot produce output more structurally artificial than the input.

**Hypothesis:** an agent communicating at its Nash equilibrium produces Benford-compliant text. Deviation from Benford in compressed output signals over-compression — a departure from the information-theoretic optimum.

---

## Architecture

```
INPUT PAYLOAD (verbose agent output)
         │
         ▼
┌────────────────────────────────────────────────┐
│  1. PARSER                                     │
│     Quarantine: code blocks, inline code,      │
│     JSON objects/arrays, URLs, file paths,     │
│     XML/HTML tags                              │
│     → These are NEVER scored or removed        │
└─────────────────────┬──────────────────────────┘
                      │ natural language only
                      ▼
┌────────────────────────────────────────────────┐
│  2. SENTENCE SPLITTER                          │
│     Split on [.!?] followed by uppercase       │
│     Minimum 2 words per sentence               │
│     Passthrough if < 5 sentences              │
└─────────────────────┬──────────────────────────┘
                      │
                      ▼
┌────────────────────────────────────────────────┐
│  3. ZIPF SCORER                                │
│     Score each sentence by vocabulary rarity   │
│     word length ≥ 7 chars = rare = informative │
│     Filler patterns penalised 75%              │
└─────────────────────┬──────────────────────────┘
                      │
                      ▼
┌────────────────────────────────────────────────┐
│  4. BENFORD GATE (retry loop)                  │
│     Select top N% by score                     │
│     Compute MAD before and after               │
│     If MAD > 2× original → relax N by 2, retry │
│     Max 3 attempts → accept best result        │
└─────────────────────┬──────────────────────────┘
                      │
                      ▼
┌────────────────────────────────────────────────┐
│  5. REASSEMBLER                                │
│     Restore original sentence order            │
│     Reinsert quarantined blocks                │
│     Append any orphaned preserved blocks       │
│     Add metadata header                        │
└─────────────────────┬──────────────────────────┘
                      │
                      ▼
OUTPUT: [PITH | ✓ | -42% tokens | benford:4.3% | compressed]
        <compressed payload>
```

**Passthrough conditions** (PITH skips compression automatically):
- Fewer than 5 sentences after parsing
- Input is pure JSON or pure code block (fully quarantined, nothing to compress)
- Payload below ~300 tokens (sentence count too low)

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
| `--ratio FLOAT` | float | `0.6` | Fraction of sentences to keep (0.1–1.0). |
| `--json` | flag | off | Output full JSON object with compressed text + metadata. |

### Compression ratio guide

| Flag | Ratio | Best For |
|------|-------|----------|
| *(default)* | `0.6` | Most agent tool results and reasoning traces |
| `--ratio 0.8` | Conservative | Sensitive outputs where context loss is risky |
| `--ratio 0.4` | Aggressive | Bulk search results, long summaries |
| `--ratio 0.3` | Maximum | Context window critical — use with caution |

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
[PITH | ✓ | -42% tokens | benford:4.3% | compressed]
<compressed payload here>
```

**JSON (`--json`):**
```json
{
  "compressed": "...",
  "meta": {
    "action": "compressed",
    "original_tokens": 487,
    "compressed_tokens": 284,
    "ratio": 0.583,
    "saved_pct": 41.7,
    "sentences_original": 22,
    "sentences_kept": 13,
    "original_benford_mad": 4.1,
    "compressed_benford_mad": 4.3,
    "benford_ok": true,
    "preserved_blocks": 0
  }
}
```

Header legend: `✓` = Benford gate passed, `⚠` = structural warning (MAD elevated but within tolerance), `passthrough` = compression skipped automatically.

---

## MCP Tools

When running as an MCP server, PITH exposes two tools over JSON-RPC:

### `compress`

Compress a payload and return the result with a metadata header string.

**Input schema:**
```json
{
  "payload": "string (required)",
  "ratio": "number 0.1–1.0 (optional, default: 0.6)"
}
```

**Output:** plain text with `[PITH | ✓ | -N% tokens | benford:X% | action]` header.

### `compress_with_metadata`

Same compression, returns a JSON object with full metadata. Use for programmatic inspection of compression quality.

**Output:** JSON object with `compressed` and `meta` fields (see schema above).

---

## Python Integration

### Subprocess (no import — any Python version)

```python
import subprocess
import json

def pith(payload: str, ratio: float = 0.6) -> tuple[str, dict]:
    result = subprocess.run(
        ["python3", "scripts/compress.py", "--ratio", str(ratio), "--json"],
        input=payload,
        capture_output=True,
        text=True,
        cwd="/path/to/pith-skill"
    )
    data = json.loads(result.stdout)
    return data["compressed"], data["meta"]

# In a multi-agent pipeline
raw_output = agent_research.run("Find information about X")
compressed, meta = pith(raw_output)
print(f"Saved {meta['saved_pct']:.0f}% ({meta['original_tokens']} → {meta['compressed_tokens']} tokens)")
agent_synthesis.run(compressed)
```

### Direct import (package installed)

```python
from mcp_server_pith.compress import compress, DEFAULT_RATIO

text = "Your verbose inter-agent payload..."
compressed_text, meta = compress(text, target_ratio=DEFAULT_RATIO)

if meta["action"] == "compressed":
    print(f"Compressed {meta['saved_pct']:.0f}%: {meta['original_tokens']} → {meta['compressed_tokens']} tokens")
    print(f"Benford MAD: {meta['compressed_benford_mad']:.1f}% ({'✓' if meta['benford_ok'] else '⚠'})")
else:
    print(f"Passthrough: {meta.get('reason', 'payload too short')}")
```

### Batch pipeline with quality filtering

```python
from mcp_server_pith.compress import compress

def compress_if_needed(payload: str, ratio: float = 0.6, min_savings: float = 20.0) -> str:
    compressed, meta = compress(payload, target_ratio=ratio)
    if meta["action"] == "passthrough" or meta["saved_pct"] < min_savings:
        return payload
    return compressed

# Process a chain of agent outputs
agent_outputs = [agent.run(task) for agent in pipeline]
compressed_chain = [compress_if_needed(out) for out in agent_outputs]
```

---

## Benchmarks

From eval suite (`tests/evals.json`, 7 test cases):

| Payload type | Ratio | Savings | Benford |
|---|---|---|---|
| Verbose web search result | `0.6` (default) | ~34% | ✓ |
| Verbose web search result | `0.4` (aggressive) | ~60% | ✓ |
| Code execution result + explanation | `0.6` | ~30% | ✓ |
| Short payload (< 5 sentences) | — | 0% passthrough | ✓ |
| Pure JSON payload | — | 0% passthrough | ✓ |
| Payload with inline URLs | `0.6` | ~35% (URLs intact) | ✓ |
| `--json` metadata output | `0.6` | Includes full meta | ✓ |

---

## Comparison

| Tool | Target | Mechanism |
|------|--------|-----------|
| **Caveman** | Agent → User output | Rewrites prose to caveman style |
| **LLMLingua** | User → Agent prompt | Token-level perplexity pruning (requires model) |
| **Selective Context** | Retrieved documents | Key sentence extraction |
| **PITH** | **Agent → Agent handoff** | Zipf density + Benford integrity gate |

PITH fills the gap no other tool targets: the payload exchanged *between* agents in a pipeline. This is where token waste compounds — each agent inherits the verbosity of the previous one. Over a five-agent chain, this can mean thousands of wasted tokens before the final answer.

Key differentiators:
- Zero external dependencies (no model call, no corpus, no API)
- Preserves all structured content unconditionally (code, JSON, URLs, paths, numbers)
- Structural integrity gate prevents over-compression
- Works on any text without training or adaptation

---

## Limitations

- Requires ≥ 5 sentences for meaningful compression; shorter payloads pass through unchanged
- Zipf proxy (word length) approximates rarity — semantic importance may diverge from lexical rarity in edge cases (e.g., short technical terms)
- Benford validation is most reliable on texts with 8+ sentences; very short compressed outputs may show elevated MAD without actual quality loss
- Not suitable for legally sensitive content where exact phrasing is contractually required
- Sentence splitter uses punctuation heuristics — unconventional formatting (e.g., bullet-heavy text without terminal punctuation) may reduce split quality

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

Numbers are preserved implicitly: they are never removed by the Zipf scorer (the scorer operates on word tokens, not digits).

---

## Project Structure

```
pith-skill/
├── src/
│   └── mcp_server_pith/     # MCP server package (pip-installable)
│       ├── __init__.py
│       ├── __main__.py
│       ├── compress.py      # Core compression logic
│       └── server.py        # MCP tool registration + JSON-RPC handler
├── scripts/
│   └── compress.py          # Standalone CLI (same logic, no install required)
├── tests/
│   ├── evals.json           # 7 eval test cases
│   ├── run_evals.py         # Eval runner
│   └── test_evals.py        # Pytest entry point
├── pyproject.toml           # Build config (hatchling + uv)
├── uv.lock                  # Locked dependency tree
├── pith.skill               # Claude Code skill manifest + instructions
├── SKILL.md                 # Skill documentation
└── README.md                # This file
```

---

## Testing

```bash
# Run eval suite directly
python3 scripts/compress.py --payload "$(cat tests/evals.json | python3 -c 'import json,sys; print(json.load(sys.stdin)[0][\"payload\"])')"

# Run via pytest
uv run pytest

# Run eval runner directly
python3 tests/run_evals.py
```

---

## Author

Created by **Albert** ([@VjAlbert](https://github.com/VjAlbert)) — developer, game theory enthusiast, and Benford's Law advocate. PITH emerged from the observation that multi-agent AI systems systematically deviate from the Nash equilibrium of communication, and that both Zipf's Law and Benford's Law are measurable signatures of that equilibrium.

---

## Related

- [video-analyzer](https://github.com/VjAlbert/video-analyzer) — bridges video files and Claude Projects
- [Anthropic MCP Servers](https://github.com/modelcontextprotocol/servers) — the reference MCP server repository (where the packaged version lives)
- [Anthropic Skills](https://github.com/anthropics/skills) — the official Claude Code skills repository

---

## License

MIT
