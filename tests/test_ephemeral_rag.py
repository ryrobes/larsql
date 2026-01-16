"""
Tests for lars.ephemeral_rag module.

Tests the automatic indexing system for large content that would otherwise
overflow LLM context windows. These tests verify:
- Content size detection
- Chunking with sentence boundary awareness
- Placeholder generation
- Search tool creation
- Template data processing
- Tool result processing

Note: These tests mock ClickHouse interactions to avoid database dependencies.
"""
from unittest.mock import patch, MagicMock
from lars.ephemeral_rag import (
    EphemeralRagManager,
    LargeContentReplacement,
    ChunkInfo,
    DEFAULT_THRESHOLD,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CHUNK_OVERLAP,
    is_ephemeral_rag_enabled,
)


# =============================================================================
# ChunkInfo Tests
# =============================================================================

class TestChunkInfo:
    """Tests for ChunkInfo dataclass."""

    def test_chunk_info_creation(self):
        """ChunkInfo should store all fields correctly."""
        chunk = ChunkInfo(
            text="Hello world",
            start=0,
            end=11,
            index=0
        )
        assert chunk.text == "Hello world"
        assert chunk.start == 0
        assert chunk.end == 11
        assert chunk.index == 0


# =============================================================================
# LargeContentReplacement Tests
# =============================================================================

class TestLargeContentReplacement:
    """Tests for LargeContentReplacement dataclass."""

    def test_replacement_creation(self):
        """LargeContentReplacement should store all tracking fields."""
        replacement = LargeContentReplacement(
            source="input.document",
            safe_name="input_document",
            original_size=150000,
            original_type="string",
            rag_id="eph_abc123",
            chunk_count=50,
            tool_name="search_input_document",
            placeholder="[LARGE CONTENT: 150K chars indexed...]",
            indexed_at=1234567890.0,
            content_hash="abc123def456"
        )
        assert replacement.source == "input.document"
        assert replacement.original_size == 150000
        assert replacement.chunk_count == 50
        assert replacement.tool_name == "search_input_document"


# =============================================================================
# EphemeralRagManager Initialization Tests
# =============================================================================

class TestEphemeralRagManagerInit:
    """Tests for EphemeralRagManager initialization."""

    def test_default_initialization(self):
        """Manager should initialize with default values."""
        manager = EphemeralRagManager(
            session_id="test_session",
            cell_name="test_cell"
        )
        assert manager.session_id == "test_session"
        assert manager.cell_name == "test_cell"
        assert manager.threshold == DEFAULT_THRESHOLD
        assert manager.chunk_size == DEFAULT_CHUNK_SIZE
        assert manager.chunk_overlap == DEFAULT_CHUNK_OVERLAP

    def test_custom_threshold(self):
        """Manager should accept custom threshold."""
        manager = EphemeralRagManager(
            session_id="test",
            cell_name="cell",
            threshold=50000
        )
        assert manager.threshold == 50000

    def test_custom_chunk_settings(self):
        """Manager should accept custom chunk size and overlap."""
        manager = EphemeralRagManager(
            session_id="test",
            cell_name="cell",
            chunk_size=2000,
            chunk_overlap=300
        )
        assert manager.chunk_size == 2000
        assert manager.chunk_overlap == 300

    def test_initial_state_empty(self):
        """Manager should start with no replacements or tools."""
        manager = EphemeralRagManager("test", "cell")
        assert manager.get_stats()["replacements_count"] == 0
        assert manager.get_stats()["total_chunks_indexed"] == 0
        assert len(manager.get_all_tools()) == 0


# =============================================================================
# EphemeralRagManager Chunking Tests
# =============================================================================

