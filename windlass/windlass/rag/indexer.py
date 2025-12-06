import hashlib
import json
import os
import time
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from ..cascade import RagConfig
from ..config import get_config
from ..agent import Agent
from .context import RagContext
from rich.console import Console

console = Console()

@dataclass
class Chunk:
    text: str
    start_char: int
    end_char: int
    start_line: int
    end_line: int

def _resolve_directory(rag_config: RagConfig, cascade_path: Optional[str]) -> str:
    """Resolve directory relative to cascade file if not absolute."""
    if os.path.isabs(rag_config.directory):
        return rag_config.directory

    base_dir = os.path.dirname(cascade_path) if isinstance(cascade_path, str) else get_config().root_dir
    return os.path.abspath(os.path.join(base_dir, rag_config.directory))

def _doc_id_for_path(rag_id: str, rel_path: str) -> str:
    """Stable doc id for a file path."""
    digest = hashlib.sha1(f"{rag_id}:{rel_path}".encode()).hexdigest()
    return digest[:12]

def _list_candidate_files(base_dir: str, recursive: bool, include: List[str], exclude: List[str]) -> List[Path]:
    """Return candidate files respecting include/exclude globs."""
    base = Path(base_dir)
    patterns_include = include or ["*"]
    patterns_exclude = exclude or []

    paths = base.rglob("*") if recursive else base.glob("*")
    candidates = []
    for path in paths:
        if path.is_dir():
            continue

        rel = path.relative_to(base).as_posix()
        name = path.name

        if any(fnmatch(rel, pat) or fnmatch(name, pat) for pat in patterns_exclude):
            continue
        if not any(fnmatch(rel, pat) or fnmatch(name, pat) for pat in patterns_include):
            continue

        candidates.append(path)
    return candidates

def _is_probably_binary(sample: bytes) -> bool:
    """Heuristic to skip obvious binary files."""
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    # If more than 30% non-text bytes, treat as binary
    text_chars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)))
    nontext = sample.translate(None, text_chars)
    return float(len(nontext)) / max(len(sample), 1) > 0.30

def _read_text_file(path: Path) -> Optional[str]:
    """Read text content, skipping binaries."""
    try:
        with open(path, "rb") as f:
            sample = f.read(1024)
            if _is_probably_binary(sample):
                return None
            rest = f.read()
            data = sample + rest
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return None

