"""
Comprehensive tests for Cascade Pydantic model validation.

These tests validate the cascade configuration models without requiring
any LLM calls or external dependencies. They ensure:
1. Valid configurations parse correctly
2. Invalid configurations raise ValidationError with helpful messages
3. Optional fields have correct defaults
4. Nested configs (soundings, wards, context) parse correctly
5. Edge cases are handled appropriately

These tests can be used as part of the cascade execution process
to validate cascade definitions (JSON and YAML) before running.
"""
import pytest
from pydantic import ValidationError

from windlass.cascade import (
    # Core models
    CascadeConfig,
    PhaseConfig,
    RuleConfig,
    load_cascade_config,
    # Context system
    ContextConfig,
    ContextSourceConfig,
    # Soundings
    SoundingsConfig,
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
            phases=[
                PhaseConfig(
                    name="single_phase",
                    instructions="Do something."
                )
            ]
        )
        assert config.cascade_id == "minimal"
        assert len(config.phases) == 1
        assert config.phases[0].name == "single_phase"

    def test_minimal_cascade_from_dict(self):
        """Parse from dict (as would come from JSON)."""
        data = {
            "cascade_id": "from_dict",
            "phases": [
                {"name": "phase1", "instructions": "Do work."}
            ]
        }
        config = CascadeConfig(**data)
        assert config.cascade_id == "from_dict"
        assert config.phases[0].instructions == "Do work."

    def test_two_phase_with_handoff(self):
        """Basic two-phase cascade with handoff."""
        config = CascadeConfig(
            cascade_id="two_phase",
            phases=[
                PhaseConfig(
                    name="first",
                    instructions="Phase 1",
                    handoffs=["second"]
                ),
                PhaseConfig(
                    name="second",
                    instructions="Phase 2",
                    context=ContextConfig(from_=["previous"])
                )
            ]
        )
        assert len(config.phases) == 2
        assert config.phases[0].handoffs == ["second"]


# =============================================================================
# PHASE CONFIG VALIDATION
# =============================================================================

class TestPhaseConfig:
    """Test PhaseConfig validation and defaults."""

    def test_phase_defaults(self):
        """Verify all default values are set correctly."""
        phase = PhaseConfig(name="test", instructions="Test")

        # Tackle defaults to empty list
        assert phase.tackle == []

        # Manifest context defaults
        assert phase.manifest_context == "current"

        # Model override defaults to None
        assert phase.model is None

        # Use native tools defaults to False
        assert phase.use_native_tools is False

        # Rules defaults to empty RuleConfig
        assert isinstance(phase.rules, RuleConfig)
        assert phase.rules.max_turns is None

        # Collections default to empty
        assert phase.handoffs == []
        assert phase.sub_cascades == []
        assert phase.async_cascades == []

        # Optional configs default to None
        assert phase.soundings is None
        assert phase.output_schema is None
        assert phase.wards is None
        assert phase.rag is None
        assert phase.context is None
        assert phase.human_input is None
        assert phase.audibles is None
        assert phase.callouts is None

    def test_phase_with_tools(self):
        """Phase with tackle (tools) specified."""
        phase = PhaseConfig(
            name="with_tools",
            instructions="Use tools",
            tackle=["linux_shell", "run_code", "smart_sql_run"]
        )
        assert phase.tackle == ["linux_shell", "run_code", "smart_sql_run"]

    def test_phase_with_manifest_tackle(self):
        """Phase using manifest (Quartermaster) for tool selection."""
        phase = PhaseConfig(
            name="with_manifest",
            instructions="Auto-select tools",
            tackle="manifest"
        )
        assert phase.tackle == "manifest"

    def test_phase_with_model_override(self):
        """Phase overriding the default model."""
        phase = PhaseConfig(
            name="custom_model",
            instructions="Use Claude",
            model="anthropic/claude-sonnet-4"
        )
        assert phase.model == "anthropic/claude-sonnet-4"

    def test_handoffs_as_strings(self):
        """Handoffs specified as simple strings."""
        phase = PhaseConfig(
            name="router",
            instructions="Route to next phase",
            handoffs=["phase_a", "phase_b", "phase_c"]
        )
        assert phase.handoffs == ["phase_a", "phase_b", "phase_c"]

    def test_handoffs_as_configs(self):
        """Handoffs with HandoffConfig for descriptions."""
        phase = PhaseConfig(
            name="router",
            instructions="Route",
            handoffs=[
                HandoffConfig(target="success", description="When task succeeds"),
                HandoffConfig(target="failure", description="When task fails"),
            ]
        )
        assert len(phase.handoffs) == 2
        assert phase.handoffs[0].target == "success"
        assert phase.handoffs[0].description == "When task succeeds"