class TestEphemeralRagManagerChunking:
    """Tests for text chunking logic."""

    def test_chunk_small_text_returns_single_chunk(self):
        """Text smaller than chunk_size should return single chunk."""
        manager = EphemeralRagManager("test", "cell", chunk_size=1000)
        chunks = manager._chunk_text("Hello world. This is a test.")

        assert len(chunks) == 1
        assert chunks[0].text == "Hello world. This is a test."
        assert chunks[0].index == 0

    def test_chunk_respects_sentence_boundaries(self):
        """Chunking should prefer breaking at sentence boundaries."""
        manager = EphemeralRagManager("test", "cell", chunk_size=50, chunk_overlap=10)
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        chunks = manager._chunk_text(text)

        # Each chunk should end at a sentence boundary when possible
        for chunk in chunks:
            # Either ends with a period or is the last chunk
            assert chunk.text.rstrip().endswith('.') or chunk == chunks[-1]

    def test_chunk_overlap(self):
        """Consecutive chunks should have overlap."""
        manager = EphemeralRagManager("test", "cell", chunk_size=30, chunk_overlap=10)
        text = "A" * 100  # No sentence boundaries
        chunks = manager._chunk_text(text)

        # With overlap, we should have more chunks than without
        assert len(chunks) > 3

    def test_chunk_preserves_all_content(self):
        """All content should be preserved across chunks (accounting for overlap)."""
        manager = EphemeralRagManager("test", "cell", chunk_size=50, chunk_overlap=10)
        text = "The quick brown fox jumps over the lazy dog. " * 10
        chunks = manager._chunk_text(text)

        # First chunk should start from beginning
        assert chunks[0].start == 0
        # Last chunk should end at the text length
        assert chunks[-1].end == len(text)

    def test_chunk_indices_sequential(self):
        """Chunk indices should be sequential starting from 0."""
        manager = EphemeralRagManager("test", "cell", chunk_size=50)
        text = "Word " * 100
        chunks = manager._chunk_text(text)

        for i, chunk in enumerate(chunks):
            assert chunk.index == i


# =============================================================================
# EphemeralRagManager Content Detection Tests (via _check_and_replace)
# =============================================================================

class TestEphemeralRagManagerContentDetection:
    """Tests for large content detection via _check_and_replace."""

    @patch.object(EphemeralRagManager, '_index_and_replace')
    def test_detect_large_string(self, mock_index):
        """String larger than threshold should trigger indexing."""
        mock_index.return_value = ("placeholder", "search_tool")

        manager = EphemeralRagManager("test", "cell", threshold=100)

        # Large string should trigger indexing
        result, tool = manager._check_and_replace("x" * 150, "test_source")
        assert tool is not None
        mock_index.assert_called_once()

        mock_index.reset_mock()

        # Small string should not trigger indexing
        result, tool = manager._check_and_replace("x" * 50, "test_source")
        assert tool is None
        mock_index.assert_not_called()

    @patch.object(EphemeralRagManager, '_index_and_replace')
    def test_detect_large_dict(self, mock_index):
        """Dict with large serialized size should trigger indexing."""
        mock_index.return_value = ("placeholder", "search_tool")

        manager = EphemeralRagManager("test", "cell", threshold=100)

        # Large dict should trigger indexing
        large_dict = {"data": "x" * 150}
        result, tool = manager._check_and_replace(large_dict, "test_source")
        assert tool is not None

        mock_index.reset_mock()

        # Small dict should not trigger indexing
        small_dict = {"data": "x" * 10}
        result, tool = manager._check_and_replace(small_dict, "test_source")
        assert tool is None

    @patch.object(EphemeralRagManager, '_index_and_replace')
    def test_detect_large_list(self, mock_index):
        """List with large serialized size should trigger indexing."""
        mock_index.return_value = ("placeholder", "search_tool")

        manager = EphemeralRagManager("test", "cell", threshold=100)

        # Large list should trigger indexing
        large_list = ["item"] * 100
        result, tool = manager._check_and_replace(large_list, "test_source")
        assert tool is not None

        mock_index.reset_mock()

        # Small list should not trigger indexing
        small_list = ["a", "b"]
        result, tool = manager._check_and_replace(small_list, "test_source")
        assert tool is None

    def test_none_passes_through(self):
        """None should pass through unchanged."""
        manager = EphemeralRagManager("test", "cell", threshold=100)
        result, tool = manager._check_and_replace(None, "test_source")
        assert result is None
        assert tool is None

    def test_empty_passes_through(self):
        """Empty values should pass through unchanged."""
        manager = EphemeralRagManager("test", "cell", threshold=100)

        result, tool = manager._check_and_replace("", "test")
        assert result == ""
        assert tool is None

        result, tool = manager._check_and_replace({}, "test")
        assert result == {}
        assert tool is None

        result, tool = manager._check_and_replace([], "test")
        assert result == []
        assert tool is None


# =============================================================================
# EphemeralRagManager Placeholder Tests (via _index_and_replace output)
# =============================================================================

class TestEphemeralRagManagerPlaceholder:
    """Tests for placeholder text in replacements."""

    @patch.object(EphemeralRagManager, '_embed_chunks')
    @patch.object(EphemeralRagManager, '_insert_chunks')
    def test_placeholder_in_replacement(self, mock_insert, mock_embed):
        """Replacement should contain a placeholder with useful info."""
        mock_embed.return_value = [[0.1] * 384]  # Fake embedding
        mock_insert.return_value = None

        manager = EphemeralRagManager("test", "cell", threshold=100)
        large_content = "x" * 200

        placeholder, tool_name = manager._index_and_replace(large_content, "test_source", "string")

        # Placeholder should mention the tool
        assert tool_name in placeholder
        # Placeholder should mention it's large/indexed
        assert "search" in placeholder.lower() or "indexed" in placeholder.lower()


