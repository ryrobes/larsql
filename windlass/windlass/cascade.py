from typing import List, Dict, Any, Optional, Union, Literal
from pydantic import BaseModel, Field

class RuleConfig(BaseModel):
    max_turns: Optional[int] = None
    max_attempts: Optional[int] = None
    loop_until: Optional[str] = None
    retry_instructions: Optional[str] = None

class SubCascadeRef(BaseModel):
    ref: str
    input_map: Dict[str, str] = Field(default_factory=dict)
    context_in: bool = True
    context_out: bool = True

class HandoffConfig(BaseModel):
    target: str
    description: Optional[str] = None

class AsyncCascadeRef(BaseModel):
    ref: str
    input_map: Dict[str, str] = Field(default_factory=dict)
    context_in: bool = True
    trigger: str = "on_start" # on_start, on_end

class WardConfig(BaseModel):
    validator: str  # Name of validator tool/cascade
    mode: Literal["blocking", "advisory", "retry"] = "blocking"
    max_attempts: int = 1  # For retry mode

class WardsConfig(BaseModel):
    pre: List[WardConfig] = Field(default_factory=list)
    post: List[WardConfig] = Field(default_factory=list)
    turn: List[WardConfig] = Field(default_factory=list)  # Optional per-turn validation

class ReforgeConfig(BaseModel):
    steps: int = 1  # Number of refinement iterations
    honing_prompt: str  # Additional refinement instructions
    factor_per_step: int = 2  # Soundings per reforge step
    mutate: bool = False  # Apply built-in variation strategies
    evaluator_override: Optional[str] = None  # Custom evaluator for refinement steps
    threshold: Optional[WardConfig] = None  # Early stopping validation (ward-like)

class SoundingsConfig(BaseModel):
    factor: int = 1
    evaluator_instructions: str
    reforge: Optional[ReforgeConfig] = None  # Optional refinement loop

class PhaseConfig(BaseModel):
    name: str
    instructions: str
    tackle: Union[List[str], Literal["manifest"]] = Field(default_factory=list)
    manifest_context: Literal["current", "full"] = "current"
    rules: RuleConfig = Field(default_factory=RuleConfig)
    handoffs: List[Union[str, HandoffConfig]] = Field(default_factory=list)
    sub_cascades: List[SubCascadeRef] = Field(default_factory=list)
    async_cascades: List[AsyncCascadeRef] = Field(default_factory=list)
    soundings: Optional[SoundingsConfig] = None
    output_schema: Optional[Dict[str, Any]] = None
    wards: Optional[WardsConfig] = None

class CascadeConfig(BaseModel):
    cascade_id: str
    phases: List[PhaseConfig]
    description: Optional[str] = None
    inputs_schema: Optional[Dict[str, str]] = None # name -> description
    soundings: Optional[SoundingsConfig] = None  # Cascade-level soundings (Tree of Thought)

def load_cascade_config(path_or_dict: Union[str, Dict]) -> CascadeConfig:
    if isinstance(path_or_dict, str):
        import json
        with open(path_or_dict, 'r') as f:
            data = json.load(f)
    else:
        data = path_or_dict
    return CascadeConfig(**data)