# =============================================================================
# RULES CONFIG VALIDATION
# =============================================================================

class TestRuleConfig:
    """Test RuleConfig for phase execution rules."""

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
        """Set max turns for phase execution."""
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

    def test_phase_with_rules(self):
        """Phase with full rules configuration."""
        phase = PhaseConfig(
            name="with_rules",
            instructions="Iterative phase",
            rules=RuleConfig(
                max_turns=10,
                max_attempts=3,
                loop_until="quality_check",
                retry_instructions="Please try again with better quality."
            )
        )
        assert phase.rules.max_turns == 10
        assert phase.rules.loop_until == "quality_check"


# =============================================================================
# CONTEXT SYSTEM VALIDATION
# =============================================================================

class TestContextConfig:
    """Test selective context configuration."""

    def test_context_from_previous(self):
        """Context from previous phase only."""
        # Note: Must use dict syntax for 'from' alias to work
        ctx = ContextConfig(**{"from": ["previous"]})
        assert ctx.from_ == ["previous"]
        assert ctx.include_input is True

    def test_context_from_all(self):
        """Explicit snowball - all prior context."""
        ctx = ContextConfig(**{"from": ["all"]})
        assert ctx.from_ == ["all"]

    def test_context_from_specific_phases(self):
        """Context from specific named phases."""
        ctx = ContextConfig(**{"from": ["phase_a", "phase_c"]})
        assert ctx.from_ == ["phase_a", "phase_c"]

    def test_context_with_exclusions(self):
        """All context except specific phases."""
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
            phase="generate_chart",
            include=["images", "output"],
            images_filter="last",
            as_role="user"
        )
        assert source.phase == "generate_chart"
        assert "images" in source.include
        assert source.images_filter == "last"

    def test_context_mixed_sources(self):
        """Mix of string and detailed source configs."""
        ctx = ContextConfig(**{"from": [
            "first",
            {"phase": "chart_gen", "include": ["images"]},
            "previous"
        ]})
        assert len(ctx.from_) == 3
        assert ctx.from_[0] == "first"
        assert isinstance(ctx.from_[1], ContextSourceConfig)

    def test_context_from_json_alias(self):
        """The 'from' alias works in JSON parsing."""
        data = {
            "from": ["all"],
            "exclude": ["phase_x"],
            "include_input": False
        }
        ctx = ContextConfig(**data)
        assert ctx.from_ == ["all"]
        assert ctx.include_input is False


# =============================================================================
# SOUNDINGS (Tree of Thought) VALIDATION
# =============================================================================