def _chunk_text(text: str, chunk_size: int, overlap: int) -> List[Chunk]:
    """Split text into overlapping chunks."""
    norm = text.replace("\r\n", "\n")
    if overlap >= chunk_size:
        overlap = max(0, chunk_size // 2)

    chunks: List[Chunk] = []
    start = 0
    total_len = len(norm)
    while start < total_len:
        end = min(total_len, start + chunk_size)
        chunk_text = norm[start:end]

        if not chunk_text.strip():
            # Skip empty/whitespace-only chunks
            if end >= total_len:
                break
            start = end
            continue

        start_line = norm.count("\n", 0, start) + 1
        end_line = norm.count("\n", 0, end) + 1

        chunks.append(Chunk(
            text=chunk_text,
            start_char=start,
            end_char=end,
            start_line=start_line,
            end_line=end_line
        ))

        if end >= total_len:
            break

        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start

    return chunks

def embed_texts(
    texts: List[str],
    model: Optional[str] = None,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    phase_name: Optional[str] = None,
    cascade_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Embed texts using Agent.embed() - goes through standard provider config and logging.

    Returns dict with: embeddings, model, dim, request_id, tokens, provider
    """
    return Agent.embed(
        texts=texts,
        model=model,
        session_id=session_id,
        trace_id=trace_id,
        parent_id=parent_id,
        phase_name=phase_name,
        cascade_id=cascade_id,
    )

def ensure_rag_index(
    rag_config: RagConfig,
    cascade_path: Optional[str],
    session_id: str,
    trace_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    phase_name: Optional[str] = None,
    cascade_id: Optional[str] = None
) -> RagContext:
    """
    Build or update a RAG index for the given rag_config.
    Returns a RagContext with paths and metadata.
    """
    abs_dir = _resolve_directory(rag_config, cascade_path)
    console.print(f"[bold cyan]📚 Building RAG index[/bold cyan] for [white]{abs_dir}[/white] (recursive={rag_config.recursive})")
    if not os.path.isdir(abs_dir):
        raise FileNotFoundError(f"RAG directory not found: {abs_dir}")

    cfg = get_config()
    include = rag_config.include or RagConfig.model_fields["include"].default_factory()
    exclude = rag_config.exclude or RagConfig.model_fields["exclude"].default_factory()
    chunk_chars = max(rag_config.chunk_chars or 1200, 200)
    chunk_overlap = max(min(rag_config.chunk_overlap or 200, chunk_chars - 1), 0)
    embed_model = rag_config.model or cfg.default_embed_model

    # rag_id is a hash of settings that affect the index content
    settings_key = json.dumps({
        "directory": abs_dir,
        "recursive": rag_config.recursive,
        "include": sorted(include),
        "exclude": sorted(exclude),
        "chunk_chars": chunk_chars,
        "chunk_overlap": chunk_overlap,
        "embed_model": embed_model,
    }, sort_keys=True)
    rag_id = hashlib.sha1(settings_key.encode()).hexdigest()[:12]

    rag_base = os.path.join(cfg.data_dir, "rag", rag_id)
    os.makedirs(rag_base, exist_ok=True)

    manifest_path = os.path.join(rag_base, "manifest.parquet")
    chunks_path = os.path.join(rag_base, "chunks.parquet")
    meta_path = os.path.join(rag_base, "meta.json")

    existing_manifest = pd.read_parquet(manifest_path) if os.path.exists(manifest_path) else None
    existing_chunks = pd.read_parquet(chunks_path) if os.path.exists(chunks_path) else None
    existing_meta = None
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r") as f:
                existing_meta = json.load(f)
        except Exception:
            existing_meta = None

    # If we already have an index with a different model, we need to reindex
    expected_dim = None
    if existing_meta:
        existing_model = existing_meta.get("embed_model")
        if existing_model and existing_model != embed_model:
            console.print(f"[yellow]⚠️  Model changed from {existing_model} to {embed_model}, will reindex all files[/yellow]")
            existing_manifest = None
            existing_chunks = None
        else:
            expected_dim = existing_meta.get("embedding_dim")

    candidates = _list_candidate_files(abs_dir, rag_config.recursive, include, exclude)
    console.print(f"[dim]Found {len(candidates)} candidate files for RAG indexing[/dim]")

    prev_by_path: Dict[str, Dict[str, Any]] = {}
    if existing_manifest is not None:
        prev_by_path = {row["rel_path"]: row.to_dict() for _, row in existing_manifest.iterrows()}

    new_manifest_rows: List[Dict[str, Any]] = []
    new_chunk_rows: List[Dict[str, Any]] = []

    indexed_files = 0
    skipped_files = 0
    removed_files = 0
    chunks_written = 0
    chunks_reused = 0
    embedding_dim_used = expected_dim

    for path in candidates:
        rel_path = path.relative_to(abs_dir).as_posix()
        stat = path.stat()
        doc_id = _doc_id_for_path(rag_id, rel_path)
        prev = prev_by_path.get(rel_path)

        # Reuse if size + mtime unchanged
        if prev is not None and abs(prev.get("mtime", 0) - stat.st_mtime) < 1e-6 and prev.get("size") == stat.st_size:
            new_manifest_rows.append(prev)
            if existing_chunks is not None:
                doc_chunks = existing_chunks[existing_chunks["doc_id"] == prev["doc_id"]]
                chunks_reused += len(doc_chunks)
                new_chunk_rows.extend(doc_chunks.to_dict("records"))
            skipped_files += 1
            continue

        content = _read_text_file(path)
        if content is None:
            skipped_files += 1
            continue

        chunk_objs = _chunk_text(content, chunk_chars, chunk_overlap)
        if not chunk_objs:
            skipped_files += 1
            continue

        text_chunks = [c.text for c in chunk_objs]

        # Embed using Agent.embed() - handles logging automatically
        embed_result = embed_texts(
            texts=text_chunks,
            model=embed_model,
            session_id=session_id,
            trace_id=trace_id,
            parent_id=parent_id,
            phase_name=phase_name,
            cascade_id=cascade_id,
        )
        embeddings = embed_result["embeddings"]
        embedding_dim_used = embedding_dim_used or embed_result["dim"]

        # Validate dimension consistency
        if expected_dim and embed_result["dim"] != expected_dim:
            raise ValueError(
                f"Embedding dimension mismatch (expected {expected_dim}, got {embed_result['dim']}). "
                f"Delete the index at {rag_base} and rebuild."
            )

        manifest_row = {
            "doc_id": doc_id,
            "rel_path": rel_path,
            "abs_path": str(path),
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "chunk_count": len(chunk_objs),
            "content_hash": hashlib.sha1(content.encode("utf-8", errors="ignore")).hexdigest()
        }
        new_manifest_rows.append(manifest_row)

        for idx, chunk in enumerate(chunk_objs):
            chunk_id = f"{doc_id}_{idx}"
            new_chunk_rows.append({
                "rag_id": rag_id,
                "doc_id": doc_id,
                "chunk_id": chunk_id,
                "rel_path": rel_path,
                "start_char": chunk.start_char,
                "end_char": chunk.end_char,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "text": chunk.text,
                "embedding": embeddings[idx],
            })

        indexed_files += 1
        chunks_written += len(chunk_objs)

    # Handle removed files
    current_rel_paths = {p.relative_to(abs_dir).as_posix() for p in candidates}
    previous_rel_paths = set(prev_by_path.keys())
    removed_paths = previous_rel_paths - current_rel_paths
    removed_files = len(removed_paths)

    # Filter out removed docs from reused chunks/manifest
    if removed_paths:
        new_manifest_rows = [row for row in new_manifest_rows if row["rel_path"] not in removed_paths]
        new_chunk_rows = [row for row in new_chunk_rows if row["rel_path"] not in removed_paths]

    manifest_columns = ["doc_id", "rel_path", "abs_path", "mtime", "size", "chunk_count", "content_hash"]
    chunk_columns = [
        "rag_id", "doc_id", "chunk_id", "rel_path",
        "start_char", "end_char", "start_line", "end_line",
        "text", "embedding"
    ]

    manifest_df = pd.DataFrame(new_manifest_rows, columns=manifest_columns)
    chunks_df = pd.DataFrame(new_chunk_rows, columns=chunk_columns)

    # Save Parquet
    manifest_df.to_parquet(manifest_path, index=False)
    chunks_df.to_parquet(chunks_path, index=False)

    # Clear store cache so subsequent searches use fresh data
    from .store import clear_cache
    clear_cache()

    # Stats and meta
    stats = {
        "indexed_files": indexed_files,
        "skipped_files": skipped_files,
        "removed_files": removed_files,
        "chunks_written": chunks_written,
        "chunks_reused": chunks_reused,
        "total_files": len(candidates),
        "total_chunks": len(chunks_df),
    }

    meta = {
        "rag_id": rag_id,
        "directory": abs_dir,
        "recursive": rag_config.recursive,
        "include": include,
        "exclude": exclude,
        "chunk_chars": chunk_chars,
        "chunk_overlap": chunk_overlap,
        "embed_model": embed_model,
        "embedding_dim": embedding_dim_used,
        "manifest_path": manifest_path,
        "chunks_path": chunks_path,
        "created_at": existing_meta.get("created_at") if existing_meta else time.time(),
        "updated_at": time.time(),
        "stats": stats,
    }

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    if indexed_files == 0 and removed_files == 0:
        console.print(f"[green]✓ RAG index up-to-date[/green] (rag_id={rag_id}, model={embed_model})")
    else:
        console.print(
            f"[green]✓ RAG index refreshed[/green] (rag_id={rag_id}, model={embed_model}) "
            f"[dim](indexed: {indexed_files}, reused: {chunks_reused}, removed: {removed_files}, chunks: {meta['stats']['total_chunks']})[/dim]"
        )

    return RagContext(
        rag_id=rag_id,
        directory=abs_dir,
        manifest_path=manifest_path,
        chunks_path=chunks_path,
        meta_path=meta_path,
        embed_model=embed_model,
        stats=stats,
        # Session context for logging (so query embeddings get tracked)
        session_id=session_id,
        cascade_id=cascade_id,
        phase_name=phase_name,
        trace_id=trace_id,
        parent_id=parent_id,
    )
