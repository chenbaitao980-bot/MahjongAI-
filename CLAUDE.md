# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **mahjong-learning** (6544 symbols, 12198 relationships, 300 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "master"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/mahjong-learning/context` | Codebase overview, check index freshness |
| `gitnexus://repo/mahjong-learning/clusters` | All functional areas |
| `gitnexus://repo/mahjong-learning/processes` | All execution flows |
| `gitnexus://repo/mahjong-learning/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

---

## Commands

### Run the app
```bash
python main.py
```
Config is loaded from `data/config/settings.yaml` (user-writable) with fallback to `config/settings.yaml` (bundled).

### Install dependencies
```bash
pip install -r requirements.txt
```
Requires Npcap (Windows) installed separately for packet-capture mode.

### Run tests
```bash
# All tests
python -m pytest tests/

# Single test file
python -m pytest tests/test_stable_reader.py -v

# Single test case
python -m pytest tests/test_stable_reader.py::ClassName::test_method -v
```

### Build distributable (PyInstaller)
```bash
build.bat
# or directly:
pyinstaller mahjong_ai.spec
```
Output goes to `dist/`.

### Debug utilities
```bash
python debug_recognition.py   # replay a saved session through the vision pipeline
python diagnose_region.py     # inspect a specific screen region
```

---

## Architecture

The app has **two independent capture modes** that share the same AI analysis back-end:

### Mode 1 — Vision Mode (screenshot-based)
```
Screen capture (mss)
  → vision/pipeline.py (RecognitionPipeline)
      → vision/hand_region_module.py  (locate hand tiles)
      → vision/hog_classifier.py      (HOG/SVM tile classifier)
      → vision/recognizer.py          (full-board recognizer)
  → battle/service.py (BattleService)
      → battle/state.py (BattleState + BattleAdvice)
      → game/evaluator.py → game/{shanten,ukeire,danger,strategy}.py
      → game/llm_advisor.py → game/llm_client.py  (DeepSeek / Qwen)
  → ui/battle_panel.py  (PyQt6 panel)
```

### Mode 2 — Stable Mode (Npcap packet sniffing, the "stable" version)
```
NpcapCapture / tcpdump (port 7777)
  → stable/protocol.py (MJProtocol)   — TCP stream reassembly + frame decode
  → stable/tracker.py  (PacketStateTracker) — rebuild BattleState from events
  → stable/mapping.py  (MappingStore) — byte→tile_id, YAML-persisted
  → game/stable_hard_analysis.py      — local shanten/ukeire analysis
  → ui/stable_battle_panel.py         — dedicated Stable mode UI
  → ui/stable_capture_controller.py   — StableCaptureThread (QThread)
```

Stable mode is the **primary/reliable path** for live games. Vision mode is used when packet capture is unavailable (e.g. mobile via screen mirror).

### Key data types

| Type | File | Purpose |
|------|------|---------|
| `BattleState` | `battle/state.py` | Authoritative game state: hand, discards, melds, phase, remaining tiles |
| `BattleAdvice` | `battle/state.py` | AI output: recommended discard, candidates, strategy mode |
| `PacketStateTracker` | `stable/tracker.py` | Stateful converter: `ProtocolMessage` events → `BattleState` |
| `ProtocolMessage` | `stable/protocol.py` | Decoded single game event (draw/discard/meld/win/baida) |
| `MappingStore` | `stable/mapping.py` | Persistent byte→tile_id mapping, context-aware (linear/nibble/stable/instance) |

### Tile encoding

Tiles are represented as strings like `"3m"` (3-man/万), `"5p"` (5-pin/筒), `"7s"` (7-sou/条), `"1z"`–`"7z"` (honors). Integer IDs (0–33) are used in `game/` math modules. `game/tiles.py` has the conversion helpers.

The game's wire protocol uses **instance encoding** with tile order 条→万→筒→字 (NOT the standard万→筒→条→字 order). This is handled in `stable/mapping.py` via `_GAME_INSTANCE_TILE_IDS`.

### Configuration

`config/settings.yaml` — all runtime settings. At startup, `data/config/settings.yaml` (next to the exe) is preferred over the bundled one, allowing user edits to survive updates.

Key sections: `deepseek` (API key/model), `vision` (provider + keys for Qwen/GLM/Volc), `layout` (screen region ratios), `battle` (voice, AI toggles), `shortcut_keys`.

### Session persistence

`game/session.py` (`GameSession`) writes per-game data to SQLite + JSONL under `data/sessions/`. Each round logs: raw frames, recognition events, analysis candidates, and final advice. `backfill_session_db.py` retrofits older JSONL-only sessions into SQLite.

### Analysis pipeline (both modes)

`BattleState.to_payload()` serializes current game state → dict passed to `game/evaluator.py` for local analysis (shanten/ukeire/danger/strategy) → dict injected into LLM prompt → `game/llm_advisor.py` calls DeepSeek or falls back to `get_program_advice()`.

Monte Carlo simulation (`game/mc_*.py`) is skipped when shanten ≥ 2 and capped at 10 iterations at shanten = 1 for performance.