class TestSoundingsConfig:
    """Test soundings/Tree-of-Thought configuration."""

    def test_basic_soundings(self):
        """Basic soundings with evaluator."""
        soundings = SoundingsConfig(
            factor=3,
            evaluator_instructions="Pick the most creative response."
        )
        assert soundings.factor == 3
        assert soundings.mutate is True  # Default
        assert soundings.max_parallel == 3  # Default

    def test_soundings_defaults(self):
        """Verify soundings defaults."""
        soundings = SoundingsConfig()
        assert soundings.factor == 1
        assert soundings.max_parallel == 3
        assert soundings.evaluator_instructions is None
        assert soundings.mutate is True
        assert soundings.mutation_mode == "rewrite"
        assert soundings.mutations is None

    def test_soundings_with_mutations(self):
        """Custom mutations for prompt variation."""
        soundings = SoundingsConfig(
            factor=5,
            mutate=True,
            mutation_mode="augment",
            mutations=[
                "Think step by step.",
                "Consider multiple perspectives.",
                "Be concise and direct."
            ]
        )
        assert soundings.mutation_mode == "augment"
        assert len(soundings.mutations) == 3

    def test_soundings_with_validator(self):
        """Pre-evaluation validator to filter soundings."""
        soundings = SoundingsConfig(
            factor=5,
            validator="code_executes",
            evaluator_instructions="Pick the cleanest code that runs."
        )
        assert soundings.validator == "code_executes"

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

    def test_soundings_with_reforge(self):
        """Soundings with reforge loop."""
        soundings = SoundingsConfig(
            factor=3,
            evaluator_instructions="Pick best approach.",
            reforge=ReforgeConfig(
                steps=2,
                honing_prompt="Refine and polish."
            )
        )
        assert soundings.reforge.steps == 2

    def test_multi_model_soundings_list(self):
        """Multi-model soundings with list of models."""
        soundings = SoundingsConfig(
            factor=6,
            models=["openai/gpt-4o", "anthropic/claude-sonnet-4", "google/gemini-2.5-flash"],
            model_strategy="round_robin"
        )
        assert len(soundings.models) == 3
        assert soundings.model_strategy == "round_robin"

    def test_multi_model_soundings_dict(self):
        """Multi-model soundings with per-model config."""
        soundings = SoundingsConfig(
            models={
                "openai/gpt-4o": ModelConfig(factor=2, temperature=0.7),
                "anthropic/claude-sonnet-4": ModelConfig(factor=3, temperature=0.5),
            },
            model_strategy="weighted"
        )
        assert soundings.models["openai/gpt-4o"].factor == 2
        assert soundings.models["anthropic/claude-sonnet-4"].temperature == 0.5

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
        """Human evaluation of soundings."""
        soundings = SoundingsConfig(
            factor=3,
            evaluator="human",
            human_eval=HumanSoundingEvalConfig(
                presentation=HumanEvalPresentation.SIDE_BY_SIDE,
                selection_mode=HumanEvalSelectionMode.PICK_ONE,
                require_reasoning=True
            )
        )
        assert soundings.evaluator == "human"
        assert soundings.human_eval.require_reasoning is True


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

    def test_phase_with_wards(self):
        """Phase with ward configuration."""
        phase = PhaseConfig(
            name="validated",
            instructions="Generate JSON",
            wards=WardsConfig(
                post=[WardConfig(validator="json_valid", mode="retry", max_attempts=3)]
            )
        )
        assert phase.wards.post[0].validator == "json_valid"


# =============================================================================
# HUMAN INPUT CONFIG
# =============================================================================