# =============================================================================
# EphemeralRagManager Tool Name Generation Tests
# =============================================================================

class TestEphemeralRagManagerToolName:
    """Tests for search tool name generation."""

    def test_tool_name_from_simple_source(self):
        """Simple source should produce clean tool name."""
        manager = EphemeralRagManager("test", "cell")
        name = manager._generate_tool_name("document")

        assert name.startswith("search_")
        assert "document" in name

    def test_tool_name_sanitizes_dots(self):
        """Dots in source path should be converted to underscores."""
        manager = EphemeralRagManager("test", "cell")
        name = manager._generate_tool_name("input.nested.data")

        assert "." not in name
        assert "input" in name or "nested" in name or "data" in name

    def test_tool_name_sanitizes_special_chars(self):
        """Special characters should be removed/converted."""
        manager = EphemeralRagManager("test", "cell")
        name = manager._generate_tool_name("tool:sql_data")

        # Should be a valid Python identifier
        assert name.isidentifier()

    def test_tool_name_handles_duplicates(self):
        """Duplicate sources should get unique names."""
        manager = EphemeralRagManager("test", "cell")

        # First call
        name1 = manager._generate_tool_name("data")
        # Simulate the name being used
        manager._used_tool_names = {name1}
        # Second call with same source
        name2 = manager._generate_tool_name("data")

        assert name1 != name2


# =============================================================================
# EphemeralRagManager Template Processing Tests (Mocked)
# =============================================================================

class TestEphemeralRagManagerTemplateProcessing:
    """Tests for template data processing (with mocked indexing)."""

    @patch.object(EphemeralRagManager, '_index_and_replace')
    def test_process_template_small_values_unchanged(self, mock_index):
        """Small template values should pass through unchanged."""
        manager = EphemeralRagManager("test", "cell", threshold=1000)

        data = {
            "input": {"name": "Alice", "id": 123},
            "state": {"counter": 5}
        }

        processed, tool_names = manager.process_template_data(data)

        assert processed == data
        assert len(tool_names) == 0
        mock_index.assert_not_called()

    @patch.object(EphemeralRagManager, '_index_and_replace')
    def test_process_template_large_string_replaced(self, mock_index):
        """Large string in template should be replaced with placeholder."""
        mock_index.return_value = ("eph_test123", 50)

        manager = EphemeralRagManager("test", "cell", threshold=100)

        data = {
            "input": {
                "small": "tiny",
                "large": "x" * 200  # Over threshold
            }
        }

        processed, tool_names = manager.process_template_data(data)

        # Small value unchanged
        assert processed["input"]["small"] == "tiny"
        # Large value replaced with placeholder
        assert "x" * 200 not in str(processed["input"]["large"])
        assert len(tool_names) == 1
        mock_index.assert_called_once()

    @patch.object(EphemeralRagManager, '_index_and_replace')
    def test_process_template_nested_large_value(self, mock_index):
        """Large value in nested structure should be found and replaced."""
        mock_index.return_value = ("eph_nested", 30)

        manager = EphemeralRagManager("test", "cell", threshold=100)

        data = {
            "input": {
                "level1": {
                    "level2": {
                        "huge": "y" * 200
                    }
                }
            }
        }

        processed, tool_names = manager.process_template_data(data)

        assert len(tool_names) == 1
        mock_index.assert_called_once()

    @patch.object(EphemeralRagManager, '_index_and_replace')
    def test_process_template_multiple_large_values(self, mock_index):
        """Multiple large values should each get their own tool."""
        mock_index.side_effect = [("eph_1", 10), ("eph_2", 20)]

        manager = EphemeralRagManager("test", "cell", threshold=100)

        data = {
            "doc1": "a" * 200,
            "doc2": "b" * 200,
            "small": "ok"
        }

        processed, tool_names = manager.process_template_data(data)

        assert processed["small"] == "ok"
        assert len(tool_names) == 2
        assert mock_index.call_count == 2


# =============================================================================
# EphemeralRagManager Tool Result Processing Tests (Mocked)
# =============================================================================

