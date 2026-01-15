"""
Comprehensive tests for Cascade Pydantic model validation.

These tests validate the cascade configuration models without requiring
any LLM calls or external dependencies. They ensure:
1. Valid configurations parse correctly
2. Invalid configurations raise ValidationError with helpful messages
3. Optional fields have correct defaults
4. Nested configs (candidates, wards, context) parse correctly
5. Edge cases are handled appropriately

These tests can be used as part of the cascade execution process
to validate cascade definitions (JSON and YAML) before running.
"""
import pytest
from pydantic import ValidationError

from rvbbit.cascade import (
    # Core models
    CascadeConfig,
    CellConfig,
    RuleConfig,
    load_cascade_config,
    # Context system
    ContextConfig,
    ContextSourceConfig,
    # Candidates
    CandidatesConfig,
    ReforgeConfig,
    ModelConfig,
    CostAwareEvaluation,
    ParetoFrontier,
    # Validation/Wards
    WardConfig,
    WardsConfig,
    # Human-in-the-loop
    HumanInputConfig,
    HumanInputType,
    HumanInputOption,
    HumanSoundingEvalConfig,
    HumanEvalPresentation,
    HumanEvalSelectionMode,
    # Advanced features
    SubCascadeRef,
    HandoffConfig,
    AsyncCascadeRef,
    RagConfig,
    TokenBudgetConfig,
    ToolCachingConfig,
    ToolCachePolicy,
    OutputExtractionConfig,
    AudibleConfig,
    CalloutsConfig,
    # Inline validators
    InlineValidatorConfig,
)


# =============================================================================
# MINIMAL VALID CASCADES
# =============================================================================

class TestMinimalCascade:
    """Test minimal valid cascade configurations."""

    def test_minimal_cascade(self):
        """The absolute minimum valid cascade."""
        config = CascadeConfig(
            cascade_id="minimal",
            cells=[
                CellConfig(
                    name="single_cell",
                    instructions="Do something."
                )
            ]
        )
        assert config.cascade_id == "minimal"
        assert len(config.cells) == 1
        assert config.cells[0].name == "single_cell"

    def test_minimal_cascade_from_dict(self):
        """Parse from dict (as would come from JSON)."""
        data = {
            "cascade_id": "from_dict",
            "cells": [
                {"name": "cell1", "instructions": "Do work."}
            ]
        }
        config = CascadeConfig(**data)
        assert config.cascade_id == "from_dict"
        assert config.cells[0].instructions == "Do work."

    def test_two_cell_with_handoff(self):
        """Basic two-cell cascade with handoff."""
        config = CascadeConfig(
            cascade_id="two_cell",
            cells=[
                CellConfig(
                    name="first",
                    instructions="Cell 1",
                    handoffs=["second"]
                ),
                CellConfig(
                    name="second",
                    instructions="Cell 2",
                    context=ContextConfig(from_=["previous"])
                )
            ]
        )
        assert len(config.cells) == 2
        assert config.cells[0].handoffs == ["second"]


# =============================================================================
# CELL CONFIG VALIDATION
# =============================================================================

class TestCellConfig:
    """Test CellConfig validation and defaults."""

    def test_cell_defaults(self):
        """Verify all default values are set correctly."""
        cell = CellConfig(name="test", instructions="Test")

        # Tackle defaults to empty list
        assert cell.skills == []

        # Manifest context defaults
        assert cell.manifest_context == "current"

        # Model override defaults to None
        assert cell.model is None

        # Use native tools defaults to False
        assert cell.use_native_tools is False

        # Rules defaults to empty RuleConfig
        assert isinstance(cell.rules, RuleConfig)
        assert cell.rules.max_turns is None

        # Collections default to empty
        assert cell.handoffs == []
        assert cell.sub_cascades == []
        assert cell.async_cascades == []

        # Optional configs default to None
        assert cell.candidates is None
        assert cell.output_schema is None
        assert cell.wards is None
        assert cell.rag is None
        assert cell.context is None
        assert cell.human_input is None
        assert cell.audibles is None
        assert cell.callouts is None

    def test_cell_with_tools(self):
        """Cell with skills (tools) specified."""
        cell = CellConfig(
            name="with_tools",
            instructions="Use tools",
            skills=["linux_shell", "run_code", "smart_sql_run"]
        )
        assert cell.skills == ["linux_shell", "run_code", "smart_sql_run"]

    def test_cell_with_manifest_skills(self):
        """Cell using manifest (Quartermaster) for tool selection."""
        cell = CellConfig(
            name="with_manifest",
            instructions="Auto-select tools",
            skills="manifest"
        )
        assert cell.skills == "manifest"

    def test_cell_with_model_override(self):
        """Cell overriding the default model."""
        cell = CellConfig(
            name="custom_model",
            instructions="Use Claude",
            model="anthropic/claude-sonnet-4"
        )
        assert cell.model == "anthropic/claude-sonnet-4"

    def test_handoffs_as_strings(self):
        """Handoffs specified as simple strings."""
        cell = CellConfig(
            name="router",
            instructions="Route to next cell",
            handoffs=["cell_a", "cell_b", "cell_c"]
        )
        assert cell.handoffs == ["cell_a", "cell_b", "cell_c"]

    def test_handoffs_as_configs(self):
        """Handoffs with HandoffConfig for descriptions."""
        cell = CellConfig(
            name="router",
            instructions="Route",
            handoffs=[
                HandoffConfig(target="success", description="When task succeeds"),
                HandoffConfig(target="failure", description="When task fails"),
            ]
        )
        assert len(cell.handoffs) == 2
        assert cell.handoffs[0].target == "success"
        assert cell.handoffs[0].description == "When task succeeds"


