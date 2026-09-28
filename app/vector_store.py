from __future__ import annotations

from pathlib import Path
from typing import Any


def sync_records(root: Path, config: dict[str, Any], records: list[dict[str, Any]]) -> None:
    vectors = [record for record in records if record.get("embedding")]
    if not vectors:
        return
    import lancedb

    database_dir = root / config["index"].get("data_dir", "data") / "lancedb"
    database_dir.mkdir(parents=True, exist_ok=True)
    database = lancedb.connect(str(database_dir))
    rows = [
        {
            "path": record["path"],
            "name": record["name"],
            "extension": record["extension"],
            "source_id": record["source_id"],
            "size": record["size"],
            "mtime": record["mtime"],
            "preview": record.get("preview", ""),
            "indexed_at": record.get("indexed_at", ""),
            "embedding_status": record.get("embedding_status", ""),
            "vector": record["embedding"],
        }
        for record in vectors
    ]
    if "files" in database.table_names():
        database.drop_table("files")
    database.create_table("files", data=rows)


def search(root: Path, config: dict[str, Any], query_vector: list[float], limit: int) -> list[dict[str, Any]]:
    import lancedb

    database_dir = root / config["index"].get("data_dir", "data") / "lancedb"
    if not database_dir.exists():
        return []
    database = lancedb.connect(str(database_dir))
    if "files" not in database.table_names():
        return []
    return database.open_table("files").search(query_vector).distance_type("cosine").limit(limit).to_list()
