import os
from jinja2 import Environment, FileSystemLoader, BaseLoader
from typing import Any, Dict

class PromptEngine:
    def __init__(self, template_dirs: list[str] = None):
        # Use CWD if not specified
        dirs = template_dirs or [os.getcwd()]
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
    return _engine.render(instruction, context)
