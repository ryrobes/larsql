"""
RAG Indexer - ClickHouse Implementation

Builds and updates RAG indexes by:
1. Scanning directories for files
2. Chunking text files
3. Generating embeddings via Agent.embed()
4. Storing chunks and embeddings in ClickHouse tables (rag_chunks, rag_manifests)

Uses ClickHouse's cosineDistance() for vector search - no Python similarity needed.
"""
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console

from ..cascade import RagConfig
from ..config import get_config
from ..agent import Agent
from .context import RagContext

console = Console()


@dataclass
class Chunk:
    """A text chunk with position info."""
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


def _list_take_files(base_dir: str, recursive: bool, include: List[str], exclude: List[str]) -> List[Path]:
    """Return take files respecting include/exclude globs."""
    base = Path(base_dir)
    patterns_include = include or ["*"]
    patterns_exclude = exclude or []

    paths = base.rglob("*") if recursive else base.glob("*")
    takes = []

    for path in paths:
        if path.is_dir():
            continue

        rel = path.relative_to(base).as_posix()
        name = path.name

        if any(fnmatch(rel, pat) or fnmatch(name, pat) for pat in patterns_exclude):
            continue
        if not any(fnmatch(rel, pat) or fnmatch(name, pat) for pat in patterns_include):
            continue

        takes.append(path)

    return takes


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
    cell_name: Optional[str] = None,
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
        cell_name=cell_name,
        cascade_id=cascade_id,
    )