# =============================================================================
# RULES CONFIG VALIDATION
# =============================================================================

class TestRuleConfig:
    """Test RuleConfig for cell execution rules."""

    def test_rule_defaults(self):
        """All rule values default to None/False."""
        rules = RuleConfig()
        assert rules.max_turns is None
        assert rules.max_attempts is None
        assert rules.loop_until is None
        assert rules.loop_until_prompt is None
        assert rules.loop_until_silent is False
        assert rules.retry_instructions is None
        assert rules.turn_prompt is None

    def test_max_turns(self):
        """Set max turns for cell execution."""
        rules = RuleConfig(max_turns=5)
        assert rules.max_turns == 5

    def test_loop_until_validation(self):
        """Loop until a validator passes."""
        rules = RuleConfig(
            loop_until="format_validator",
            loop_until_prompt="Ensure output is valid JSON",
            max_attempts=3
        )
        assert rules.loop_until == "format_validator"
        assert rules.max_attempts == 3

    def test_turn_prompt_jinja(self):
        """Turn prompt supports Jinja2 templating."""
        rules = RuleConfig(
            turn_prompt="This is turn {{ turn_number }}. Previous: {{ previous_output }}"
        )
        assert "{{ turn_number }}" in rules.turn_prompt

    def test_cell_with_rules(self):
        """Cell with full rules configuration."""
        cell = CellConfig(
            name="with_rules",
            instructions="Iterative cell",
            rules=RuleConfig(
                max_turns=10,
                max_attempts=3,
                loop_until="quality_check",
                retry_instructions="Please try again with better quality."
            )
        )
        assert cell.rules.max_turns == 10
        assert cell.rules.loop_until == "quality_check"


# =============================================================================
# CONTEXT SYSTEM VALIDATION
# =============================================================================

class TestContextConfig:
    """Test selective context configuration."""

    def test_context_from_previous(self):
        """Context from previous cell only."""
        # Note: Must use dict syntax for 'from' alias to work
        ctx = ContextConfig(**{"from": ["previous"]})
        assert ctx.from_ == ["previous"]
        assert ctx.include_input is True

    def test_context_from_all(self):
        """Explicit snowball - all prior context."""
        ctx = ContextConfig(**{"from": ["all"]})
        assert ctx.from_ == ["all"]

    def test_context_from_specific_cells(self):
        """Context from specific named cells."""
        ctx = ContextConfig(**{"from": ["cell_a", "cell_c"]})
        assert ctx.from_ == ["cell_a", "cell_c"]

    def test_context_with_exclusions(self):
        """All context except specific cells."""
        ctx = ContextConfig(**{
            "from": ["all"],
            "exclude": ["verbose_debug", "internal_processing"]
        })
        assert "verbose_debug" in ctx.exclude

    def test_context_no_input(self):
        """Disable original input injection."""
        ctx = ContextConfig(**{"from": ["previous"], "include_input": False})
        assert ctx.include_input is False

    def test_context_source_config(self):
        """Detailed context source configuration."""
        source = ContextSourceConfig(
            cell="generate_chart",
            include=["images", "output"],
            images_filter="last",
            as_role="user"
        )
        assert source.cell == "generate_chart"
        assert "images" in source.include
        assert source.images_filter == "last"

    def test_context_mixed_sources(self):
        """Mix of string and detailed source configs."""
        ctx = ContextConfig(**{"from": [
            "first",
            {"cell": "chart_gen", "include": ["images"]},
            "previous"
        ]})
        assert len(ctx.from_) == 3
        assert ctx.from_[0] == "first"
        assert isinstance(ctx.from_[1], ContextSourceConfig)

    def test_context_from_json_alias(self):
        """The 'from' alias works in JSON parsing."""
        data = {
            "from": ["all"],
            "exclude": ["cell_x"],
            "include_input": False
        }
        ctx = ContextConfig(**data)
        assert ctx.from_ == ["all"]
        assert ctx.include_input is False


