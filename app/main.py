from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import queue
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from embedding import EmbeddingEngine


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "config.json"
WEB_ROOT = ROOT / "web"
LOG_PATH = ROOT / "logs" / "service.log"
DEFAULT_CONFIG = {
    "host": "0.0.0.0",
    "port": 8876,
    "model": {
        "name": "WeMM-Embedding-2B",
        "path": "",
        "device": "cuda",
        "dtype": "bfloat16",
        "dimension": 512,
        "enabled": False,
    },
    "index": {
        "data_dir": "data",
        "cache_dir": "cache",
        "database_file": "data/index.jsonl",
        "metadata_file": "data/metadata.json",
        "max_file_size_mb": 250,
        "extensions": [
            ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".xml",
            ".html", ".htm", ".css", ".scss", ".less", ".js", ".mjs", ".cjs", ".ts",
            ".tsx", ".jsx", ".vue", ".svelte", ".py", ".java", ".kt", ".go", ".rs",
            ".c", ".h", ".cpp", ".hpp", ".cs", ".php", ".rb", ".swift", ".sh", ".bat",
            ".cmd", ".ps1", ".sql", ".tex", ".yaml", ".yml", ".toml", ".ini", ".cfg",
            ".conf", ".env", ".log", ".svg", ".rtf", ".pdf", ".docx", ".xlsx", ".pptx",
            ".odt", ".ods", ".odp", ".epub", ".jpg", ".jpeg", ".png", ".webp", ".bmp",
            ".gif", ".tif", ".tiff", ".ico", ".avif", ".zip", ".rar", ".7z", ".mp4",
            ".mkv", ".avi", ".mov", ".mp3", ".wav", ".flac", ".psd", ".ai", ".iso",
        ],
    },
    "sources": [],
    "backup": {"enabled": False, "path": ""},
}

STATE_LOCK = threading.RLock()
JOB_LOCK = threading.Lock()
JOB: dict[str, Any] = {
    "running": False,
    "mode": "",
    "started_at": "",
    "finished_at": "",
    "scanned": 0,
    "indexed": 0,
    "skipped": 0,
    "failed": 0,
    "total": 0,
    "current": 0,
    "percent": 0.0,
    "current_file": "",
    "phase": "idle",
    "rate": 0.0,
    "eta_seconds": None,
    "failures": [],
    "message": "",
}
ENGINE: EmbeddingEngine | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{utc_now()}] {message}"
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def load_config() -> dict[str, Any]:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, json.JSONDecodeError):
        config = json.loads(json.dumps(DEFAULT_CONFIG))
    return config


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_PATH.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
    temp.replace(CONFIG_PATH)


