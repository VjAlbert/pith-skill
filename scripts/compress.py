#!/usr/bin/env python3
"""
PITH — Skill Compatibility Wrapper
Redirects invocation to the unified package implementation inside src/
"""

import os
import sys

# Risolve il percorso assoluto della cartella 'src' rispetto alla posizione di questo script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "src"))

# Inietta il percorso in cima a sys.path per prevenire il ModuleNotFoundError
if SRC_PATH not in sys.path:
    sys.path.insert(0, SRC_PATH)

try:
    from mcp_server_pith.compress import main
except ModuleNotFoundError as e:
    print(f"Error: PITH package core not found in {SRC_PATH}.", file=sys.stderr)
    print(f"Details: {e}", file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    # La riconfigurazione degli stream viene gestita nativamente all'interno di main()
    main()