# =============================================================================
# CANDIDATES (Tree of Thought) VALIDATION
# =============================================================================

class TestCandidatesConfig:
    """Test candidates/Tree-of-Thought configuration."""

    def test_basic_candidates(self):
        """Basic candidates with evaluator."""
        candidates = CandidatesConfig(
            factor=3,
            evaluator_instructions="Pick the most creative response."
        )
        assert candidates.factor == 3
        assert candidates.mutate is True  # Default
        assert candidates.max_parallel == 3  # Default

    def test_candidates_defaults(self):
        """Verify candidates defaults."""
        candidates = CandidatesConfig()
        assert candidates.factor == 1
        assert candidates.max_parallel == 3
        assert candidates.evaluator_instructions is None
        assert candidates.mutate is True
        assert candidates.mutation_mode == "rewrite"
        assert candidates.mutations is None

    def test_candidates_with_mutations(self):
        """Custom mutations for prompt variation."""
        candidates = CandidatesConfig(
            factor=5,
            mutate=True,
            mutation_mode="augment",
            mutations=[
                "Think step by step.",
                "Consider multiple perspectives.",
                "Be concise and direct."
            ]
        )
        assert candidates.mutation_mode == "augment"
        assert len(candidates.mutations) == 3

    def test_candidates_with_validator(self):
        """Pre-evaluation validator to filter candidates."""
        candidates = CandidatesConfig(
            factor=5,
            validator="code_executes",
            evaluator_instructions="Pick the cleanest code that runs."
        )
        assert candidates.validator == "code_executes"

    def test_reforge_config(self):
        """Reforge (iterative refinement) configuration."""
        reforge = ReforgeConfig(
            steps=3,
            honing_prompt="Make it better: clearer, more concise, more actionable.",
            factor_per_step=2,
            mutate=True
        )
        assert reforge.steps == 3
        assert reforge.factor_per_step == 2

    def test_candidates_with_reforge(self):
        """Candidates with reforge loop."""
        candidates = CandidatesConfig(
            factor=3,
            evaluator_instructions="Pick best approach.",
            reforge=ReforgeConfig(
                steps=2,
                honing_prompt="Refine and polish."
            )
        )
        assert candidates.reforge.steps == 2

    def test_multi_model_candidates_list(self):
        """Multi-model candidates with list of models."""
        candidates = CandidatesConfig(
            factor=6,
            models=["openai/gpt-4o", "anthropic/claude-sonnet-4", "google/gemini-2.5-flash"],
            model_strategy="round_robin"
        )
        assert len(candidates.models) == 3
        assert candidates.model_strategy == "round_robin"

    def test_multi_model_candidates_dict(self):
        """Multi-model candidates with per-model config."""
        candidates = CandidatesConfig(
            models={
                "openai/gpt-4o": ModelConfig(factor=2, temperature=0.7),
                "anthropic/claude-sonnet-4": ModelConfig(factor=3, temperature=0.5),
            },
            model_strategy="weighted"
        )
        assert candidates.models["openai/gpt-4o"].factor == 2
        assert candidates.models["anthropic/claude-sonnet-4"].temperature == 0.5

    def test_cost_aware_evaluation(self):
        """Cost-aware evaluation settings."""
        cost_aware = CostAwareEvaluation(
            enabled=True,
            quality_weight=0.6,
            cost_weight=0.4,
            show_costs_to_evaluator=True
        )
        assert cost_aware.quality_weight == 0.6
        assert cost_aware.cost_normalization == "min_max"  # Default

    def test_pareto_frontier(self):
        """Pareto frontier configuration."""
        pareto = ParetoFrontier(
            enabled=True,
            policy="balanced",
            show_frontier=True
        )
        assert pareto.policy == "balanced"

    def test_human_evaluation(self):
        """Human evaluation of candidates."""
        candidates = CandidatesConfig(
            factor=3,
            evaluator="human",
            human_eval=HumanSoundingEvalConfig(
                presentation=HumanEvalPresentation.SIDE_BY_SIDE,
                selection_mode=HumanEvalSelectionMode.PICK_ONE,
                require_reasoning=True
            )
        )
        assert candidates.evaluator == "human"
        assert candidates.human_eval.require_reasoning is True


