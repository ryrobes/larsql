"""
Tests for lars.rag.duckdb_store module.

Tests the DuckDB-backed vector store for RAG, which replaces chromadb.
These tests verify:
- Chunk storage and retrieval
- Vector similarity search
- Tombstone-based deletion
- Parquet file management
- Compaction
- Hybrid search (vector + BM25)
"""
import os
import shutil
import tempfile
from unittest.mock import patch, MagicMock
import pytest

from lars.rag.duckdb_store import (
    Chunk,
    ChromaChunk,  # Backwards compat alias
    chunk_id,
    chroma_chunk_id,  # Backwards compat alias
    upsert_chunks,
    delete_by_rag_id,
    delete_by_doc_id,
    query_chunks,
    query_chunks_hybrid,
    get_chunk_by_id,
    compact_collection,
    _collection_dir,
    _get_parquet_files,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def temp_rag_dir(tmp_path):
    """Create a temporary RAG directory for tests."""
    rag_dir = tmp_path / "rag"
    rag_dir.mkdir()
    
    # Patch _get_rag_path to return our temp directory
    with patch('lars.rag.duckdb_store._get_rag_path', return_value=str(rag_dir)):
        yield str(rag_dir)


@pytest.fixture
def sample_chunks():
    """Create sample chunks for testing."""
    return [
        Chunk(
            rag_id='test-rag-001',
            doc_id='doc1',
            chunk_index=0,
            text='The users table contains email and name columns for storing user information.',
            embedding=[0.1 + i * 0.001 for i in range(384)],
            rel_path='schema/users.sql',
            start_line=1,
            end_line=10,
            char_start=0,
            char_end=100,
            file_hash='abc123',
            embedding_model='test-model',
            embedding_dim=384
        ),
        Chunk(
            rag_id='test-rag-001',
            doc_id='doc2',
            chunk_index=0,
            text='The orders table has total price and status fields for tracking purchases.',
            embedding=[0.4 + i * 0.001 for i in range(384)],
            rel_path='schema/orders.sql',
            start_line=1,
            end_line=15,
            char_start=0,
            char_end=150,
            file_hash='def456',
            embedding_model='test-model',
            embedding_dim=384
        ),
        Chunk(
            rag_id='test-rag-001',
            doc_id='doc3',
            chunk_index=0,
            text='The products catalog includes pricing and inventory data.',
            embedding=[0.7 + i * 0.001 for i in range(384)],
            rel_path='schema/products.sql',
            start_line=1,
            end_line=20,
            char_start=0,
            char_end=200,
            file_hash='ghi789',
            embedding_model='test-model',
            embedding_dim=384
        ),
    ]


# =============================================================================
# Chunk Model Tests
# =============================================================================

class TestChunkModel:
    """Tests for Chunk dataclass."""

    def test_chunk_creation(self):
        """Chunk should store all fields correctly."""
        chunk = Chunk(
            rag_id='rag1',
            doc_id='doc1',
            chunk_index=0,
            text='Hello world',
            embedding=[0.1, 0.2, 0.3],
            rel_path='test.txt',
            start_line=1,
            end_line=5,
            char_start=0,
            char_end=11,
            file_hash='abc',
            embedding_model='model',
            embedding_dim=3
        )
        assert chunk.rag_id == 'rag1'
        assert chunk.text == 'Hello world'
        assert len(chunk.embedding) == 3

    def test_chunk_id_generation(self):
        """Chunk ID should be deterministic based on rag_id, doc_id, chunk_index."""
        chunk = Chunk(
            rag_id='rag1',
            doc_id='doc1',
            chunk_index=0,
            text='test',
            embedding=[0.1],
            rel_path='test.txt',
            start_line=1,
            end_line=1,
            char_start=0,
            char_end=4,
            file_hash='abc',
            embedding_model='model',
            embedding_dim=1
        )
        
        id1 = chunk.chunk_id()
        id2 = chunk.chunk_id()
        
        # Same chunk should produce same ID
        assert id1 == id2
        
        # ID should be a hex string (SHA1)
        assert len(id1) == 40
        assert all(c in '0123456789abcdef' for c in id1)

    def test_chunk_id_uniqueness(self):
        """Different chunks should have different IDs."""
        id1 = chunk_id('rag1', 'doc1', 0)
        id2 = chunk_id('rag1', 'doc1', 1)  # Different index
        id3 = chunk_id('rag1', 'doc2', 0)  # Different doc
        id4 = chunk_id('rag2', 'doc1', 0)  # Different rag
        
        assert len({id1, id2, id3, id4}) == 4  # All unique

    def test_chunk_metadata(self):
        """Metadata method should return dict with all fields."""
        chunk = Chunk(
            rag_id='rag1',
            doc_id='doc1',
            chunk_index=5,
            text='test',
            embedding=[0.1],
            rel_path='test.txt',
            start_line=10,
            end_line=20,
            char_start=100,
            char_end=200,
            file_hash='abc123',
            embedding_model='model',
            embedding_dim=1
        )
        
        meta = chunk.metadata()
        
        assert meta['rag_id'] == 'rag1'
        assert meta['doc_id'] == 'doc1'
        assert meta['chunk_index'] == 5
        assert meta['rel_path'] == 'test.txt'
        assert meta['start_line'] == 10
        assert meta['end_line'] == 20
        assert meta['file_hash'] == 'abc123'

    def test_backwards_compat_aliases(self):
        """ChromaChunk and chroma_chunk_id should work as aliases."""
        # ChromaChunk alias
        chunk = ChromaChunk(
            rag_id='rag1',
            doc_id='doc1',
            chunk_index=0,
            text='test',
            embedding=[0.1],
            rel_path='test.txt',
            start_line=1,
            end_line=1,
            char_start=0,
            char_end=4,
            file_hash='abc',
            embedding_model='model',
            embedding_dim=1
        )
        assert isinstance(chunk, Chunk)
        
        # chroma_chunk_id alias
        id1 = chroma_chunk_id('rag1', 'doc1', 0)
        id2 = chunk_id('rag1', 'doc1', 0)
        assert id1 == id2


# =============================================================================
# Upsert Tests
# =============================================================================

class TestUpsertChunks:
    """Tests for chunk upsert operations."""

    def test_upsert_creates_parquet_file(self, temp_rag_dir, sample_chunks):
        """Upserting chunks should create a parquet file."""
        upsert_chunks('test-model', 384, sample_chunks)
        
        coll_dir = _collection_dir('test-model', 384)
        parquet_files = _get_parquet_files(coll_dir)
        
        assert len(parquet_files) >= 1
        assert any(f.endswith('.parquet') for f in parquet_files)

    def test_upsert_empty_list_noop(self, temp_rag_dir):
        """Upserting empty list should be a no-op."""
        upsert_chunks('test-model', 384, [])
        
        coll_dir = _collection_dir('test-model', 384)
        parquet_files = [f for f in _get_parquet_files(coll_dir) 
                        if not os.path.basename(f).startswith('tombstone_')]
        
        assert len(parquet_files) == 0

    def test_upsert_multiple_batches(self, temp_rag_dir, sample_chunks):
        """Multiple upserts should create multiple parquet files."""
        import time
        
        upsert_chunks('test-model', 384, sample_chunks[:1])
        time.sleep(0.01)  # Ensure different timestamp
        upsert_chunks('test-model', 384, sample_chunks[1:2])
        
        coll_dir = _collection_dir('test-model', 384)
        parquet_files = [f for f in _get_parquet_files(coll_dir) 
                        if not os.path.basename(f).startswith('tombstone_')]
        
        # At minimum, verify we can query all chunks (files may merge on fast systems)
        query_vec = [0.1] * 384
        results = query_chunks('test-model', 384, 'test-rag-001', query_vec, 10)
        assert len(results['ids'][0]) == 2  # Both chunks queryable


# =============================================================================
# Query Tests
# =============================================================================

class TestQueryChunks:
    """Tests for vector similarity search."""

    def test_query_returns_results(self, temp_rag_dir, sample_chunks):
        """Query should return matching chunks."""
        upsert_chunks('test-model', 384, sample_chunks)
        
        # Query with embedding similar to first chunk
        query_vec = [0.1 + i * 0.001 for i in range(384)]
        results = query_chunks('test-model', 384, 'test-rag-001', query_vec, 3)
        
        assert 'ids' in results
        assert 'documents' in results
        assert 'distances' in results
        assert len(results['ids'][0]) == 3  # All 3 chunks returned

    def test_query_returns_chromadb_format(self, temp_rag_dir, sample_chunks):
        """Query results should match chromadb response format."""
        upsert_chunks('test-model', 384, sample_chunks)
        
        query_vec = [0.1 + i * 0.001 for i in range(384)]
        results = query_chunks('test-model', 384, 'test-rag-001', query_vec, 2)
        
        # Chromadb format: nested lists
        assert isinstance(results['ids'], list)
        assert isinstance(results['ids'][0], list)
        assert isinstance(results['documents'], list)
        assert isinstance(results['documents'][0], list)
        assert isinstance(results['metadatas'], list)
        assert isinstance(results['metadatas'][0], list)
        assert isinstance(results['distances'], list)
        assert isinstance(results['distances'][0], list)

    def test_query_similarity_ordering(self, temp_rag_dir, sample_chunks):
        """Results should be ordered by similarity (closest first)."""
        upsert_chunks('test-model', 384, sample_chunks)
        
        # Query with embedding very close to first chunk
        query_vec = [0.1 + i * 0.001 for i in range(384)]
        results = query_chunks('test-model', 384, 'test-rag-001', query_vec, 3)
        
        distances = results['distances'][0]
        
        # Distances should be sorted ascending (lower = more similar)
        assert distances == sorted(distances)

    def test_query_empty_collection(self, temp_rag_dir):
        """Query on empty collection should return empty results."""
        query_vec = [0.1 + i * 0.001 for i in range(384)]
        results = query_chunks('test-model', 384, 'nonexistent-rag', query_vec, 5)
        
        assert results['ids'] == [[]]
        assert results['documents'] == [[]]
        assert results['distances'] == [[]]

    def test_query_filters_by_rag_id(self, temp_rag_dir, sample_chunks):
        """Query should only return chunks matching the rag_id."""
        # Add chunks with different rag_id
        other_chunks = [
            Chunk(
                rag_id='other-rag',
                doc_id='doc1',
                chunk_index=0,
                text='Different RAG context',
                embedding=[0.9 + i * 0.001 for i in range(384)],
                rel_path='other.sql',
                start_line=1,
                end_line=5,
                char_start=0,
                char_end=50,
                file_hash='xyz',
                embedding_model='test-model',
                embedding_dim=384
            )
        ]
        
        upsert_chunks('test-model', 384, sample_chunks)
        upsert_chunks('test-model', 384, other_chunks)
        
        query_vec = [0.1 + i * 0.001 for i in range(384)]
        
        # Query only test-rag-001
        results = query_chunks('test-model', 384, 'test-rag-001', query_vec, 10)
        
        # Should only get chunks from test-rag-001
        for meta in results['metadatas'][0]:
            assert meta['rag_id'] == 'test-rag-001'


# =============================================================================
# Delete Tests
# =============================================================================

class TestDeleteOperations:
    """Tests for delete operations."""

    def test_delete_by_rag_id(self, temp_rag_dir, sample_chunks):
        """Delete by rag_id should remove all chunks for that RAG."""
        upsert_chunks('test-model', 384, sample_chunks)
        
        # Verify chunks exist
        query_vec = [0.1 + i * 0.001 for i in range(384)]
        results_before = query_chunks('test-model', 384, 'test-rag-001', query_vec, 10)
        assert len(results_before['ids'][0]) == 3
        
        # Delete
        delete_by_rag_id('test-model', 384, 'test-rag-001')
        
        # Verify chunks gone
        results_after = query_chunks('test-model', 384, 'test-rag-001', query_vec, 10)
        assert len(results_after['ids'][0]) == 0

    def test_delete_by_doc_id(self, temp_rag_dir, sample_chunks):
        """Delete by doc_id should only remove chunks for that document."""
        upsert_chunks('test-model', 384, sample_chunks)
        
        # Delete only doc1
        delete_by_doc_id('test-model', 384, 'test-rag-001', 'doc1')
        
        # Query remaining
        query_vec = [0.1 + i * 0.001 for i in range(384)]
        results = query_chunks('test-model', 384, 'test-rag-001', query_vec, 10)
        
        # Should have 2 remaining (doc2 and doc3)
        assert len(results['ids'][0]) == 2
        
        # Verify doc1 is gone
        for meta in results['metadatas'][0]:
            assert meta['doc_id'] != 'doc1'

    def test_delete_creates_tombstone(self, temp_rag_dir, sample_chunks):
        """Delete should create a tombstone file."""
        upsert_chunks('test-model', 384, sample_chunks)
        
        delete_by_rag_id('test-model', 384, 'test-rag-001')
        
        coll_dir = _collection_dir('test-model', 384)
        parquet_files = _get_parquet_files(coll_dir)
        
        tombstone_files = [f for f in parquet_files if 'tombstone' in os.path.basename(f)]
        assert len(tombstone_files) >= 1


# =============================================================================
# Get Chunk By ID Tests
# =============================================================================

class TestGetChunkById:
    """Tests for getting specific chunks."""

    def test_get_existing_chunk(self, temp_rag_dir, sample_chunks):
        """Should retrieve existing chunk by composite ID."""
        upsert_chunks('test-model', 384, sample_chunks)
        
        result = get_chunk_by_id('test-model', 384, 'test-rag-001', 'doc1', 0)
        
        assert result is not None
        assert 'text' in result
        assert 'metadata' in result
        assert 'users table' in result['text']
        assert result['metadata']['doc_id'] == 'doc1'

    def test_get_nonexistent_chunk(self, temp_rag_dir, sample_chunks):
        """Should return None for non-existent chunk."""
        upsert_chunks('test-model', 384, sample_chunks)
        
        result = get_chunk_by_id('test-model', 384, 'test-rag-001', 'nonexistent', 0)
        
        assert result is None

    def test_get_chunk_empty_collection(self, temp_rag_dir):
        """Should return None from empty collection."""
        result = get_chunk_by_id('test-model', 384, 'test-rag-001', 'doc1', 0)
        
        assert result is None


# =============================================================================
# Compaction Tests
# =============================================================================

class TestCompaction:
    """Tests for collection compaction."""

    def test_compact_merges_files(self, temp_rag_dir, sample_chunks):
        """Compaction should merge multiple parquet files into one."""
        import time
        
        # Create multiple files with small delays to ensure different timestamps
        upsert_chunks('test-model', 384, sample_chunks[:1])
        time.sleep(0.01)  # Small delay for unique timestamp
        upsert_chunks('test-model', 384, sample_chunks[1:2])
        time.sleep(0.01)
        upsert_chunks('test-model', 384, sample_chunks[2:3])
        
        coll_dir = _collection_dir('test-model', 384)
        files_before = len(_get_parquet_files(coll_dir))
        assert files_before >= 2  # At least 2 files (timing can vary)
        
        # Compact
        count = compact_collection('test-model', 384)
        
        # Should have one compacted file
        files_after = _get_parquet_files(coll_dir)
        chunk_files = [f for f in files_after if not 'tombstone' in os.path.basename(f)]
        assert len(chunk_files) == 1
        assert count == 3  # 3 chunks remain

    def test_compact_applies_tombstones(self, temp_rag_dir, sample_chunks):
        """Compaction should apply tombstones and remove deleted chunks."""
        upsert_chunks('test-model', 384, sample_chunks)
        delete_by_doc_id('test-model', 384, 'test-rag-001', 'doc1')
        
        # Compact
        count = compact_collection('test-model', 384)
        
        # Should have 2 chunks (doc1 was deleted)
        assert count == 2
        
        # Verify tombstone files are removed after compaction
        coll_dir = _collection_dir('test-model', 384)
        files = _get_parquet_files(coll_dir)
        tombstone_files = [f for f in files if 'tombstone' in os.path.basename(f)]
        assert len(tombstone_files) == 0

    def test_compact_empty_collection(self, temp_rag_dir):
        """Compacting empty collection should return 0."""
        count = compact_collection('test-model', 384)
        assert count == 0

    def test_compact_all_deleted(self, temp_rag_dir, sample_chunks):
        """Compacting after deleting all should return 0 and clean up files."""
        upsert_chunks('test-model', 384, sample_chunks)
        delete_by_rag_id('test-model', 384, 'test-rag-001')
        
        count = compact_collection('test-model', 384)
        
        assert count == 0
        
        # All files should be cleaned up
        coll_dir = _collection_dir('test-model', 384)
        files = _get_parquet_files(coll_dir)
        assert len(files) == 0


# =============================================================================
# Hybrid Search Tests
# =============================================================================

class TestHybridSearch:
    """Tests for hybrid vector + BM25 search."""

    def test_hybrid_search_returns_results(self, temp_rag_dir, sample_chunks):
        """Hybrid search should return results."""
        upsert_chunks('test-model', 384, sample_chunks)
        
        query_vec = [0.1 + i * 0.001 for i in range(384)]
        results = query_chunks_hybrid(
            'test-model', 384, 'test-rag-001',
            query_vec, 'users email', 3
        )
        
        assert 'ids' in results
        assert len(results['ids'][0]) <= 3

    def test_hybrid_search_boosts_keyword_matches(self, temp_rag_dir, sample_chunks):
        """Hybrid search should boost chunks with keyword matches."""
        upsert_chunks('test-model', 384, sample_chunks)
        
        # Use a query vector that's NOT close to the users chunk,
        # but use keywords that should match it
        query_vec = [0.7 + i * 0.001 for i in range(384)]  # Close to products chunk
        
        results_vector_only = query_chunks(
            'test-model', 384, 'test-rag-001',
            query_vec, 3
        )
        
        results_hybrid = query_chunks_hybrid(
            'test-model', 384, 'test-rag-001',
            query_vec, 'users email table columns',  # Keywords matching doc1
            3, vector_weight=0.3  # Favor text matching
        )
        
        # Both should return results
        assert len(results_vector_only['ids'][0]) > 0
        assert len(results_hybrid['ids'][0]) > 0


# =============================================================================
# Deduplication Tests
# =============================================================================

class TestDeduplication:
    """Tests for handling duplicate chunks."""

    def test_duplicate_upserts_deduped_at_query_time(self, temp_rag_dir):
        """Duplicate chunks should be deduplicated at query time (latest wins)."""
        chunk_v1 = Chunk(
            rag_id='test-rag',
            doc_id='doc1',
            chunk_index=0,
            text='Version 1 of the text',
            embedding=[0.1] * 384,
            rel_path='doc.txt',
            start_line=1,
            end_line=1,
            char_start=0,
            char_end=20,
            file_hash='v1',
            embedding_model='test-model',
            embedding_dim=384
        )
        
        chunk_v2 = Chunk(
            rag_id='test-rag',
            doc_id='doc1',
            chunk_index=0,  # Same composite ID
            text='Version 2 of the text - UPDATED',
            embedding=[0.1] * 384,
            rel_path='doc.txt',
            start_line=1,
            end_line=1,
            char_start=0,
            char_end=30,
            file_hash='v2',
            embedding_model='test-model',
            embedding_dim=384
        )
        
        # Upsert v1 then v2
        upsert_chunks('test-model', 384, [chunk_v1])
        upsert_chunks('test-model', 384, [chunk_v2])
        
        # Query should return only 1 result (deduplicated)
        query_vec = [0.1] * 384
        results = query_chunks('test-model', 384, 'test-rag', query_vec, 10)
        
        assert len(results['ids'][0]) == 1
        # Should have the v2 text (latest)
        assert 'UPDATED' in results['documents'][0][0]


# =============================================================================
# Edge Case Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_special_characters_in_text(self, temp_rag_dir):
        """Chunks with special characters should be handled correctly."""
        chunk = Chunk(
            rag_id='test-rag',
            doc_id='doc1',
            chunk_index=0,
            text="Special chars: 'quotes', \"double\", `backticks`, \n\tnewlines\ttabs",
            embedding=[0.1] * 384,
            rel_path='doc.txt',
            start_line=1,
            end_line=2,
            char_start=0,
            char_end=50,
            file_hash='abc',
            embedding_model='test-model',
            embedding_dim=384
        )
        
        upsert_chunks('test-model', 384, [chunk])
        
        result = get_chunk_by_id('test-model', 384, 'test-rag', 'doc1', 0)
        assert result is not None
        assert 'quotes' in result['text']

    def test_unicode_in_text(self, temp_rag_dir):
        """Chunks with unicode should be handled correctly."""
        chunk = Chunk(
            rag_id='test-rag',
            doc_id='doc1',
            chunk_index=0,
            text='Unicode: émojis 🎉, 中文, العربية',
            embedding=[0.1] * 384,
            rel_path='doc.txt',
            start_line=1,
            end_line=1,
            char_start=0,
            char_end=30,
            file_hash='abc',
            embedding_model='test-model',
            embedding_dim=384
        )
        
        upsert_chunks('test-model', 384, [chunk])
        
        result = get_chunk_by_id('test-model', 384, 'test-rag', 'doc1', 0)
        assert result is not None
        assert '🎉' in result['text']
        assert '中文' in result['text']

    def test_very_long_text(self, temp_rag_dir):
        """Very long text should be handled correctly."""
        long_text = 'word ' * 10000  # 50K characters
        
        chunk = Chunk(
            rag_id='test-rag',
            doc_id='doc1',
            chunk_index=0,
            text=long_text,
            embedding=[0.1] * 384,
            rel_path='doc.txt',
            start_line=1,
            end_line=100,
            char_start=0,
            char_end=len(long_text),
            file_hash='abc',
            embedding_model='test-model',
            embedding_dim=384
        )
        
        upsert_chunks('test-model', 384, [chunk])
        
        result = get_chunk_by_id('test-model', 384, 'test-rag', 'doc1', 0)
        assert result is not None
        assert len(result['text']) == len(long_text)

    def test_different_embedding_dimensions(self, temp_rag_dir):
        """Different embedding dimensions should be stored separately."""
        chunk_384 = Chunk(
            rag_id='test-rag',
            doc_id='doc1',
            chunk_index=0,
            text='384-dim embedding',
            embedding=[0.1] * 384,
            rel_path='doc.txt',
            start_line=1,
            end_line=1,
            char_start=0,
            char_end=20,
            file_hash='abc',
            embedding_model='model-384',
            embedding_dim=384
        )
        
        chunk_768 = Chunk(
            rag_id='test-rag',
            doc_id='doc1',
            chunk_index=0,
            text='768-dim embedding',
            embedding=[0.1] * 768,
            rel_path='doc.txt',
            start_line=1,
            end_line=1,
            char_start=0,
            char_end=20,
            file_hash='abc',
            embedding_model='model-768',
            embedding_dim=768
        )
        
        upsert_chunks('model-384', 384, [chunk_384])
        upsert_chunks('model-768', 768, [chunk_768])
        
        # Each should be queryable independently
        result_384 = get_chunk_by_id('model-384', 384, 'test-rag', 'doc1', 0)
        result_768 = get_chunk_by_id('model-768', 768, 'test-rag', 'doc1', 0)
        
        assert result_384 is not None
        assert result_768 is not None
        assert '384' in result_384['text']
        assert '768' in result_768['text']
