#!/usr/bin/env python3
"""
PITH — Inter-Agent Payload Compressor
Zipf word-density scoring + Benford structural validation

Usage:
    echo "<payload>" | python3 compress.py
    python3 compress.py --payload "<text>" --ratio 0.6
    python3 compress.py --payload "<text>" --json
"""

import sys, re, json, math, argparse, heapq
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Configuration ────────────────────────────────────────────────────
DEFAULT_RATIO      = 0.60   # Keep top 60% of sentences by density
BENFORD_TOLERANCE  = 2.0    # Max MAD multiplier before Benford gate triggers
MIN_SENTENCES      = 5      # Pass through if fewer sentences than this
DENSE_WORD_CHARS   = 7      # Words >= N chars = rare = high information proxy
MAX_RETRIES        = 3      # Benford gate retry attempts

BENFORD = {d: math.log10(1 + 1/d) * 100 for d in range(1, 10)}

STOPWORDS = set("""
a about above after again against all am an and any are as at be because been before
being below between both but by can cannot could did do does doing down during each few
for from further get got had has have having he her here him his how i if in into is it
its itself let me more most my myself no nor not of off on once only or other our out
over own same she should so some such than that the their them then there these they this
those through to too under until up very was we were what when where which while who
whose why will with would you your yours
""".split())

# Long words that are common/procedural — don't count as dense even if >= DENSE_WORD_CHARS.
# These frequently appear in filler sentences ("no errors encountered", "completed successfully").
COMMON_LONG_WORDS = {
    "encountered", "completed", "successfully", "produced", "happened",
    "computation", "discussed", "following", "together", "available",
    "including", "currently", "adequate", "correctly", "proceeded",
    "retrieved", "processed", "sequentially", "executed",
}

# Sentence patterns that indicate filler / hedging — score is multiplied down.
FILLER_PATTERNS = re.compile(
    r"^(i believe\b|i think\b|i found\b|i searched\b|i need to\b|i am\b"
    r"|the search (was|is|has been|returned|completed)\b"
    r"|no (errors?|issues?|problems?|warnings?)\b)",
    re.IGNORECASE,
)

# ── Pre-compiled regexes (module-level: compiled once, reused every call) ─
_STRIP_NON_ALPHA = re.compile(r'[^a-zA-Z\s]')
_SPLIT_SENT_RE   = re.compile(r'(?<=[.!?])\s+(?=[A-Z-￿])')

# ── Content Preservation ─────────────────────────────────────────────
# These patterns are extracted BEFORE compression and restored AFTER.
# Code, JSON, URLs, paths, numbers are never touched.

PRESERVE_PATTERNS = [
    ("code_block",  re.compile(r"```[\s\S]*?```")),
    ("inline_code", re.compile(r"`[^`\n]+`")),
    ("json_obj",    re.compile(r"\{[^{}]{10,}\}")),
    ("json_arr",    re.compile(r"\[[^\[\]]{10,}\]")),
    ("url",         re.compile(r"https?://\S+")),
    ("filepath",    re.compile(r"(?:/[\w.\-_]+){2,}")),
    ("xml_tag",     re.compile(r"<[a-zA-Z][^>]*>[\s\S]*?</[a-zA-Z]+>")),
]

def extract_preserved(text):
    preserved = {}
    idx = [0]

    def replacer(m, kind):
        key = f"\x00PITH_{kind}_{idx[0]}\x00"
        preserved[key] = m.group(0)
        idx[0] += 1
        return key

    for kind, pattern in PRESERVE_PATTERNS:
        text = pattern.sub(lambda m, k=kind: replacer(m, k), text)

    return text, preserved

def restore_preserved(text, preserved):
    for key, value in preserved.items():
        text = text.replace(key, value)
    return text

# ── Sentence Splitting ───────────────────────────────────────────────

def split_sentences(text):
    # Split on sentence-ending punctuation followed by space + capital
    raw = _SPLIT_SENT_RE.split(text.strip())
    # Also split on newline-separated items (bullet points, numbered lists)
    result = []
    for part in raw:
        lines = part.split('\n')
        for line in lines:
            line = line.strip()
            if len(line.split()) >= 2:
                result.append(line)
    return result

# ── Zipf Density Scoring ─────────────────────────────────────────────

def zipf_density(sentence):
    """
    Score a sentence's information density using word length as Zipf proxy.

    Rare words (specific, technical, uncommon) are systematically longer.
    Words >= DENSE_WORD_CHARS characters = high information content.

    Returns float 0.0–1.0. Higher = more information-dense.
    """
    words = _STRIP_NON_ALPHA.sub(' ', sentence.lower()).split()
    content = [w for w in words if w not in STOPWORDS and len(w) > 2]

    if not content:
        return 0.0

    # Single pass: accumulate dense count and total length together
    n_dense = 0
    total_len = 0
    for w in content:
        wl = len(w)
        total_len += wl
        if wl >= DENSE_WORD_CHARS and w not in COMMON_LONG_WORDS:
            n_dense += 1
    mean_len = total_len / len(content)

    # Weighted combination: fraction dense (60%) + normalized mean length (40%)
    score = (n_dense / len(content)) * 0.6 + min(mean_len / 12.0, 1.0) * 0.4

    # Penalize first-person hedging and procedural filler sentences
    if FILLER_PATTERNS.match(sentence.strip()):
        score *= 0.25

    return round(min(score, 1.0), 4)

# ── Benford Validation ───────────────────────────────────────────────