# =============================================================================
# WARDS (Validation) CONFIG
# =============================================================================

class TestWardsConfig:
    """Test ward (validation) configuration."""

    def test_single_ward(self):
        """Single validator ward."""
        ward = WardConfig(
            validator="json_valid",
            mode="blocking"
        )
        assert ward.validator == "json_valid"
        assert ward.mode == "blocking"
        assert ward.max_attempts == 1

    def test_retry_ward(self):
        """Ward with retry mode."""
        ward = WardConfig(
            validator="passes_tests",
            mode="retry",
            max_attempts=3
        )
        assert ward.mode == "retry"
        assert ward.max_attempts == 3

    def test_advisory_ward(self):
        """Advisory ward (warns but continues)."""
        ward = WardConfig(
            validator="style_check",
            mode="advisory"
        )
        assert ward.mode == "advisory"

    def test_wards_config(self):
        """Full wards configuration with pre/post."""
        wards = WardsConfig(
            pre=[WardConfig(validator="input_sanitizer", mode="blocking")],
            post=[
                WardConfig(validator="json_valid", mode="blocking"),
                WardConfig(validator="quality_check", mode="retry", max_attempts=2)
            ],
            turn=[WardConfig(validator="safety_check", mode="blocking")]
        )
        assert len(wards.pre) == 1
        assert len(wards.post) == 2
        assert len(wards.turn) == 1

    def test_cell_with_wards(self):
        """Cell with ward configuration."""
        cell = CellConfig(
            name="validated",
            instructions="Generate JSON",
            wards=WardsConfig(
                post=[WardConfig(validator="json_valid", mode="retry", max_attempts=3)]
            )
        )
        assert cell.wards.post[0].validator == "json_valid"


# =============================================================================
# HUMAN INPUT CONFIG
# =============================================================================

class TestHumanInputConfig:
    """Test human-in-the-loop configuration."""

    def test_simple_confirmation(self):
        """Simple boolean human_input flag."""
        cell = CellConfig(
            name="needs_approval",
            instructions="Do something",
            human_input=True
        )
        assert cell.human_input is True

    def test_detailed_human_input(self):
        """Detailed HumanInputConfig."""
        config = HumanInputConfig(
            type=HumanInputType.CHOICE,
            prompt="Select the best option:",
            options=[
                HumanInputOption(label="Option A", value="a", description="First choice"),
                HumanInputOption(label="Option B", value="b", description="Second choice"),
            ],
            timeout_seconds=300,
            on_timeout="abort"
        )
        assert config.type == HumanInputType.CHOICE
        assert len(config.options) == 2
        assert config.timeout_seconds == 300

    def test_human_input_types(self):
        """All human input types are valid."""
        for input_type in HumanInputType:
            config = HumanInputConfig(type=input_type)
            assert config.type == input_type

    def test_rating_config(self):
        """Rating type configuration."""
        config = HumanInputConfig(
            type=HumanInputType.RATING,
            max_rating=10,
            rating_labels=["Terrible", "Poor", "Fair", "Good", "Great", "Excellent"]
        )
        assert config.max_rating == 10
        assert len(config.rating_labels) == 6

    def test_conditional_human_input(self):
        """Conditional human input with Jinja2."""
        config = HumanInputConfig(
            type=HumanInputType.CONFIRMATION,
            condition="{{ state.needs_review == true }}",
            default_value=True
        )
        assert "{{ state.needs_review" in config.condition


# =============================================================================
# RAG CONFIG
# =============================================================================

class TestRagConfig:
    """Test RAG (Retrieval Augmented Generation) configuration."""

    def test_minimal_rag(self):
        """Minimal RAG configuration."""
        rag = RagConfig(directory="docs")
        assert rag.directory == "docs"
        assert rag.recursive is False
        assert rag.chunk_chars == 1200
        assert rag.chunk_overlap == 200

    def test_rag_with_filters(self):
        """RAG with custom include/exclude patterns."""
        rag = RagConfig(
            directory="knowledge_base",
            recursive=True,
            include=["*.md", "*.txt"],
            exclude=["drafts/**", "*.tmp"]
        )
        assert rag.recursive is True
        assert "*.md" in rag.include
        assert "drafts/**" in rag.exclude

    def test_rag_custom_chunking(self):
        """Custom chunking parameters."""
        rag = RagConfig(
            directory="large_docs",
            chunk_chars=2000,
            chunk_overlap=400
        )
        assert rag.chunk_chars == 2000
        assert rag.chunk_overlap == 400

    def test_cell_with_rag(self):
        """Cell with RAG configuration."""
        cell = CellConfig(
            name="rag_search",
            instructions="Search the documentation for {{ input.query }}",
            rag=RagConfig(directory="docs", recursive=True)
        )
        assert cell.rag.directory == "docs"


