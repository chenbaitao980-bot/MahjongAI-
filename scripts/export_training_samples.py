from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.replay_stable_reader import _iter_messages
from stable.mapping import MappingStore
from stable.training_data import export_training_samples


def export_file(
    input_path: Path,
    output_path: Path,
    *,
    port: int = 7777,
    local_player: int = 1,
    mapping_path: str | None = None,
    include_blocked: bool = True,
    record_enabled: bool = True,
    train_enabled: bool = False,
) -> int:
    store = MappingStore(path=mapping_path)
    samples, stats = export_training_samples(
        _iter_messages(input_path, port),
        mapping_store=store,
        local_player=local_player,
        player_count=2,
        source_path=str(input_path),
        include_blocked=include_blocked,
        record_enabled=record_enabled,
        train_enabled=train_enabled,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False, sort_keys=True) + "\n")

    print(
        "exported "
        f"samples={stats.samples} trainable={stats.trainable} "
        f"blocked={stats.blocked} messages={stats.messages} -> {output_path}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export stable-reader replay logs into training sample JSONL."
    )
    parser.add_argument("input", help="events_*.jsonl or raw_*.pcap")
    parser.add_argument("output", help="output samples_*.jsonl")
    parser.add_argument("--port", type=int, default=7777)
    parser.add_argument("--local-player", type=int, default=1)
    parser.add_argument("--mapping-path", default=None)
    parser.add_argument(
        "--drop-blocked",
        action="store_true",
        help="Only write trainable samples; blocked decisions are counted but omitted.",
    )
    parser.add_argument(
        "--record-disabled",
        action="store_true",
        help="Replay input without writing training samples.",
    )
    parser.add_argument(
        "--train-enabled",
        action="store_true",
        help="Mark eligible samples as allowed into the training pool.",
    )
    args = parser.parse_args(argv)
    return export_file(
        Path(args.input),
        Path(args.output),
        port=args.port,
        local_player=args.local_player,
        mapping_path=args.mapping_path,
        include_blocked=not args.drop_blocked,
        record_enabled=not args.record_disabled,
        train_enabled=bool(args.train_enabled),
    )


if __name__ == "__main__":
    raise SystemExit(main())