def benford_mad(sentences):
    """
    Mean Absolute Deviation of sentence-length first-digit distribution
    from Benford's Law expected distribution.

    Natural text: MAD < 6%
    AI/over-compressed text: MAD > 7%
    """
    lengths = []
    for s in sentences:
        parts = s.split()
        if parts:
            lengths.append(len(parts))
    if len(lengths) < 5:
        return 0.0

    first_digits = [int(str(max(l, 1))[0]) for l in lengths]
    dist = Counter(first_digits)
    total = len(first_digits)
    return round(
        sum(abs(dist.get(d, 0) / total * 100 - BENFORD[d]) for d in range(1, 10)) / 9,
        2
    )

# ── Core Compression ─────────────────────────────────────────────────

def compress(text, target_ratio=DEFAULT_RATIO):
    """
    Main PITH compression pipeline.

    Returns:
        compressed_text (str): The compressed payload
        meta (dict): Compression metadata
    """
    original_tokens = len(text.split())
    passthrough_meta = {
        "action": "passthrough",
        "original_tokens": original_tokens,
        "compressed_tokens": original_tokens,
        "ratio": 1.0,
        "saved_pct": 0.0,
        "benford_ok": True,
    }

    # ── Step 1: Extract preserved blocks ────────────────────────────
    working, preserved = extract_preserved(text)
    n_preserved = len(preserved)

    # ── Step 2: Split into sentences ────────────────────────────────
    sentences = split_sentences(working)

    # ── Step 3: Passthrough for short payloads ──────────────────────
    if len(sentences) < MIN_SENTENCES:
        passthrough_meta["reason"] = f"only {len(sentences)} sentences (< {MIN_SENTENCES})"
        passthrough_meta["benford_mad"] = benford_mad(sentences)
        passthrough_meta["preserved_blocks"] = n_preserved
        return text, passthrough_meta

    # ── Step 4: Score each sentence ──────────────────────────────────
    scored = [(i, s, zipf_density(s)) for i, s in enumerate(sentences)]
    original_mad = benford_mad(sentences)
    keep_n = max(2, round(len(sentences) * target_ratio))

    # ── Step 5: Benford gate loop ────────────────────────────────────
    kept_sentences = sentences  # fallback
    compressed_mad = original_mad
    candidate: list[str] = []
    candidate_mad: float = original_mad

    for attempt in range(MAX_RETRIES):
        # heapq.nlargest is O(n log k) vs sorted O(n log n) — faster when k << n
        top = heapq.nlargest(keep_n, scored, key=lambda x: x[2])
        # Restore original sentence order
        kept_indices = sorted(x[0] for x in top)
        candidate = [sentences[i] for i in kept_indices]
        candidate_mad = benford_mad(candidate)

        if original_mad > 0 and candidate_mad > original_mad * BENFORD_TOLERANCE:
            # Over-compressed — add 2 more sentences and retry
            keep_n = min(len(sentences), keep_n + 2)
        else:
            kept_sentences = candidate
            compressed_mad = candidate_mad
            break
    else:
        # All retries exhausted — use last candidate
        kept_sentences = candidate
        compressed_mad = candidate_mad

    # ── Step 6: Reassemble ────────────────────────────────────────────
    compressed_working = " ".join(kept_sentences)
    compressed_text = restore_preserved(compressed_working, preserved)

    # Ensure critical preserved blocks not lost (e.g. code at end)
    for key, value in preserved.items():
        if key not in compressed_working:
            compressed_text += f"\n{value}"

    compressed_tokens = len(compressed_text.split())
    ratio = round(compressed_tokens / original_tokens, 3) if original_tokens > 0 else 1.0

    meta = {
        "action": "compressed",
        "original_tokens": original_tokens,
        "compressed_tokens": compressed_tokens,
        "ratio": ratio,
        "saved_pct": round((1 - ratio) * 100, 1),
        "sentences_original": len(sentences),
        "sentences_kept": len(kept_sentences),
        "original_benford_mad": original_mad,
        "compressed_benford_mad": compressed_mad,
        "benford_ok": compressed_mad <= original_mad * BENFORD_TOLERANCE or original_mad == 0,
        "preserved_blocks": n_preserved,
    }

    return compressed_text, meta

# ── CLI ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="PITH — Inter-Agent Payload Compressor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  echo "Your verbose agent output..." | python3 compress.py
  python3 compress.py --payload "Long text..." --ratio 0.5
  python3 compress.py --payload "Long text..." --json
        """
    )
    parser.add_argument("--payload", type=str,
                        help="Text to compress (alternative to stdin)")
    parser.add_argument("--ratio", type=float, default=DEFAULT_RATIO,
                        help=f"Target sentence keep ratio 0.0–1.0 (default: {DEFAULT_RATIO})")
    parser.add_argument("--json", action="store_true",
                        help="Output full JSON with compressed text + metadata")
    args = parser.parse_args()

    # Read input
    if args.payload:
        text = args.payload
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        parser.print_help()
        sys.exit(1)

    text = text.strip()
    if not text:
        print('{"error": "empty input"}' if args.json else "Error: empty input",
              file=sys.stderr)
        sys.exit(1)

    # Validate ratio
    if not 0.1 <= args.ratio <= 1.0:
        print("Error: --ratio must be between 0.1 and 1.0", file=sys.stderr)
        sys.exit(1)

    # Run compression
    compressed, meta = compress(text, target_ratio=args.ratio)

    if args.json:
        print(json.dumps({"compressed": compressed, "meta": meta}, indent=2))
    else:
        benford_icon = "✓" if meta.get("benford_ok", True) else "⚠"
        action = meta.get("action", "compressed")
        saved = meta.get("saved_pct", 0)
        b_mad = meta.get("compressed_benford_mad", meta.get("benford_mad", 0))
        header = f"[PITH | {benford_icon} | -{saved:.0f}% tokens | benford:{b_mad:.1f}% | {action}]"
        print(header)
        print(compressed)

if __name__ == "__main__":
    main()