# =============================================================================
# TOKEN BUDGET CONFIG
# =============================================================================

class TestTokenBudgetConfig:
    """Test token budget configuration."""

    def test_token_budget_defaults(self):
        """Default token budget settings."""
        budget = TokenBudgetConfig()
        assert budget.max_total == 100000
        assert budget.reserve_for_output == 4000
        assert budget.strategy == "sliding_window"
        assert budget.warning_threshold == 0.8

    def test_custom_token_budget(self):
        """Custom token budget configuration."""
        budget = TokenBudgetConfig(
            max_total=50000,
            reserve_for_output=8000,
            strategy="prune_oldest",
            warning_threshold=0.9
        )
        assert budget.max_total == 50000
        assert budget.strategy == "prune_oldest"

    def test_cell_overrides(self):
        """Per-cell token budget overrides."""
        budget = TokenBudgetConfig(
            max_total=100000,
            cell_overrides={
                "synthesis": 50000,
                "quick_task": 10000
            }
        )
        assert budget.cell_overrides["synthesis"] == 50000


# =============================================================================
# TOOL CACHING CONFIG
# =============================================================================

class TestToolCachingConfig:
    """Test tool caching configuration."""

    def test_caching_disabled_by_default(self):
        """Caching is disabled by default."""
        caching = ToolCachingConfig()
        assert caching.enabled is False

    def test_enabled_caching(self):
        """Enable caching with defaults."""
        caching = ToolCachingConfig(enabled=True)
        assert caching.enabled is True
        assert caching.storage == "memory"
        assert caching.global_ttl == 3600

    def test_per_tool_policy(self):
        """Per-tool caching policies."""
        caching = ToolCachingConfig(
            enabled=True,
            tools={
                "smart_sql_run": ToolCachePolicy(
                    enabled=True,
                    ttl=7200,
                    key="sql_hash"
                ),
                "expensive_api": ToolCachePolicy(
                    enabled=True,
                    ttl=86400
                )
            }
        )
        assert caching.tools["smart_sql_run"].ttl == 7200
        assert caching.tools["smart_sql_run"].key == "sql_hash"


# =============================================================================
# OUTPUT EXTRACTION CONFIG
# =============================================================================

class TestOutputExtractionConfig:
    """Test output extraction configuration."""

    def test_basic_extraction(self):
        """Basic regex pattern extraction."""
        extraction = OutputExtractionConfig(
            pattern=r"<scratchpad>(.*?)</scratchpad>",
            store_as="reasoning"
        )
        assert extraction.pattern == r"<scratchpad>(.*?)</scratchpad>"
        assert extraction.store_as == "reasoning"
        assert extraction.required is False
        assert extraction.format == "text"

    def test_json_extraction(self):
        """Extract and parse as JSON."""
        extraction = OutputExtractionConfig(
            pattern=r"```json\n(.*?)\n```",
            store_as="structured_output",
            format="json",
            required=True
        )
        assert extraction.format == "json"
        assert extraction.required is True


# =============================================================================
# AUDIBLE CONFIG
# =============================================================================

class TestAudibleConfig:
    """Test audible (real-time feedback) configuration."""

    def test_audible_defaults(self):
        """Default audible settings."""
        audible = AudibleConfig()
        assert audible.enabled is True
        assert audible.budget == 3
        assert audible.allow_retry is True

    def test_custom_audible(self):
        """Custom audible configuration."""
        audible = AudibleConfig(
            enabled=True,
            budget=5,
            allow_retry=False,
            timeout_seconds=60
        )
        assert audible.budget == 5
        assert audible.timeout_seconds == 60


# =============================================================================
# CALLOUTS CONFIG
# =============================================================================

class TestCalloutsConfig:
    """Test callouts (semantic tagging) configuration."""

    def test_callout_shorthand(self):
        """String shorthand for callouts."""
        cell = CellConfig(
            name="tagged",
            instructions="Do work",
            callouts="Key Result"
        )
        assert cell.callouts == "Key Result"

    def test_callout_full_config(self):
        """Full CalloutsConfig."""
        callouts = CalloutsConfig(
            output="Research Summary for {{input.topic}}",
            messages="Finding {{turn}}",
            messages_filter="assistant_only"
        )
        assert "{{input.topic}}" in callouts.output
        assert callouts.messages_filter == "assistant_only"