def resolve_project_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def db_path(config: dict[str, Any]) -> Path:
    path = resolve_project_path(config["index"]["database_file"])
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def metadata_path(config: dict[str, Any]) -> Path:
    path = resolve_project_path(config["index"]["metadata_file"])
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def read_records(config: dict[str, Any]) -> list[dict[str, Any]]:
    path = db_path(config)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def write_records(config: dict[str, Any], records: list[dict[str, Any]]) -> None:
    path = db_path(config)
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    temp.replace(path)
    metadata_path(config).write_text(
        json.dumps({"updated_at": utc_now(), "records": len(records)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        from vector_store import sync_records

        sync_records(ROOT, config, records)
    except Exception as exc:
        log(f"vector store sync failed: {exc}")


def quick_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        digest.update(handle.read(1024 * 1024))
    return digest.hexdigest()[:16]


IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".ico", ".avif"
}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".html", ".htm",
    ".css", ".scss", ".less", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte",
    ".py", ".java", ".kt", ".go", ".rs", ".c", ".h", ".cpp", ".hpp", ".cs", ".php", ".rb",
    ".swift", ".sh", ".bat", ".cmd", ".ps1", ".sql", ".tex", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".conf", ".env", ".log", ".svg"
}
OFFICE_XML_EXTENSIONS = {".pptx", ".odt", ".ods", ".odp", ".epub"}


def extract_zip_xml_preview(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        suffix = path.suffix.lower()
        if suffix == ".pptx":
            candidates = sorted(name for name in names if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
        elif suffix == ".epub":
            candidates = sorted(name for name in names if name.lower().endswith((".xhtml", ".html", ".htm")))
        else:
            candidates = [name for name in names if name.endswith("content.xml")]
        values: list[str] = []
        for name in candidates[:80]:
            try:
                root = ET.fromstring(archive.read(name))
            except (KeyError, ET.ParseError):
                continue
            for node in root.iter():
                if node.text and (node.tag.endswith("}t") or node.tag.endswith("}p") or node.tag.endswith("}span")):
                    values.append(node.text)
        return re.sub(r"\s+", " ", " ".join(values))[:1200]


def extract_preview(path: Path) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix in TEXT_EXTENSIONS:
            return re.sub(r"\s+", " ", path.read_text(encoding="utf-8", errors="ignore"))[:1200]
        if suffix == ".rtf":
            raw = path.read_text(encoding="latin-1", errors="ignore")
            text = re.sub(r"\\[a-z]+\d*\s?", " ", raw, flags=re.IGNORECASE)
            return re.sub(r"[{}]", "", text).strip()[:1200]
        if suffix == ".pdf":
            from pypdf import PdfReader

            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages[:10])
            return re.sub(r"\s+", " ", text)[:1200]
        if suffix == ".docx":
            from docx import Document

            text = "\n".join(paragraph.text for paragraph in Document(str(path)).paragraphs)
            return re.sub(r"\s+", " ", text)[:1200]
        if suffix == ".xlsx":
            from openpyxl import load_workbook

            workbook = load_workbook(str(path), read_only=True, data_only=True)
            values = []
            for sheet in workbook.worksheets[:5]:
                for row in sheet.iter_rows(max_row=100, values_only=True):
                    values.extend(str(value) for value in row if value is not None)
            return re.sub(r"\s+", " ", " ".join(values))[:1200]
        if suffix in OFFICE_XML_EXTENSIONS:
            return extract_zip_xml_preview(path)
    except OSError:
        return ""
    except Exception as exc:
        log(f"preview failed {path}: {exc}")
        return ""
    return ""


def prepare_image_for_model(path: Path, config: dict[str, Any]) -> str:
    from PIL import Image, ImageOps

    max_side = int(config["index"].get("max_image_side", 1024))
    cache_root = resolve_project_path(config["index"].get("cache_dir", "cache")) / "model-images"
    cache_root.mkdir(parents=True, exist_ok=True)
    stat = path.stat()
    cache_name = hashlib.sha1(f"{path}|{stat.st_size}|{stat.st_mtime_ns}|{max_side}".encode("utf-8", errors="ignore")).hexdigest()
    output = cache_root / f"{cache_name}.jpg"
    if output.exists():
        return str(output)
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        image.save(output, "JPEG", quality=92, optimize=True)
    return str(output)


def embedding_input(path: Path, preview: str, config: dict[str, Any]) -> str | dict[str, str] | None:
    if path.suffix.lower() in IMAGE_EXTENSIONS:
        return {"image": prepare_image_for_model(path, config)}
    if preview:
        return preview
    return None


def file_record(
    path: Path,
    source: dict[str, Any],
    engine: EmbeddingEngine | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    stat = path.stat()
    preview = extract_preview(path)
    vector = None
    embedding_status = "pending_model"
    input_value = embedding_input(path, preview, config)
    if engine and engine.enabled and input_value is not None:
        vector = engine.encode(input_value)
        embedding_status = "ready"
    return {
        "path": str(path),
        "name": path.name,
        "extension": path.suffix.lower(),
        "source_id": source["id"],
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "hash": quick_hash(path),
        "preview": preview,
        "indexed_at": utc_now(),
        "embedding": vector,
        "embedding_status": embedding_status,
    }


def canonical_path(path_text: str) -> Path:
    return Path(path_text).expanduser().resolve(strict=False)


def path_is_under(path: Path, root: Path) -> bool:
    try:
        path_value = os.path.normcase(str(path))
        root_value = os.path.normcase(str(root))
        return os.path.commonpath([path_value, root_value]) == root_value
    except ValueError:
        return False


def is_allowed_file(path: Path, config: dict[str, Any]) -> bool:
    path_value = os.path.normcase(str(path))
    for record in read_records(config):
        try:
            if os.path.normcase(str(canonical_path(record.get("path", "")))) == path_value:
                return True
        except (OSError, ValueError):
            continue
    for source in config.get("sources", []):
        try:
            if source.get("enabled", True) and path_is_under(path, canonical_path(source["path"])):
                return True
        except (KeyError, OSError, ValueError):
            continue
    return False


def record_is_in_enabled_sources(record: dict[str, Any], config: dict[str, Any]) -> bool:
    try:
        path = canonical_path(str(record.get("path", "")))
    except (OSError, ValueError):
        return False
    for source in config.get("sources", []):
        if source.get("enabled", True) and path_is_under(path, canonical_path(str(source.get("path", "")))):
            return True
    return False


def requested_file(path_text: str, config: dict[str, Any]) -> Path:
    if not path_text.strip():
        raise ValueError("缺少文件路径")
    path = canonical_path(path_text)
    if not path.is_file():
        raise FileNotFoundError("文件不存在或不可访问")
    if not is_allowed_file(path, config):
        raise PermissionError("只能访问已索引文件或当前检索文件夹中的文件")
    return path


def preview_payload(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    stat = path.stat()
    base = {
        "name": path.name,
        "path": str(path),
        "extension": suffix,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
    }
    if suffix in IMAGE_EXTENSIONS:
        return {**base, "kind": "image", "url": f"/api/file?path={urllib.parse.quote(str(path))}"}
    if suffix == ".pdf":
        return {**base, "kind": "pdf", "url": f"/api/file?path={urllib.parse.quote(str(path))}"}
    if suffix in TEXT_EXTENSIONS:
        text = path.read_text(encoding="utf-8", errors="ignore")
        limit = 20000
        return {**base, "kind": "text", "content": text[:limit], "truncated": len(text) > limit}
    if suffix == ".rtf":
        return {**base, "kind": "text", "content": extract_preview(path), "truncated": False, "extracted": True}
    if suffix in {".docx", ".xlsx", *OFFICE_XML_EXTENSIONS}:
        return {**base, "kind": "text", "content": extract_preview(path), "truncated": False, "extracted": True}
    return {**base, "kind": "metadata", "content": "", "message": "此文件类型暂不支持网页预览，请打开所在文件夹查看。"}


def update_job(**changes: Any) -> None:
    with STATE_LOCK:
        JOB.update(changes)
        total = int(JOB.get("total") or 0)
        current = int(JOB.get("current") or 0)
        JOB["percent"] = round((current / total) * 100, 1) if total else 0.0
        started = JOB.get("started_at")
        if started and current:
            try:
                elapsed = max(time.time() - datetime.fromisoformat(started).timestamp(), 0.001)
                JOB["rate"] = round(current / elapsed, 2)
                JOB["eta_seconds"] = round(max(total - current, 0) / JOB["rate"], 1) if JOB["rate"] else None
            except ValueError:
                pass


def add_failure(path: Path, error: Exception, phase: str = "index") -> None:
    item = {"path": str(path), "error": f"{type(error).__name__}: {error}", "phase": phase, "time": utc_now()}
    with STATE_LOCK:
        failures = JOB.setdefault("failures", [])
        failures.append(item)
        del failures[:-100]
        JOB["failed"] += 1
        JOB["current"] += 1
    log(f"failed [{phase}] {path}: {error}")


def source_id(path: str) -> str:
    return hashlib.sha1(path.lower().encode("utf-8", errors="ignore")).hexdigest()[:12]


def list_directory(path_text: str) -> dict[str, Any]:
    if not path_text:
        roots = []
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root = Path(f"{letter}:\\")
            if root.exists():
                roots.append({"name": f"{letter}:", "path": str(root), "is_dir": True})
        return {"path": "", "parent": "", "items": roots}
    path = Path(path_text)
    if not path.exists() or not path.is_dir():
        raise ValueError("目录不存在或当前账户无权访问")
    items = []
    try:
        children = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        for child in children:
            if child.is_dir() and not child.name.startswith("$"):
                items.append({"name": child.name, "path": str(child), "is_dir": True})
    except OSError as exc:
        raise ValueError(f"无法读取目录：{exc}") from exc
    return {"path": str(path), "parent": str(path.parent) if path.parent != path else "", "items": items[:500]}


def scan_job(mode: str) -> None:
    config = load_config()
    with STATE_LOCK:
        JOB.update(
            {
                "running": True,
                "mode": mode,
                "started_at": utc_now(),
                "finished_at": "",
                "scanned": 0,
                "indexed": 0,
                "skipped": 0,
                "failed": 0,
                "total": 0,
                "current": 0,
                "percent": 0.0,
                "current_file": "",
                "phase": "scanning",
                "rate": 0.0,
                "eta_seconds": None,
                "failures": [],
                "message": "正在扫描文件清单",
            }
        )
    try:
        global ENGINE
        ENGINE = ENGINE or EmbeddingEngine(config, ROOT)
        records = read_records(config)
        old_by_path = {record["path"]: record for record in records}
        extensions = {value.lower() for value in config["index"].get("extensions", [])}
        max_size = int(config["index"].get("max_file_size_mb", 250)) * 1024 * 1024
        sources = [source for source in config.get("sources", []) if source.get("enabled", True)]
        seen: set[str] = set()
        pending: dict[str, list[tuple[Path, dict[str, Any], dict[str, Any], str | dict[str, str]]]] = {}
        for source in sources:
            root = Path(source["path"])
            if not root.exists():
                log(f"skip unavailable source: {root}")
                continue
            try:
                paths = root.rglob("*")
                for path in paths:
                    if not path.is_file() or path.suffix.lower() not in extensions:
                        continue
                    update_job(scanned=JOB["scanned"] + 1, current_file=str(path), phase="scanning")
                    path_key = str(path)
                    seen.add(path_key)
                    stat = path.stat()
                    old = old_by_path.get(path_key)
                    if (
                        mode == "incremental"
                        and old
                        and old.get("size") == stat.st_size
                        and old.get("mtime") == stat.st_mtime
                        and (not ENGINE.enabled or old.get("embedding_status") == "ready")
                    ):
                        update_job(skipped=JOB["skipped"] + 1, current=JOB["current"] + 1)
                        continue
                    if stat.st_size > max_size:
                        add_failure(path, ValueError(f"文件超过 {max_size // 1024 // 1024} MB 限制"), "size")
                        continue
                    preview = extract_preview(path)
                    input_value = embedding_input(path, preview, config)
                    record = {
                        "path": path_key,
                        "name": path.name,
                        "extension": path.suffix.lower(),
                        "source_id": source["id"],
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                        "hash": quick_hash(path),
                        "preview": preview,
                        "indexed_at": utc_now(),
                        "embedding": None,
                        "embedding_status": "pending_model",
                    }
                    if input_value is None:
                        old_by_path[path_key] = record
                        update_job(indexed=JOB["indexed"] + 1, current=JOB["current"] + 1)
                    else:
                        kind = "image" if isinstance(input_value, dict) else "text"
                        pending.setdefault(kind, []).append((path, source, record, input_value))
            except Exception as exc:
                add_failure(root, exc, "scan")

        total = int(JOB["scanned"])
        update_job(
            total=total,
            phase="loading_model" if ENGINE.enabled and pending else "embedding",
            current_file="正在加载模型..." if ENGINE.enabled and pending else "",
            message="正在加载模型" if ENGINE.enabled and pending else "正在生成向量",
        )
        image_batch_size = int(config["index"].get("image_batch_size", 2))
        text_batch_size = int(config["index"].get("text_batch_size", 8))
        for kind, items in pending.items():
            batch_size = image_batch_size if kind == "image" else text_batch_size
            for offset in range(0, len(items), max(batch_size, 1)):
                batch = items[offset : offset + max(batch_size, 1)]
                values = [item[3] for item in batch]
                vectors = None
                last_error: Exception | None = None
                for attempt in range(2):
                    try:
                        vectors = ENGINE.encode_batch(values) if ENGINE.enabled else [None] * len(batch)
                        break
                    except Exception as exc:
                        last_error = exc
                        update_job(current_file=str(batch[0][0]), phase=f"retry {attempt + 1}/2")
                        time.sleep(0.5)
                if vectors is None:
                    for path, _source, _record, _value in batch:
                        add_failure(path, last_error or RuntimeError("向量生成失败"), "embedding")
                    continue
                for (path, source, record, _value), vector in zip(batch, vectors):
                    record["embedding"] = vector
                    record["embedding_status"] = "ready" if vector else "pending_model"
                    old_by_path[str(path)] = record
                update_job(
                    current=JOB["current"] + len(batch),
                    indexed=JOB["indexed"] + len(batch),
                    current_file=str(batch[-1][0]),
                    phase="embedding",
                )
        # Keep records from unavailable sources; a later scan can recover them.
        # A source may be temporarily offline, so do not delete its records here.
        records = list(old_by_path.values())
        write_records(config, records)
        if config.get("backup", {}).get("enabled") and config["backup"].get("path"):
            backup = Path(config["backup"]["path"])
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(db_path(config), backup / "index.jsonl")
            shutil.copy2(metadata_path(config), backup / "metadata.json")
        with STATE_LOCK:
            JOB["message"] = "索引任务完成"
            JOB["phase"] = "done"
    except Exception as exc:  # keep the web service alive and expose the failure
        log(f"job failed: {exc}")
        with STATE_LOCK:
            JOB["message"] = f"索引失败：{exc}"
            JOB["failed"] += 1
            JOB["phase"] = "error"
    finally:
        with STATE_LOCK:
            JOB["running"] = False
            JOB["finished_at"] = utc_now()
            JOB["current_file"] = ""


def start_scan(mode: str) -> bool:
    with JOB_LOCK:
        with STATE_LOCK:
            if JOB["running"]:
                return False
        thread = threading.Thread(target=scan_job, args=(mode,), daemon=True, name="indexer")
        thread.start()
        return True


def gpu_status() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
        )
        line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        fields = [field.strip() for field in line.split(",")]
        if len(fields) >= 4:
            return {"available": True, "name": fields[0], "memory_total": fields[1], "memory_used": fields[2], "driver": fields[3]}
    except (OSError, subprocess.SubprocessError):
        pass
    return {"available": False, "name": "", "memory_total": "", "memory_used": "", "driver": ""}


def make_status() -> dict[str, Any]:
    config = load_config()
    records = [record for record in read_records(config) if record_is_in_enabled_sources(record, config)]
    with STATE_LOCK:
        job = dict(JOB)
    embedding_status = ENGINE.status() if ENGINE else {
        "enabled": config.get("model", {}).get("enabled", False),
        "loaded": False,
        "name": config.get("model", {}).get("name", "WeMM-Embedding-2B"),
        "path": config.get("model", {}).get("path", ""),
        "dimension": config.get("model", {}).get("dimension", 512),
        "device": config.get("model", {}).get("device", "cuda"),
        "error": "",
    }
    return {
        "service": {"ok": True, "host": socket.gethostname(), "port": config["port"], "time": utc_now()},
        "gpu": gpu_status(),
        "model": {**config["model"], **embedding_status},
        "sources": config.get("sources", []),
        "index": {"records": len(records), "file": str(db_path(config)), "metadata": str(metadata_path(config))},
        "job": job,
    }


def search_records(query: str, limit: int = 50) -> list[dict[str, Any]]:
    config = load_config()
    engine = ENGINE or EmbeddingEngine(config, ROOT)
    query_text = re.sub(r"\s+", " ", query.strip().lower())
    terms = [term for term in re.findall(r"[\w]+", query_text, flags=re.UNICODE) if len(term) > 1]
    results: list[dict[str, Any]] = []
    query_vector = None
    if engine.enabled and query.strip():
        try:
            query_vector = engine.encode(query)
        except Exception as exc:
            log(f"query embedding failed: {exc}")
    records = [record for record in read_records(config) if record_is_in_enabled_sources(record, config)]
    by_path = {str(record.get("path", "")): record for record in records}

    # Exact text matches are always retained; semantic matches must clear a threshold.
    for record in records:
        name = str(record.get("name", "")).lower()
        path = str(record.get("path", "")).lower()
        preview = str(record.get("preview", "")).lower()
        name_hit = any(term in name for term in terms)
        path_hit = any(term in path for term in terms)
        preview_hit = any(term in preview for term in terms)
        fields = ((name, 0.55), (path, 0.15), (preview, 0.30))
        phrase_hit = bool(query_text and any(query_text in field for field, _weight in fields))
        token_hits = sum(1 for term in terms if any(term in field for field, _weight in fields))
        weighted_hits = sum(weight for field, weight in fields if any(term in field for term in terms))
        lexical_score = min(1.0, weighted_hits + (0.35 if phrase_hit else 0.0) + min(token_hits, 3) * 0.08)
        if path_hit and not (name_hit or preview_hit):
            lexical_score = 0.0
        if lexical_score > 0:
            result = dict(record)
            result["lexical_score"] = round(lexical_score, 4)
            result["semantic_score"] = 0.0
            result["match_kind"] = "关键词命中"
            results.append(result)

    semantic_scores: dict[str, float] = {}
    if query_vector:
        try:
            from vector_store import search

            vector_results = search(ROOT, config, query_vector, max(limit * 3, 80))
            for item in vector_results:
                path = str(item.get("path", ""))
                distance = float(item.pop("_distance", 2.0))
                # LanceDB cosine distance is converted to a 0..1 similarity score.
                semantic_scores[path] = max(0.0, min(1.0, 1.0 - distance))
        except Exception as exc:
            log(f"vector search failed: {exc}")

    if semantic_scores:
        top_semantic = max(semantic_scores.values())
        semantic_floor = max(0.34, top_semantic - 0.10)
        existing = {str(item.get("path", "")): item for item in results}
        semantic_only_budget = max(0, min(8 - len(results), 5))
        for path, semantic_score in semantic_scores.items():
            record = by_path.get(path)
            if not record or semantic_score < semantic_floor:
                continue
            result = existing.get(path, dict(record))
            result["semantic_score"] = round(semantic_score, 4)
            result.setdefault("lexical_score", 0.0)
            if result["lexical_score"] <= 0:
                if semantic_only_budget <= 0:
                    continue
                image_floor = 0.46 if str(record.get("extension", "")).lower() in IMAGE_EXTENSIONS else semantic_floor
                if semantic_score < image_floor:
                    continue
                result["match_kind"] = "图片内容相关" if str(record.get("extension", "")).lower() in IMAGE_EXTENSIONS else "语义相关"
                results.append(result)
                semantic_only_budget -= 1

    for result in results:
        lexical_score = float(result.get("lexical_score", 0.0))
        semantic_score = float(result.get("semantic_score", 0.0))
        result["score"] = round(lexical_score * 0.68 + semantic_score * 0.32, 4)
        result.pop("embedding", None)

    results.sort(key=lambda item: (-item["score"], -item.get("mtime", 0)))
    return results[:limit]


class Handler(BaseHTTPRequestHandler):
    server_version = "WeMMSearch/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        log(format % args)

    def send_json(self, payload: Any, status: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def body_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            return self.serve_file(WEB_ROOT / "index.html", "text/html; charset=utf-8")
        if parsed.path.startswith("/static/"):
            filename = Path(parsed.path.removeprefix("/static/")).name
            types = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
            return self.serve_file(WEB_ROOT / filename, types.get(Path(filename).suffix, "application/octet-stream"))
        try:
            query = urllib.parse.parse_qs(parsed.query)
            if parsed.path == "/api/status":
                return self.send_json(make_status())
            if parsed.path == "/api/directories":
                return self.send_json(list_directory(query.get("path", [""])[0]))
            if parsed.path == "/api/files":
                return self.send_json({"items": search_records(query.get("q", [""])[0])})
            if parsed.path == "/api/preview":
                config = load_config()
                path = requested_file(query.get("path", [""])[0], config)
                return self.send_json(preview_payload(path))
            if parsed.path == "/api/file":
                config = load_config()
                path = requested_file(query.get("path", [""])[0], config)
                return self.serve_binary(path)
            if parsed.path == "/api/logs":
                text = LOG_PATH.read_text(encoding="utf-8", errors="ignore") if LOG_PATH.exists() else ""
                return self.send_json({"text": text[-12000:]})
            self.send_json({"error": "not found"}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 400)

    def do_POST(self) -> None:
        try:
            payload = self.body_json()
            if self.path == "/api/sources":
                path_text = str(payload.get("path", "")).strip()
                path = Path(path_text)
                if not path.is_dir():
                    return self.send_json({"error": "目录不存在或不可访问"}, 400)
                config = load_config()
                if any(item.get("path", "").lower() == path_text.lower() for item in config.get("sources", [])):
                    return self.send_json({"error": "目录已经存在"}, 409)
                config.setdefault("sources", []).append(
                    {"id": source_id(path_text), "name": path.name or path_text, "path": path_text, "enabled": True}
                )
                save_config(config)
                return self.send_json({"ok": True, "sources": config["sources"]})
            if self.path == "/api/sources/delete":
                config = load_config()
                source_key = str(payload.get("id", ""))
                config["sources"] = [item for item in config.get("sources", []) if item.get("id") != source_key]
                save_config(config)
                return self.send_json({"ok": True, "sources": config["sources"]})
            if self.path == "/api/index":
                mode = payload.get("mode", "incremental")
                if mode not in {"initial", "incremental"}:
                    return self.send_json({"error": "invalid mode"}, 400)
                if not start_scan(mode):
                    return self.send_json({"error": "已有索引任务运行中"}, 409)
                return self.send_json({"ok": True, "mode": mode}, 202)
            if self.path == "/api/open-folder":
                config = load_config()
                path = requested_file(str(payload.get("path", "")), config)
                if os.name != "nt":
                    return self.send_json({"error": "打开文件夹功能需要服务运行在 Windows 上"}, 400)
                target = f"/select,{path}" if path.is_file() else str(path)
                subprocess.Popen(
                    ["explorer.exe", target],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                )
                return self.send_json({"ok": True})
            if self.path == "/api/open-file":
                config = load_config()
                path = requested_file(str(payload.get("path", "")), config)
                if os.name != "nt":
                    return self.send_json({"error": "打开文件功能需要服务运行在 Windows 上"}, 400)
                os.startfile(str(path))
                return self.send_json({"ok": True})
            if self.path == "/api/config":
                config = load_config()
                for key in ("model", "index", "backup"):
                    if isinstance(payload.get(key), dict):
                        config[key].update(payload[key])
                save_config(config)
                return self.send_json({"ok": True, "config": config})
            self.send_json({"error": "not found"}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 400)

    def serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            return self.send_json({"error": "file not found"}, 404)
        raw = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def serve_binary(self, path: Path) -> None:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Content-Disposition", "inline")
        self.end_headers()
        with path.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile, length=1024 * 1024)


def main() -> None:
    config = load_config()
    global ENGINE
    ENGINE = EmbeddingEngine(config, ROOT)
    for path in ("data", "cache", "logs", "models"):
        (ROOT / path).mkdir(parents=True, exist_ok=True)
    host = config.get("host", "0.0.0.0")
    port = int(config.get("port", 8876))
    server = ThreadingHTTPServer((host, port), Handler)
    log(f"service started on {host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        log("service stopped")


if __name__ == "__main__":
    main()