class TestEphemeralRagManagerToolResultProcessing:
    """Tests for tool result processing (with mocked indexing)."""

    @patch.object(EphemeralRagManager, '_index_and_replace')
    def test_process_small_tool_result_unchanged(self, mock_index):
        """Small tool results should pass through unchanged."""
        manager = EphemeralRagManager("test", "cell", threshold=1000)

        result = '{"status": "success", "data": [1, 2, 3]}'

        processed, tool_name = manager.process_tool_result("sql_data", result)

        assert processed == result
        assert tool_name is None
        mock_index.assert_not_called()

    @patch.object(EphemeralRagManager, '_index_and_replace')
    def test_process_large_tool_result_indexed(self, mock_index):
        """Large tool results should be indexed."""
        # _index_and_replace returns (placeholder, tool_name)
        mock_index.return_value = ("[placeholder]", "search_sql_data_result")

        manager = EphemeralRagManager("test", "cell", threshold=100)

        large_result = '{"rows": ' + '"row_data",' * 100 + '}'

        processed, tool_name = manager.process_tool_result("sql_data", large_result)

        assert tool_name is not None
        assert "search" in tool_name
        mock_index.assert_called_once()

    @patch.object(EphemeralRagManager, '_embed_chunks')
    @patch.object(EphemeralRagManager, '_insert_chunks')
    def test_tool_result_source_includes_tool_name(self, mock_insert, mock_embed):
        """Indexed tool result should track the source tool name."""
        mock_embed.return_value = [[0.1] * 384]
        mock_insert.return_value = None

        manager = EphemeralRagManager("test", "cell", threshold=100)

        manager.process_tool_result("custom_tool", "x" * 200)

        # Check that the source tracking mentions the tool
        stats = manager.get_stats()
        assert stats["replacements_count"] == 1


# =============================================================================
# EphemeralRagManager Stats Tests
# =============================================================================

class TestEphemeralRagManagerStats:
    """Tests for statistics tracking."""

    def test_initial_stats_zeroed(self):
        """Fresh manager should have zero stats."""
        manager = EphemeralRagManager("test", "cell")
        stats = manager.get_stats()

        assert stats["replacements_count"] == 0
        assert stats["total_chunks_indexed"] == 0
        assert stats["total_chars_indexed"] == 0

    @patch.object(EphemeralRagManager, '_embed_chunks')
    @patch.object(EphemeralRagManager, '_insert_chunks')
    def test_stats_updated_after_indexing(self, mock_insert, mock_embed):
        """Stats should update after indexing content."""
        mock_embed.return_value = [[0.1] * 384]
        mock_insert.return_value = None

        manager = EphemeralRagManager("test", "cell", threshold=100)
        manager.process_template_data({"large": "x" * 200})

        stats = manager.get_stats()
        assert stats["replacements_count"] == 1
        assert stats["total_chunks_indexed"] >= 1


# =============================================================================
# EphemeralRagManager Tool Retrieval Tests
# =============================================================================

class TestEphemeralRagManagerToolRetrieval:
    """Tests for search tool retrieval."""

    @patch.object(EphemeralRagManager, '_embed_chunks')
    @patch.object(EphemeralRagManager, '_insert_chunks')
    def test_get_tool_returns_callable(self, mock_insert, mock_embed):
        """get_tool should return a callable function."""
        mock_embed.return_value = [[0.1] * 384]
        mock_insert.return_value = None

        manager = EphemeralRagManager("test", "cell", threshold=100)
        manager.process_template_data({"big": "x" * 200})

        tools = manager.get_all_tools()
        assert len(tools) == 1

        tool_name = list(tools.keys())[0]
        tool_fn = tools[tool_name]
        assert callable(tool_fn)

    @patch.object(EphemeralRagManager, '_embed_chunks')
    @patch.object(EphemeralRagManager, '_insert_chunks')
    def test_get_tool_by_name(self, mock_insert, mock_embed):
        """Should be able to retrieve specific tool by name."""
        mock_embed.return_value = [[0.1] * 384]
        mock_insert.return_value = None

        manager = EphemeralRagManager("test", "cell", threshold=100)
        _, tool_names = manager.process_template_data({"big": "x" * 200})

        tool_name = tool_names[0]
        tool = manager.get_tool(tool_name)

        assert tool is not None
        assert callable(tool)

    def test_get_nonexistent_tool_returns_none(self):
        """Requesting non-existent tool should return None."""
        manager = EphemeralRagManager("test", "cell")

        tool = manager.get_tool("nonexistent_tool")
        assert tool is None


# =============================================================================
# EphemeralRagManager Cleanup Tests
# =============================================================================