# =============================================================================
# SUB-CASCADE AND ASYNC REFS
# =============================================================================

class TestSubCascadeRefs:
    """Test sub-cascade and async cascade references."""

    def test_sub_cascade_ref(self):
        """Sub-cascade reference configuration."""
        ref = SubCascadeRef(
            ref="child_cascade.json",
            input_map={"query": "parent_query"},
            context_in=True,
            context_out=True
        )
        assert ref.ref == "child_cascade.json"
        assert ref.input_map["query"] == "parent_query"

    def test_async_cascade_ref(self):
        """Async cascade reference configuration."""
        ref = AsyncCascadeRef(
            ref="background_task.json",
            trigger="on_start"
        )
        assert ref.trigger == "on_start"

    def test_cell_with_sub_cascades(self):
        """Cell with sub-cascade references."""
        cell = CellConfig(
            name="orchestrator",
            instructions="Coordinate sub-tasks",
            sub_cascades=[
                SubCascadeRef(ref="task_a.json"),
                SubCascadeRef(ref="task_b.json", context_in=False)
            ]
        )
        assert len(cell.sub_cascades) == 2


# =============================================================================
# FULL CASCADE CONFIG
# =============================================================================

class TestFullCascadeConfig:
    """Test complete cascade configurations."""

    def test_cascade_with_description(self):
        """Cascade with description."""
        config = CascadeConfig(
            cascade_id="documented",
            description="A well-documented cascade for testing.",
            cells=[CellConfig(name="main", instructions="Work")]
        )
        assert config.description == "A well-documented cascade for testing."

    def test_cascade_with_inputs_schema(self):
        """Cascade with inputs schema (for tool use)."""
        config = CascadeConfig(
            cascade_id="parameterized",
            description="Takes parameters",
            inputs_schema={
                "query": "The search query",
                "limit": "Maximum results to return"
            },
            cells=[CellConfig(
                name="search",
                instructions="Search for {{ input.query }} and return up to {{ input.limit }} results."
            )]
        )
        assert "query" in config.inputs_schema
        assert "limit" in config.inputs_schema

    def test_cascade_with_memory(self):
        """Cascade with persistent memory bank."""
        config = CascadeConfig(
            cascade_id="with_memory",
            memory="conversation_history",
            cells=[CellConfig(name="chat", instructions="Chat with context")]
        )
        assert config.memory == "conversation_history"

    def test_cascade_level_candidates(self):
        """Cascade-level candidates (Tree of Thought)."""
        config = CascadeConfig(
            cascade_id="parallel_approaches",
            candidates=CandidatesConfig(
                factor=3,
                evaluator_instructions="Pick the best overall approach."
            ),
            cells=[
                CellConfig(name="analyze", instructions="Analyze the problem"),
                CellConfig(name="solve", instructions="Solve it", context=ContextConfig(from_=["previous"]))
            ]
        )
        assert config.candidates.factor == 3

    def test_cascade_with_all_features(self):
        """Cascade exercising many features together."""
        config = CascadeConfig(
            cascade_id="feature_rich",
            description="Tests multiple features",
            inputs_schema={"topic": "Research topic"},
            memory="research_memory",
            token_budget=TokenBudgetConfig(max_total=50000),
            tool_caching=ToolCachingConfig(enabled=True),
            cells=[
                CellConfig(
                    name="research",
                    instructions="Research {{ input.topic }}",
                    skills=["smart_sql_run"],
                    rag=RagConfig(directory="knowledge"),
                    rules=RuleConfig(max_turns=5),
                    handoffs=["synthesize"]
                ),
                CellConfig(
                    name="synthesize",
                    instructions="Synthesize findings",
                    context=ContextConfig(from_=["research"]),
                    candidates=CandidatesConfig(
                        factor=3,
                        evaluator_instructions="Pick most insightful synthesis."
                    ),
                    wards=WardsConfig(
                        post=[WardConfig(validator="quality_check", mode="retry", max_attempts=2)]
                    ),
                    callouts="Final Research Synthesis"
                )
            ]
        )
        assert config.cascade_id == "feature_rich"
        assert config.token_budget.max_total == 50000
        assert config.cells[0].rag.directory == "knowledge"
        assert config.cells[1].candidates.factor == 3


# =============================================================================
# INLINE VALIDATORS
# =============================================================================