class TestHumanInputConfig:
    """Test human-in-the-loop configuration."""

    def test_simple_confirmation(self):
        """Simple boolean human_input flag."""
        phase = PhaseConfig(
            name="needs_approval",
            instructions="Do something",
            human_input=True
        )
        assert phase.human_input is True

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

    def test_phase_with_rag(self):
        """Phase with RAG configuration."""
        phase = PhaseConfig(
            name="rag_search",
            instructions="Search the documentation for {{ input.query }}",
            rag=RagConfig(directory="docs", recursive=True)
        )
        assert phase.rag.directory == "docs"


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

    def test_phase_overrides(self):
        """Per-phase token budget overrides."""
        budget = TokenBudgetConfig(
            max_total=100000,
            phase_overrides={
                "synthesis": 50000,
                "quick_task": 10000
            }
        )
        assert budget.phase_overrides["synthesis"] == 50000


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
        phase = PhaseConfig(
            name="tagged",
            instructions="Do work",
            callouts="Key Result"
        )
        assert phase.callouts == "Key Result"

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

    def test_phase_with_sub_cascades(self):
        """Phase with sub-cascade references."""
        phase = PhaseConfig(
            name="orchestrator",
            instructions="Coordinate sub-tasks",
            sub_cascades=[
                SubCascadeRef(ref="task_a.json"),
                SubCascadeRef(ref="task_b.json", context_in=False)
            ]
        )
        assert len(phase.sub_cascades) == 2


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
            phases=[PhaseConfig(name="main", instructions="Work")]
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
            phases=[PhaseConfig(
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
            phases=[PhaseConfig(name="chat", instructions="Chat with context")]
        )
        assert config.memory == "conversation_history"

    def test_cascade_level_soundings(self):
        """Cascade-level soundings (Tree of Thought)."""
        config = CascadeConfig(
            cascade_id="parallel_approaches",
            soundings=SoundingsConfig(
                factor=3,
                evaluator_instructions="Pick the best overall approach."
            ),
            phases=[
                PhaseConfig(name="analyze", instructions="Analyze the problem"),
                PhaseConfig(name="solve", instructions="Solve it", context=ContextConfig(from_=["previous"]))
            ]
        )
        assert config.soundings.factor == 3

    def test_cascade_with_all_features(self):
        """Cascade exercising many features together."""
        config = CascadeConfig(
            cascade_id="feature_rich",
            description="Tests multiple features",
            inputs_schema={"topic": "Research topic"},
            memory="research_memory",
            token_budget=TokenBudgetConfig(max_total=50000),
            tool_caching=ToolCachingConfig(enabled=True),
            phases=[
                PhaseConfig(
                    name="research",
                    instructions="Research {{ input.topic }}",
                    tackle=["smart_sql_run"],
                    rag=RagConfig(directory="knowledge"),
                    rules=RuleConfig(max_turns=5),
                    handoffs=["synthesize"]
                ),
                PhaseConfig(
                    name="synthesize",
                    instructions="Synthesize findings",
                    context=ContextConfig(from_=["research"]),
                    soundings=SoundingsConfig(
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
        assert config.phases[0].rag.directory == "knowledge"
        assert config.phases[1].soundings.factor == 3


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
            phases=[
                PhaseConfig(
                    name="discover",
                    instructions="Find an interesting question.",
                    rules=RuleConfig(max_turns=3, loop_until="check_question")
                ),
                PhaseConfig(
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
            phases=[
                PhaseConfig(
                    name="work",
                    instructions="Do something",
                    rules=RuleConfig(loop_until="validate_output")
                )
            ]
        )
        assert "{{ input.content }}" in config.validators["validate_output"].instructions

    def test_load_cascade_with_inline_validators(self):
        """Load a cascade file that uses inline validators."""
        # Load the actual sql_chart_gen_analysis_full.yaml
        config = load_cascade_config("examples/sql_chart_gen_analysis_full.yaml")
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
            CascadeConfig(phases=[PhaseConfig(name="x", instructions="y")])
        assert "cascade_id" in str(exc_info.value)

    def test_missing_phases(self):
        """Cascade without phases should fail."""
        with pytest.raises(ValidationError) as exc_info:
            CascadeConfig(cascade_id="no_phases")
        assert "phases" in str(exc_info.value)

    def test_empty_phases(self):
        """Cascade with empty phases list is allowed by Pydantic.

        Note: While structurally valid, an empty phases cascade
        is semantically meaningless. Runtime validation could
        catch this if desired.
        """
        # Pydantic allows empty list - document this behavior
        config = CascadeConfig(cascade_id="empty_phases", phases=[])
        assert config.phases == []

    def test_phase_missing_name(self):
        """Phase without name should fail."""
        with pytest.raises(ValidationError) as exc_info:
            PhaseConfig(instructions="No name provided")
        assert "name" in str(exc_info.value)

    def test_phase_missing_instructions(self):
        """Phase without instructions should fail."""
        with pytest.raises(ValidationError) as exc_info:
            PhaseConfig(name="no_instructions")
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
                phase="test",
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
            "phases": [
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
            "phases": [
                {
                    "name": "research",
                    "instructions": "Research the topic",
                    "tackle": ["smart_sql_run"],
                    "context": {
                        "from": ["all"],
                        "include_input": True
                    },
                    "soundings": {
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
        assert config.phases[0].soundings.factor == 3
        assert config.phases[0].soundings.reforge.steps == 2
        assert config.phases[0].wards.post[0].mode == "retry"

    def test_load_preserves_jinja_templates(self):
        """Jinja2 templates in instructions are preserved."""
        data = {
            "cascade_id": "templated",
            "phases": [
                {
                    "name": "greet",
                    "instructions": "Hello {{ input.name }}! Your state is {{ state.mood }}."
                }
            ]
        }
        config = load_cascade_config(data)
        assert "{{ input.name }}" in config.phases[0].instructions
        assert "{{ state.mood }}" in config.phases[0].instructions


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
            "phases": [{"name": "main", "instructions": "Work"}]
        }
        is_valid, errors = validate_cascade(data)
        assert is_valid is True
        assert errors == []

    def test_invalid_cascade_returns_errors(self):
        """Invalid cascade returns (False, [errors])."""
        data = {
            "cascade_id": "invalid",
            # Missing phases
        }
        is_valid, errors = validate_cascade(data)
        assert is_valid is False
        assert len(errors) > 0
        assert any("phases" in e.lower() for e in errors)

    def test_multiple_errors_collected(self):
        """Multiple validation errors are collected."""
        data = {
            # Missing cascade_id
            "phases": [
                {"name": "incomplete"}  # Missing instructions
            ]
        }
        is_valid, errors = validate_cascade(data)
        assert is_valid is False
        assert len(errors) >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
