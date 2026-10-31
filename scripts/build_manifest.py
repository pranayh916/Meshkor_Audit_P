"""Build the current raw-input inventory without overwriting the legacy manifest."""
from __future__ import annotations

import csv
import hashlib
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw_essential_inputs"
LEGACY = ROOT / "data" / "manifest.csv"
MANIFEST = ROOT / "data" / "manifests" / "file_inventory.csv"
FIELDS = ["source", "subfolder", "file_name", "relative_path", "size_bytes", "format",
          "source_period", "modified", "sha256", "source_url", "notes",
          "inventory_status", "processing_status"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_rows(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = {}
        for row in csv.DictReader(f):
            relative = row.get("relative_path") or ""
            if not relative and row.get("source") and row.get("file_name"):
                relative = (Path("data/raw_essential_inputs") / row["source"] /
                            row.get("subfolder", "") / row["file_name"]).as_posix()
                row["relative_path"] = relative
            rows[relative] = row
        return rows


def main() -> None:
    old = load_rows(LEGACY)
    previous = load_rows(MANIFEST)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in sorted(RAW.rglob("*")) if RAW.is_dir() else []:
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        seen.add(relative)
        rel_raw = path.relative_to(RAW)
        source = rel_raw.parts[0]
        subfolder = Path(*rel_raw.parts[1:-1]).as_posix() if len(rel_raw.parts) > 1 else ""
        size = path.stat().st_size
        digest = sha256(path)
        prior = previous.get(relative, {})
        legacy_key = (source, subfolder, path.name)
        legacy_row = next((r for r in old.values() if
                           (r.get("source"), r.get("subfolder", ""), r.get("file_name")) == legacy_key), {})
        is_sidecar = path.name.endswith(".sha256")
        incomplete = path.name.endswith(".part")
        status = "new" if not prior else ("unchanged" if prior.get("sha256") == digest else "changed")
        if is_sidecar:
            processing = "sidecar"
        elif incomplete:
            processing = "incomplete"
        else:
            processing = prior.get("processing_status") or "pending"
        parts = [p for p in rel_raw.parts if re.search(r"20\d{2}(?:[-_]Q?\d)?", p, re.I)]
        rows.append({
            "source": source, "subfolder": subfolder, "file_name": path.name,
            "relative_path": relative, "size_bytes": str(size), "format": path.suffix.lower().lstrip("."),
            "source_period": parts[0] if parts else "",
            "modified": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
            "sha256": digest, "source_url": legacy_row.get("source_url", ""),
            "notes": legacy_row.get("notes", ""), "inventory_status": status,
            "processing_status": processing,
        })
    # Keep previously inventoried missing inputs and legacy manual rows visible.
    for relative, prior in previous.items():
        if relative and relative not in seen:
            rows.append({**{field: prior.get(field, "") for field in FIELDS},
                         "inventory_status": "removed"})
    for legacy_row in old.values():
        if legacy_row.get("notes") and not any(
                r.get("source") == legacy_row.get("source") and
                r.get("subfolder", "") == legacy_row.get("subfolder", "") and
                r.get("file_name") == legacy_row.get("file_name") for r in rows):
            rows.append({**{field: "" for field in FIELDS}, **legacy_row,
                         "inventory_status": "manual", "processing_status": "not_applicable"})

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", dir=MANIFEST.parent,
                                     delete=False) as f:
        temp = Path(f.name)
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temp, MANIFEST)
    print(f"Wrote {len(rows)} inventory rows to {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