class TestEphemeralRagManagerCleanup:
    """Tests for cleanup behavior."""

    @patch.object(EphemeralRagManager, '_embed_chunks')
    @patch.object(EphemeralRagManager, '_insert_chunks')
    def test_cleanup_clears_indexes(self, mock_insert, mock_embed):
        """Cleanup should clear all tracking state."""
        mock_embed.return_value = [[0.1] * 384]
        mock_insert.return_value = None

        manager = EphemeralRagManager("test", "cell", threshold=100)

        # Mock the db to avoid actual ClickHouse calls
        manager._db = MagicMock()

        manager.process_template_data({"a": "x" * 200, "b": "y" * 200})

        # Verify we have replacements
        assert len(manager.replacements) == 2

        manager.cleanup()

        # Should clear all state
        assert len(manager.replacements) == 0

    def test_cleanup_clears_internal_state(self):
        """Cleanup should clear internal tracking."""
        manager = EphemeralRagManager("test", "cell")

        # Mock the db to avoid actual ClickHouse calls
        manager._db = MagicMock()

        # Manually add some state (replacements is a dict, not list)
        manager.replacements = {"test_rag_id": MagicMock()}
        manager._tools = {"search_test": lambda: None}

        manager.cleanup()

        assert len(manager.replacements) == 0
        assert len(manager._tools) == 0

    def test_cleanup_idempotent(self):
        """Calling cleanup multiple times should be safe."""
        manager = EphemeralRagManager("test", "cell")

        # Mock the db to avoid actual ClickHouse calls
        manager._db = MagicMock()

        # Should not raise
        manager.cleanup()
        manager.cleanup()
        manager.cleanup()


# =============================================================================
# is_ephemeral_rag_enabled Tests
# =============================================================================

class TestIsEphemeralRagEnabled:
    """Tests for the enabled check function."""

    @patch('lars.config.get_config')
    def test_enabled_when_config_true(self, mock_get_config):
        """Should return True when config.ephemeral_rag_enabled is True."""
        mock_cfg = MagicMock()
        mock_cfg.ephemeral_rag_enabled = True
        mock_get_config.return_value = mock_cfg

        assert is_ephemeral_rag_enabled() is True

    @patch('lars.config.get_config')
    def test_disabled_when_config_false(self, mock_get_config):
        """Should return False when config.ephemeral_rag_enabled is False."""
        mock_cfg = MagicMock()
        mock_cfg.ephemeral_rag_enabled = False
        mock_get_config.return_value = mock_cfg

        assert is_ephemeral_rag_enabled() is False


# =============================================================================
# Content Hash Deduplication Tests
# =============================================================================

class TestEphemeralRagManagerDeduplication:
    """Tests for content deduplication via hashing."""

    @patch.object(EphemeralRagManager, '_embed_chunks')
    @patch.object(EphemeralRagManager, '_insert_chunks')
    def test_identical_content_same_source_reused(self, mock_insert, mock_embed):
        """Same content from same source should reuse existing index."""
        mock_embed.return_value = [[0.1] * 384]
        mock_insert.return_value = None

        manager = EphemeralRagManager("test", "cell", threshold=100)
        large_content = "x" * 200

        # Process same content twice from same source path
        manager.process_template_data({"doc": large_content})
        manager.process_template_data({"doc": large_content})

        # Same source + same content = same rag_id = reuse existing
        # Only one index should be created
        assert manager.get_stats()["replacements_count"] == 1

    @patch.object(EphemeralRagManager, '_embed_chunks')
    @patch.object(EphemeralRagManager, '_insert_chunks')
    def test_identical_content_different_sources_both_indexed(self, mock_insert, mock_embed):
        """Same content from different sources creates separate indexes (for distinct tool names)."""
        mock_embed.return_value = [[0.1] * 384]
        mock_insert.return_value = None

        manager = EphemeralRagManager("test", "cell", threshold=100)
        large_content = "x" * 200

        # Process same content from different source paths
        # This creates separate indexes so each has its own search tool
        manager.process_template_data({"doc1": large_content})
        manager.process_template_data({"doc2": large_content})

        # Different sources = different rag_ids = separate indexes
        assert manager.get_stats()["replacements_count"] == 2

    @patch.object(EphemeralRagManager, '_embed_chunks')
    @patch.object(EphemeralRagManager, '_insert_chunks')
    def test_different_content_both_indexed(self, mock_insert, mock_embed):
        """Different content should each be indexed."""
        mock_embed.return_value = [[0.1] * 384]
        mock_insert.return_value = None

        manager = EphemeralRagManager("test", "cell", threshold=100)

        manager.process_template_data({"a": "x" * 200})
        manager.process_template_data({"b": "y" * 200})

        assert manager.get_stats()["replacements_count"] == 2