def ensure_rag_index(
    rag_config: RagConfig,
    cascade_path: Optional[str],
    session_id: str,
    trace_id: Optional[str] = None,
    parent_id: Optional[str] = None,
    cell_name: Optional[str] = None,
    cascade_id: Optional[str] = None
) -> RagContext:
    """
    Build or update a RAG index in ClickHouse.

    Returns a RagContext with rag_id and metadata.
    Data is stored in rag_chunks and rag_manifests tables.
    """
    from ..db_adapter import get_db

    abs_dir = _resolve_directory(rag_config, cascade_path)
    console.print(f"[bold cyan][INFO] Building RAG index[/bold cyan] for [white]{abs_dir}[/white] (recursive={rag_config.recursive})")

    if not os.path.isdir(abs_dir):
        raise FileNotFoundError(f"RAG directory not found: {abs_dir}")

    cfg = get_config()
    db = get_db()

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

    # Get existing manifests from ClickHouse
    existing_manifests = db.query(
        f"SELECT doc_id, rel_path, file_hash, mtime, file_size FROM rag_manifests WHERE rag_id = '{rag_id}'"
    )
    prev_by_path: Dict[str, Dict[str, Any]] = {r['rel_path']: r for r in existing_manifests}

    # Get current embedding dimension from existing data (if any)
    existing_dim_result = db.query(
        f"SELECT embedding_dim FROM rag_chunks WHERE rag_id = '{rag_id}' LIMIT 1"
    )
    expected_dim = existing_dim_result[0]['embedding_dim'] if existing_dim_result else None

    # Scan directory for take files
    takes = _list_take_files(abs_dir, rag_config.recursive, include, exclude)
    console.print(f"[dim]Found {len(takes)} data files for RAG indexing[/dim]")
    console.print("[dim](will likely take little while on the first run..._)[/dim]")

    # Track stats
    indexed_files = 0
    skipped_files = 0
    removed_files = 0
    chunks_written = 0
    chunks_reused = 0
    embedding_dim_used = expected_dim

    # Phase 1: Collect all chunks from all files (no embedding yet)
    # Structure: list of (file_info, chunk_objs) where file_info has metadata
    files_to_process = []
    current_rel_paths = set()
    all_text_chunks = []  # Flat list of all chunk texts for batched embedding
    chunk_file_mapping = []  # Track which file each chunk belongs to

    for path in takes:
        rel_path = path.relative_to(abs_dir).as_posix()
        current_rel_paths.add(rel_path)

        stat = path.stat()
        doc_id = _doc_id_for_path(rag_id, rel_path)
        prev = prev_by_path.get(rel_path)

        # Reuse if size + mtime unchanged
        # Note: prev values may be numpy types from ClickHouse, so convert to Python types
        if prev is not None and abs(float(prev.get("mtime", 0)) - stat.st_mtime) < 1e-6 and int(prev.get("file_size", 0)) == stat.st_size:
            chunks_reused_count = db.query(
                f"SELECT count() as cnt FROM rag_chunks WHERE rag_id = '{rag_id}' AND doc_id = '{prev['doc_id']}'"
            )
            chunks_reused += chunks_reused_count[0]['cnt'] if chunks_reused_count else 0
            skipped_files += 1
            continue

        # Read and validate file
        content = _read_text_file(path)
        if content is None:
            skipped_files += 1
            continue

        # Chunk the content
        chunk_objs = _chunk_text(content, chunk_chars, chunk_overlap)
        if not chunk_objs:
            skipped_files += 1
            continue

        content_hash = hashlib.sha1(content.encode("utf-8", errors="ignore")).hexdigest()

        # Store file info for later processing
        file_info = {
            "path": path,
            "rel_path": rel_path,
            "doc_id": doc_id,
            "prev": prev,
            "stat": stat,
            "content_hash": content_hash,
            "chunk_objs": chunk_objs,
            "chunk_start_idx": len(all_text_chunks),  # Track where this file's chunks start
        }
        files_to_process.append(file_info)

        # Add chunks to flat list for batched embedding
        for chunk in chunk_objs:
            all_text_chunks.append(chunk.text)
            chunk_file_mapping.append(len(files_to_process) - 1)  # Index into files_to_process

    # Phase 2: Batch embed all chunks in one API call
    all_embeddings = []
    if all_text_chunks:
        console.print(f"[dim]Embedding {len(all_text_chunks)} chunks in single batch...[/dim]")
        embed_result = embed_texts(
            texts=all_text_chunks,
            model=embed_model,
            session_id=session_id,
            trace_id=trace_id,
            parent_id=parent_id,
            cell_name=cell_name,
            cascade_id=cascade_id,
        )
        all_embeddings = embed_result["embeddings"]
        embedding_dim_used = embedding_dim_used or embed_result["dim"]

        # Validate dimension consistency
        if expected_dim and embed_result["dim"] != expected_dim:
            raise ValueError(
                f"Embedding dimension mismatch (expected {expected_dim}, got {embed_result['dim']}). "
                f"Delete existing chunks for this rag_id and rebuild."
            )

    # Phase 3: Build insert rows with embeddings
    chunks_to_insert = []
    manifests_to_insert = []

    for file_info in files_to_process:
        doc_id = file_info["doc_id"]
        rel_path = file_info["rel_path"]
        prev = file_info["prev"]
        stat = file_info["stat"]
        content_hash = file_info["content_hash"]
        chunk_objs = file_info["chunk_objs"]
        chunk_start_idx = file_info["chunk_start_idx"]

        # Delete old chunks for this doc (if updating)
        if prev:
            db.execute(f"ALTER TABLE rag_chunks DELETE WHERE rag_id = '{rag_id}' AND doc_id = '{prev['doc_id']}'")

        # Prepare manifest row
        manifests_to_insert.append({
            "doc_id": doc_id,
            "rag_id": rag_id,
            "rel_path": rel_path,
            "abs_path": str(file_info["path"]),
            "file_hash": content_hash,
            "file_size": stat.st_size,
            "mtime": stat.st_mtime,
            "chunk_count": len(chunk_objs),
            "content_hash": content_hash,
        })

        # Prepare chunk rows with embeddings from the batched result
        for idx, chunk in enumerate(chunk_objs):
            embedding_idx = chunk_start_idx + idx
            chunks_to_insert.append({
                "rag_id": rag_id,
                "doc_id": doc_id,
                "rel_path": rel_path,
                "chunk_index": idx,
                "text": chunk.text,
                "char_start": chunk.start_char,
                "char_end": chunk.end_char,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "file_hash": content_hash,
                "embedding": all_embeddings[embedding_idx],
                "embedding_model": embed_model,
                "embedding_dim": embedding_dim_used or len(all_embeddings[embedding_idx]),
            })

        indexed_files += 1
        chunks_written += len(chunk_objs)

    # Handle removed files
    previous_rel_paths = set(prev_by_path.keys())
    removed_paths = previous_rel_paths - current_rel_paths
    removed_files = len(removed_paths)

    if removed_paths:
        for rel_path in removed_paths:
            prev = prev_by_path[rel_path]
            db.execute(f"ALTER TABLE rag_chunks DELETE WHERE rag_id = '{rag_id}' AND doc_id = '{prev['doc_id']}'")
            db.execute(f"ALTER TABLE rag_manifests DELETE WHERE rag_id = '{rag_id}' AND doc_id = '{prev['doc_id']}'")

    # Batch insert new data
    if chunks_to_insert:
        db.insert_rows('rag_chunks', chunks_to_insert)

    if manifests_to_insert:
        db.insert_rows('rag_manifests', manifests_to_insert)

    # Get final stats
    total_chunks_result = db.query(f"SELECT count() as cnt FROM rag_chunks WHERE rag_id = '{rag_id}'")
    total_chunks = total_chunks_result[0]['cnt'] if total_chunks_result else 0

    total_docs_result = db.query(f"SELECT count() as cnt FROM rag_manifests WHERE rag_id = '{rag_id}'")
    total_docs = total_docs_result[0]['cnt'] if total_docs_result else 0

    stats = {
        "indexed_files": indexed_files,
        "skipped_files": skipped_files,
        "removed_files": removed_files,
        "chunks_written": chunks_written,
        "chunks_reused": chunks_reused,
        "total_files": total_docs,
        "total_chunks": total_chunks,
    }

    if indexed_files == 0 and removed_files == 0:
        console.print(f"[green][OK] RAG index up-to-date[/green] (rag_id={rag_id}, model={embed_model})")
    else:
        console.print(
            f"[green][OK] RAG index refreshed[/green] (rag_id={rag_id}, model={embed_model}) "
            f"[dim](indexed: {indexed_files}, reused: {chunks_reused}, removed: {removed_files}, chunks: {total_chunks})[/dim]"
        )

    return RagContext(
        rag_id=rag_id,
        directory=abs_dir,
        embed_model=embed_model,
        embedding_dim=embedding_dim_used or 0,
        stats=stats,
        # Session context for logging (so query embeddings get tracked)
        session_id=session_id,
        cascade_id=cascade_id,
        cell_name=cell_name,
        trace_id=trace_id,
        parent_id=parent_id,
    )


def delete_rag_index(rag_id: str):
    """Delete all data for a RAG index."""
    from ..db_adapter import get_db

    db = get_db()
    db.execute(f"ALTER TABLE rag_chunks DELETE WHERE rag_id = '{rag_id}'")
    db.execute(f"ALTER TABLE rag_manifests DELETE WHERE rag_id = '{rag_id}'")
    console.print(f"[yellow]Deleted RAG index: {rag_id}[/yellow]")


def list_rag_indexes() -> List[Dict[str, Any]]:
    """List all RAG indexes in ClickHouse."""
    from ..db_adapter import get_db

    db = get_db()
    return db.query("""
        SELECT
            rag_id,
            count(DISTINCT doc_id) as doc_count,
            count() as chunk_count,
            any(embedding_model) as embed_model,
            min(created_at) as created_at
        FROM rag_chunks
        GROUP BY rag_id
        ORDER BY created_at DESC
    """)
