import os
from jinja2 import Environment, FileSystemLoader, BaseLoader
from typing import Any, Dict

class PromptEngine:
    def __init__(self, template_dirs: list[str] = None):
        # Use CWD if not specified, plus standard prompt locations
        dirs = template_dirs or [os.getcwd()]

        # Add cascades/prompts directory for reusable prompt includes
        # Check both CWD-relative and RVBBIT_ROOT-relative locations
        cascades_prompts = os.path.join(os.getcwd(), 'cascades', 'prompts')
        if os.path.isdir(cascades_prompts):
            dirs.append(cascades_prompts)

        # Also check RVBBIT_ROOT if set
        rvbbit_root = os.environ.get('RVBBIT_ROOT')
        if rvbbit_root:
            root_prompts = os.path.join(rvbbit_root, 'cascades', 'prompts')
            if os.path.isdir(root_prompts) and root_prompts not in dirs:
                dirs.append(root_prompts)

        self.env = Environment(loader=FileSystemLoader(dirs))
        
    def render(self, template_str_or_path: str, context: Dict[str, Any]) -> str:
        """
        Renders a prompt. 
        If string starts with '@', treats it as a file path.
        Otherwise treats it as an inline template string.
        """
        if template_str_or_path.startswith("@"):
            # Load from file
            path = template_str_or_path[1:] # strip @
            # We might need to handle absolute paths vs relative to template_dirs
            # For simplicity, if it exists locally, use it directly via string loading if outside loader path
            if os.path.exists(path):
                with open(path, 'r') as f:
                    content = f.read()
                template = self.env.from_string(content)
                return template.render(**context)
            else:
                # Try loader
                try:
                    template = self.env.get_template(path)
                    return template.render(**context)
                except Exception:
                    # Fallback or error
                    return f"Error: Template not found {path}"
        else:
            # Inline
            template = self.env.from_string(template_str_or_path)
            return template.render(**context)

_engine = PromptEngine()

def render_instruction(instruction: str, context: Dict[str, Any]) -> str:
    # Debug logging for branching sessions
    if 'state' in context and context['state'].get('conversation_history'):
        print(f"[PromptRender] ✓ Rendering with conversation_history: {len(context['state']['conversation_history'])} items")
        print(f"[PromptRender] State keys available: {list(context.get('state', {}).keys())}")
        print(f"[PromptRender] input.initial_query: {context.get('input', {}).get('initial_query')}")
    elif 'state' in context and context['state']:
        print(f"[PromptRender] ⚠ Rendering with state but NO conversation_history")
        print(f"[PromptRender] State keys: {list(context.get('state', {}).keys())}")

    rendered = _engine.render(instruction, context)

    # Show first 500 chars of rendered prompt if branching
    if context.get('input', {}).get('initial_query'):
        print(f"[PromptRender] ===== RENDERED PROMPT (first 500 chars) =====")
        print(rendered[:500])
        print(f"[PromptRender] ============================================")

    return rendered
