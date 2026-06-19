"""Extract XY_IDs from decrypted-lua Protocol files. Build closed set JSON."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from collections import OrderedDict

PROTOCOLS_DIR = Path(r"E:\claude\project\MahjongAI\MahjongAI\apk_research\decrypted-lua\app\Protocols")
OUT_JSON = Path(r"E:\claude\project\MahjongAI\MahjongAI\.trellis\tasks\06-19-n6-hidden-protocol-scan\research\xyid_closed_set.json")


def parse_protocol_file(path: Path) -> dict:
    text = path.read_text("utf-8", errors="replace")
    lines = text.split("\n")

    processid = None
    cmdt_expr: dict[str, str] = {}  # name -> raw expression
    locals_int: dict[str, int] = {}  # other helper ints (e.g. XY_ID_PLUS)
    # entries: list of { line, struct_name, raw_val (str) }
    entries: list[dict] = []

    cur_struct_name = None
    # Track lines like:  ProtocolName.StructName = {
    # so the most recent one is the struct an XY_ID belongs to.

    for i, raw in enumerate(lines, start=1):
        # processid
        m = re.search(r"\bprocessid\s*=\s*(\d+)", raw)
        if m:
            processid = int(m.group(1))

        # `local CMDT_FOO = <expr>` (skip commented lines)
        if re.match(r"^\s*--", raw):
            pass
        else:
            m = re.match(r"^\s*local\s+(CMDT_[A-Z0-9_]+)\s*=\s*(.+?)\s*$", raw)
            if m:
                _val = re.sub(r"\s*--.*$", "", m.group(2)).rstrip(";").strip()
                cmdt_expr[m.group(1)] = _val
            # Also catch `local XY_ID_PLUS = N`
            m = re.match(r"^\s*local\s+([A-Z][A-Z0-9_]*)\s*=\s*(\d+)\s*(--.*)?$", raw)
            if m and m.group(1).startswith("XY_ID_"):
                locals_int[m.group(1)] = int(m.group(2))

        # struct declaration:  Foo.Bar = {  (capture latest)
        m = re.match(r"^\s*([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*=\s*\{\s*$", raw)
        if m:
            cur_struct_name = f"{m.group(1)}.{m.group(2)}"
        # also accept multiline-ish:  Foo.Bar = {  ... already covered above

        # XY_ID assignment within table literal
        # e.g.  XY_ID = CMDT_FOO,
        # e.g.  XY_ID = 11014,
        # e.g.  XY_ID = 51 + XY_ID_PLUS,
        # e.g.  XY_ID = CMDT_FOO ,
        m = re.match(r"^\s*XY_ID\s*=\s*([^,]+?)\s*,?\s*(--.*)?$", raw)
        if m:
            val_str = m.group(1).strip()
            entries.append({
                "line": i,
                "struct": cur_struct_name or "?",
                "raw_val": val_str,
            })

    # Resolve CMDT_*
    resolved: dict[str, int] = {}
    # iterate until stable
    for _ in range(20):
        changed = False
        for name, expr in cmdt_expr.items():
            if name in resolved:
                continue
            v = try_eval(expr, resolved, locals_int)
            if v is not None:
                resolved[name] = v
                changed = True
        if not changed:
            break

    return {
        "processid": processid,
        "cmdt": resolved,
        "cmdt_unresolved": {k: v for k, v in cmdt_expr.items() if k not in resolved},
        "locals": locals_int,
        "entries": entries,
    }


def try_eval(expr: str, resolved: dict[str, int], locals_int: dict[str, int]) -> int | None:
    expr = expr.strip().rstrip(";").strip()
    # plain int
    if re.match(r"^-?\d+$", expr):
        return int(expr)
    # NAME
    if expr in resolved:
        return resolved[expr]
    if expr in locals_int:
        return locals_int[expr]
    # NAME + NUM
    m = re.match(r"^([A-Z_][A-Z0-9_]*)\s*\+\s*(\d+)$", expr)
    if m:
        nm, add = m.group(1), int(m.group(2))
        if nm in resolved:
            return resolved[nm] + add
        if nm in locals_int:
            return locals_int[nm] + add
    # NUM + NAME
    m = re.match(r"^(\d+)\s*\+\s*([A-Z_][A-Z0-9_]*)$", expr)
    if m:
        add, nm = int(m.group(1)), m.group(2)
        if nm in resolved:
            return resolved[nm] + add
        if nm in locals_int:
            return locals_int[nm] + add
    return None


def main():
    closed: dict[int, list[dict]] = {}
    file_summaries = OrderedDict()

    for f in sorted(PROTOCOLS_DIR.glob("*.lua")):
        info = parse_protocol_file(f)
        proto_name = f.stem  # e.g. IMProtocol
        processid = info["processid"]
        file_summaries[proto_name] = {
            "file": f.name,
            "processid": processid,
            "cmdt_count": len(info["cmdt"]),
            "cmdt_unresolved": list(info["cmdt_unresolved"].keys()),
            "entries": [],
        }

        for ent in info["entries"]:
            val = try_eval(ent["raw_val"], info["cmdt"], info["locals"])
            if val is None:
                # Unable to resolve
                file_summaries[proto_name]["entries"].append({
                    **ent,
                    "value": None,
                    "note": "UNRESOLVED",
                })
                continue

            # find name from CMDT (best-effort)
            cmdt_name = None
            for k, v in info["cmdt"].items():
                if v == val and ent["raw_val"].endswith(k):
                    cmdt_name = k
                    break
            if cmdt_name is None:
                # raw_val itself is the CMDT name
                rv = ent["raw_val"]
                if rv.startswith("CMDT_") and rv in info["cmdt"]:
                    cmdt_name = rv

            direction = "?"
            tag_src = (cmdt_name or ent["raw_val"]).upper() + "_" + ent["struct"].upper()
            if "REQ" in tag_src or "REQUEST" in tag_src:
                direction = "req"
            elif "RESP" in tag_src or "RESPONSE" in tag_src:
                direction = "resp"
            elif "NOTIFY" in tag_src or "PUSH" in tag_src or "REPORT" in tag_src or "EVENT" in tag_src:
                direction = "notify"

            entry = {
                "msg_type": val,
                "name": cmdt_name or ent["struct"],
                "struct": ent["struct"],
                "protocol": proto_name,
                "processid": processid,
                "direction": direction,
                "source_file": f"apk_research/decrypted-lua/app/Protocols/{f.name}",
                "source_line": ent["line"],
                "raw_expr": ent["raw_val"],
            }
            file_summaries[proto_name]["entries"].append(entry)
            closed.setdefault(val, []).append(entry)

    # Build JSON output: msg_type -> list of definitions (some IDs are shared across protocols)
    out = OrderedDict()
    for k in sorted(closed.keys()):
        out[str(k)] = closed[k]

    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path = OUT_JSON.with_name("_extract_summary.json")
    summary_path.write_text(json.dumps(file_summaries, indent=2, ensure_ascii=False), encoding="utf-8")

    # Print stats to stdout
    total_unique = len(out)
    total_defs = sum(len(v) for v in out.values())
    in_range = sum(1 for k in out if 1 <= int(k) <= 5000)
    print(f"Protocols processed: {len(file_summaries)}")
    print(f"Unique msg_type values: {total_unique}")
    print(f"Total XY_ID definitions (with collisions): {total_defs}")
    print(f"Unique msg_types in [1, 5000]: {in_range}")
    print(f"Unresolved entries:")
    for proto, info in file_summaries.items():
        unresolved = [e for e in info["entries"] if e.get("value") is None and e.get("note") == "UNRESOLVED"]
        if unresolved:
            print(f"  {proto}: {len(unresolved)} unresolved")
            for u in unresolved[:5]:
                print(f"    line {u['line']}: struct={u['struct']} raw={u['raw_val']!r}")


if __name__ == "__main__":
    main()