class TestInlineValidatorConfig:
    """Test inline validator configurations."""

    def test_minimal_inline_validator(self):
        """Inline validator with just instructions."""
        config = InlineValidatorConfig(
            instructions="Return {\"valid\": true, \"reason\": \"Test passed\"}"
        )
        assert config.instructions == 'Return {"valid": true, "reason": "Test passed"}'
        assert config.model is None  # Uses default
        assert config.max_turns == 1

    def test_inline_validator_with_model(self):
        """Inline validator with custom model."""
        config = InlineValidatorConfig(
            instructions="Check if output is valid JSON.",
            model="openai/gpt-4o-mini"
        )
        assert config.model == "openai/gpt-4o-mini"

    def test_inline_validator_with_max_turns(self):
        """Inline validator with multiple turns allowed."""
        config = InlineValidatorConfig(
            instructions="Validate thoroughly, can use tools if needed.",
            max_turns=3
        )
        assert config.max_turns == 3

    def test_cascade_with_inline_validators(self):
        """Cascade with validators defined inline."""
        config = CascadeConfig(
            cascade_id="with_inline_validators",
            validators={
                "check_question": InlineValidatorConfig(
                    instructions="Check if a question was formulated."
                ),
                "check_sql": InlineValidatorConfig(
                    instructions="Check if SQL query was executed.",
                    model="google/gemini-2.5-flash-lite"
                )
            },
            cells=[
                CellConfig(
                    name="discover",
                    instructions="Find an interesting question.",
                    rules=RuleConfig(max_turns=3, loop_until="check_question")
                ),
                CellConfig(
                    name="query",
                    instructions="Execute SQL.",
                    context=ContextConfig(from_=["previous"]),
                    rules=RuleConfig(max_turns=2, loop_until="check_sql")
                )
            ]
        )
        assert config.validators is not None
        assert "check_question" in config.validators
        assert "check_sql" in config.validators
        assert config.validators["check_sql"].model == "google/gemini-2.5-flash-lite"

    def test_cascade_validators_with_jinja(self):
        """Inline validators support Jinja2 templates."""
        config = CascadeConfig(
            cascade_id="jinja_validators",
            validators={
                "validate_output": InlineValidatorConfig(
                    instructions="""
                    Check if this output is valid:
                    {{ input.content }}

                    Original input: {{ input.original_input }}

                    Return JSON: {"valid": true/false, "reason": "..."}
                    """
                )
            },
            cells=[
                CellConfig(
                    name="work",
                    instructions="Do something",
                    rules=RuleConfig(loop_until="validate_output")
                )
            ]
        )
        assert "{{ input.content }}" in config.validators["validate_output"].instructions

    def test_load_cascade_with_inline_validators(self):
        """Load a cascade file that uses inline validators."""
        import os
        test_file = "examples/sql_chart_gen_analysis_full.yaml"
        if not os.path.exists(test_file):
            pytest.skip(f"Example file not found: {test_file}")

        # Load the actual sql_chart_gen_analysis_full.yaml
        config = load_cascade_config(test_file)
        assert config.validators is not None
        assert "question_formulated" in config.validators
        assert "schema_discovered" in config.validators
        assert "query_executed" in config.validators
        assert "analysis_complete" in config.validators
        assert "chart_rendered" in config.validators


# =============================================================================
# INVALID CONFIGURATIONS (Should Raise Errors)
# =============================================================================

class TestInvalidConfigurations:
    """Test that invalid configurations raise appropriate errors."""

    def test_missing_cascade_id(self):
        """Cascade without cascade_id should fail."""
        with pytest.raises(ValidationError) as exc_info:
            CascadeConfig(cells=[CellConfig(name="x", instructions="y")])
        assert "cascade_id" in str(exc_info.value)

    def test_missing_cells(self):
        """Cascade without cells should fail."""
        with pytest.raises(ValidationError) as exc_info:
            CascadeConfig(cascade_id="no_cells")
        assert "cells" in str(exc_info.value)

    def test_empty_cells(self):
        """Cascade with empty cells list is allowed by Pydantic.

        Note: While structurally valid, an empty cells cascade
        is semantically meaningless. Runtime validation could
        catch this if desired.
        """
        # Pydantic allows empty list - document this behavior
        config = CascadeConfig(cascade_id="empty_cells", cells=[])
        assert config.cells == []

    def test_cell_missing_name(self):
        """Cell without name should fail."""
        with pytest.raises(ValidationError) as exc_info:
            CellConfig(instructions="No name provided")
        assert "name" in str(exc_info.value)

    def test_cell_missing_instructions(self):
        """Cell without instructions should fail."""
        with pytest.raises(ValidationError) as exc_info:
            CellConfig(name="no_instructions")
        assert "instructions" in str(exc_info.value)

    def test_invalid_ward_mode(self):
        """Invalid ward mode should fail."""
        with pytest.raises(ValidationError) as exc_info:
            WardConfig(validator="test", mode="invalid_mode")
        assert "mode" in str(exc_info.value).lower() or "input" in str(exc_info.value).lower()

    def test_invalid_human_input_type(self):
        """Invalid human input type should fail."""
        with pytest.raises(ValidationError):
            HumanInputConfig(type="not_a_valid_type")

    def test_invalid_context_source_include(self):
        """Invalid include type in context source should fail."""
        with pytest.raises(ValidationError):
            ContextSourceConfig(
                cell="test",
                include=["invalid_type"]
            )

    def test_invalid_token_budget_strategy(self):
        """Invalid token budget strategy should fail."""
        with pytest.raises(ValidationError):
            TokenBudgetConfig(strategy="invalid_strategy")


