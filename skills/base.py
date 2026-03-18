"""
Hedgehog Skills Base
Registry and base class for all skills
"""
import json
from typing import Callable, Any, Dict, List, Optional, Tuple


# Map simple types to JSON Schema types
TYPE_MAP = {
    "str": "string",
    "string": "string",
    "int": "integer",
    "integer": "integer",
    "float": "number",
    "number": "number",
    "bool": "boolean",
    "boolean": "boolean",
}


class Skill:
    """Represents a callable skill"""

    def __init__(
        self,
        name: str,
        func: Callable,
        description: str,
        parameters: List[Dict] = None,
    ):
        self.name = name
        self.func = func
        self.description = description
        self.parameters = parameters or []

    def execute(self, **kwargs) -> Any:
        """Execute the skill with given parameters"""
        return self.func(**kwargs)

    def get_tool_schema(self) -> Dict:
        """
        Get OpenAI function calling schema for this skill

        Returns:
            Dict in OpenAI tool format
        """
        # Build properties from parameters
        properties = {}
        required = []

        for param in self.parameters:
            param_name = param["name"]
            param_type = TYPE_MAP.get(param.get("type", "str"), "string")
            param_desc = param.get("description", "")

            properties[param_name] = {
                "type": param_type,
                "description": param_desc,
            }

            # Assume all params are required unless marked optional
            if not param.get("optional", False):
                required.append(param_name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


class SkillRegistry:
    """Central registry for all available skills"""

    def __init__(self):
        self.skills: Dict[str, Skill] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: List[Dict] = None,
    ) -> Callable:
        """Decorator to register a skill"""
        def decorator(func: Callable) -> Callable:
            skill = Skill(name, func, description, parameters)
            self.skills[name] = skill
            return func
        return decorator

    def get(self, name: str) -> Optional[Skill]:
        """Get a skill by name"""
        return self.skills.get(name)

    def execute(self, skill_name: str, **kwargs) -> Tuple[bool, Any]:
        """
        Execute a skill by name

        Returns:
            Tuple of (success, result_or_error)
        """
        skill = self.get(skill_name)
        if not skill:
            return False, f"Unknown skill: {skill_name}"

        try:
            result = skill.execute(**kwargs)
            return True, result
        except Exception as e:
            return False, f"Error executing {skill_name}: {str(e)}"

    def get_tools_schema(self) -> List[Dict]:
        """
        Get OpenAI tools schema for all registered skills

        Returns:
            List of tool schemas in OpenAI format
        """
        return [skill.get_tool_schema() for skill in self.skills.values()]


# Global registry
_registry = None

def get_registry() -> SkillRegistry:
    """Get or create the skill registry"""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
        # Import skills to register them
        from skills import database, system, soulwinners
        from skills import solana_trading, telegram_skills, auto_heal
    return _registry