# =============================================================================
# LOADING FROM JSON/YAML
# =============================================================================

class TestLoadingCascades:
    """Test loading cascades from dict/JSON structure."""

    def test_load_simple_json(self):
        """Load a simple JSON structure."""
        data = {
            "cascade_id": "simple",
            "cells": [
                {
                    "name": "main",
                    "instructions": "Do the thing."
                }
            ]
        }
        config = load_cascade_config(data)
        assert config.cascade_id == "simple"

    def test_load_complex_json(self):
        """Load a complex JSON structure with nested configs."""
        data = {
            "cascade_id": "complex",
            "cells": [
                {
                    "name": "research",
                    "instructions": "Research the topic",
                    "skills": ["smart_sql_run"],
                    "context": {
                        "from": ["all"],
                        "include_input": True
                    },
                    "candidates": {
                        "factor": 3,
                        "evaluator_instructions": "Pick best",
                        "reforge": {
                            "steps": 2,
                            "honing_prompt": "Improve it"
                        }
                    },
                    "wards": {
                        "post": [
                            {"validator": "quality", "mode": "retry", "max_attempts": 2}
                        ]
                    }
                }
            ]
        }
        config = load_cascade_config(data)
        assert config.cells[0].candidates.factor == 3
        assert config.cells[0].candidates.reforge.steps == 2
        assert config.cells[0].wards.post[0].mode == "retry"

    def test_load_preserves_jinja_templates(self):
        """Jinja2 templates in instructions are preserved."""
        data = {
            "cascade_id": "templated",
            "cells": [
                {
                    "name": "greet",
                    "instructions": "Hello {{ input.name }}! Your state is {{ state.mood }}."
                }
            ]
        }
        config = load_cascade_config(data)
        assert "{{ input.name }}" in config.cells[0].instructions
        assert "{{ state.mood }}" in config.cells[0].instructions


# =============================================================================
# VALIDATE CASCADE HELPER (for runtime use)
# =============================================================================

def validate_cascade(data: dict) -> tuple[bool, list[str]]:
    """
    Validate a cascade configuration dict.

    Returns:
        Tuple of (is_valid, list_of_error_messages)

    This function can be used at runtime to validate cascade definitions
    before execution.
    """
    errors = []
    try:
        CascadeConfig(**data)
        return True, []
    except ValidationError as e:
        for error in e.errors():
            loc = " -> ".join(str(x) for x in error["loc"])
            msg = f"{loc}: {error['msg']}"
            errors.append(msg)
        return False, errors


class TestValidateCascadeHelper:
    """Test the validate_cascade helper function."""

    def test_valid_cascade_returns_true(self):
        """Valid cascade returns (True, [])."""
        data = {
            "cascade_id": "valid",
            "cells": [{"name": "main", "instructions": "Work"}]
        }
        is_valid, errors = validate_cascade(data)
        assert is_valid is True
        assert errors == []

    def test_invalid_cascade_returns_errors(self):
        """Invalid cascade returns (False, [errors])."""
        data = {
            "cascade_id": "invalid",
            # Missing cells
        }
        is_valid, errors = validate_cascade(data)
        assert is_valid is False
        assert len(errors) > 0
        assert any("cells" in e.lower() for e in errors)

    def test_multiple_errors_collected(self):
        """Multiple validation errors are collected."""
        data = {
            # Missing cascade_id
            "cells": [
                {"name": "incomplete"}  # Missing instructions
            ]
        }
        is_valid, errors = validate_cascade(data)
        assert is_valid is False
        assert len(errors) >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
