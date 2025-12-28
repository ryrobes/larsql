"""
Prompt optimization through candidate analysis.

The key insight: Soundings generate training data automatically.
Every candidate run = A/B test with cost, time, quality metrics.

After N runs, analyze which candidate approaches win most often,
then suggest prompt improvements based on winning patterns.
"""
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime


class SoundingAnalyzer:
    """Analyzes candidate winners to suggest prompt improvements."""

    def __init__(self, data_dir: str = None):
        from rvbbit.config import get_config
        from rvbbit.db_adapter import get_db_adapter
        config = get_config()
        self.data_dir = Path(data_dir or config.data_dir)
        self.db = get_db_adapter()

    def analyze_cascade(
        self,
        cascade_file: str,
        min_runs: int = 10,
        min_confidence: float = 0.6
    ) -> Dict[str, Any]:
        """
        Analyze a cascade's candidate patterns and suggest improvements.

        Args:
            cascade_file: Path to cascade JSON (can also be cascade_id)
            min_runs: Minimum number of runs before suggesting (default: 10)
            min_confidence: Minimum win rate for dominant candidate (default: 60%)

        Returns:
            Analysis with suggestions for each phase
        """
        print(f"Analyzing cascade: {cascade_file}")
        print(f"Minimum runs: {min_runs}, Confidence threshold: {min_confidence*100}%")
        print()

        # Extract cascade_id from the file path (e.g., "examples/foo.json" -> "foo")
        # This handles both full paths and just cascade_ids
        cascade_id = Path(cascade_file).stem if '/' in cascade_file or '\\' in cascade_file else cascade_file

        # Query unified_logs table directly (pure ClickHouse)
        # Search by both cascade_file (full path) AND cascade_id (logical name)
        # Most candidate logs only have cascade_id, not cascade_file
        sessions_query = f"""
            SELECT DISTINCT session_id
            FROM unified_logs
            WHERE cascade_file = '{cascade_file}'
               OR position(cascade_file, '{cascade_file}') > 0
               OR cascade_id = '{cascade_id}'
        """

        try:
            result = self.db.query(sessions_query, output_format="dict")
            sessions = [r['session_id'] for r in result]
        except Exception as e:
            print(f"Error querying logs: {e}")
            return {"suggestions": []}

        if len(sessions) < min_runs:
            print(f"Not enough data: Found {len(sessions)} runs, need {min_runs}")
            return {"suggestions": []}

        print(f"Found {len(sessions)} runs")

        # Analyze each phase that has soundings
        suggestions = []

        # Get phases with soundings (use cell_name column directly)
        # Search by both cascade_file and cascade_id
        phases_query = f"""
            SELECT DISTINCT cell_name
            FROM unified_logs
            WHERE (cascade_file = '{cascade_file}'
               OR position(cascade_file, '{cascade_file}') > 0
               OR cascade_id = '{cascade_id}')
              AND cell_name IS NOT NULL
              AND candidate_index IS NOT NULL
        """

        try:
            result = self.db.query(phases_query, output_format="dict")
            cells = set(r['cell_name'] for r in result if r['cell_name'])
        except Exception as e:
            print(f"Error querying phases: {e}")
            cells = set()

        print(f"Analyzing {len(phases)} phase(s) with soundings data...")
        print()

        for cell_name in phases:
            suggestion = self._analyze_phase(
                cascade_file,
                cascade_id,
                cell_name,
                min_confidence
            )

            if suggestion:
                suggestions.append(suggestion)

        return {
            "cascade_file": cascade_file,
            "analyzed_at": datetime.now().isoformat(),
            "total_runs": len(sessions),
            "suggestions": suggestions
        }

    def _analyze_phase(
        self,
        cascade_file: str,
        cascade_id: str,
        cell_name: str,
        min_confidence: float
    ) -> Optional[Dict[str, Any]]:
        """Analyze a single phase's candidate patterns."""

        # Query unified_logs table directly for candidate data
        # Search by both cascade_file and cascade_id
        query = f"""
            SELECT
                candidate_index,
                is_winner,
                cost,
                role,
                content_json
            FROM unified_logs
            WHERE (cascade_file = '{cascade_file}'
               OR position(cascade_file, '{cascade_file}') > 0
               OR cascade_id = '{cascade_id}')
              AND cell_name = '{cell_name}'
              AND candidate_index IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT 500
        """

        try:
            result = self.db.query(query, output_format="dict")
            events = result
        except Exception as e:
            return None

        if not events:
            return None

        # Parse candidate data
        sounding_attempts = {}  # {candidate_index: {"wins": N, "costs": [], "content": []}}

        for row in events:
            try:
                candidate_index = row.get("candidate_index")
                is_winner = row.get("is_winner")
                cost = row.get("cost")
                role = row.get("role")
                content = row.get("content_json")

                if candidate_index is None:
                    continue

                if candidate_index not in sounding_attempts:
                    sounding_attempts[candidate_index] = {
                        "wins": 0,
                        "total": 0,
                        "costs": [],
                        "content": []
                    }

                sounding_attempts[candidate_index]["total"] += 1

                if is_winner:
                    sounding_attempts[candidate_index]["wins"] += 1

                # Track cost if available
                if cost:
                    sounding_attempts[candidate_index]["costs"].append(cost)

                # Track agent responses for pattern extraction
                if role == "assistant" and content:
                    # Parse content if it's JSON string
                    if isinstance(content, str):
                        try:
                            content = json.loads(content)
                        except:
                            pass
                    sounding_attempts[candidate_index]["content"].append(str(content) if content else "")

            except:
                continue

        if not sounding_attempts:
            return None

        # Find dominant winner
        dominant = None
        max_wins = 0

        for idx, data in sounding_attempts.items():
            if data["wins"] > max_wins:
                max_wins = data["wins"]
                dominant = (idx, data)

        if not dominant:
            return None

        dominant_index, dominant_data = dominant

        # Calculate win rate correctly:
        # - total_competitions = number of times ANY candidate was selected as winner
        # - win_rate = this candidate's wins / total competitions
        total_competitions = sum(d["wins"] for d in sounding_attempts.values())
        total_rows = sum(d["total"] for d in sounding_attempts.values())
        win_rate = dominant_data["wins"] / total_competitions if total_competitions > 0 else 0

        if win_rate < min_confidence:
            return None  # Not confident enough

        # Calculate metrics
        avg_cost = sum(dominant_data["costs"]) / len(dominant_data["costs"]) if dominant_data["costs"] else 0

        # Calculate loser metrics for comparison
        loser_costs = []
        for idx, data in sounding_attempts.items():
            if idx != dominant_index:
                loser_costs.extend(data["costs"])

        avg_loser_cost = sum(loser_costs) / len(loser_costs) if loser_costs else avg_cost

        # Extract patterns from winning content
        patterns = self._extract_patterns(dominant_data["content"][:10])  # Sample first 10

        return {
            "phase": cell_name,
            "dominant_sounding": dominant_index,
            "win_rate": win_rate,
            "total_attempts": total_competitions,  # Number of competitions (sessions with winners)
            "total_rows": total_rows,  # Total log rows analyzed
            "wins": dominant_data["wins"],
            "metrics": {
                "avg_cost": avg_cost,
                "avg_loser_cost": avg_loser_cost,
                "cost_improvement": ((avg_loser_cost - avg_cost) / avg_loser_cost * 100) if avg_loser_cost > 0 else 0
            },
            "patterns": patterns,
            "confidence": "high" if win_rate > 0.75 else "medium"
        }

    def _extract_patterns(self, content_samples: List[str]) -> List[str]:
        """Extract common patterns from winning responses."""

        patterns = []

        # Simple pattern extraction (could be much more sophisticated)
        all_content = "\n\n".join(content_samples)

        # Check for common phrases
        if "step by step" in all_content.lower():
            patterns.append("Uses step-by-step reasoning")

        if "first" in all_content.lower() and "then" in all_content.lower():
            patterns.append("Follows sequential approach (first X, then Y)")

        if any(word in all_content.lower() for word in ["explore", "understand", "analyze"]):
            patterns.append("Starts with exploration/understanding")

        if len(content_samples) > 0:
            avg_length = sum(len(c) for c in content_samples) / len(content_samples)
            if avg_length < 500:
                patterns.append("Concise responses (< 500 chars)")
            elif avg_length > 1500:
                patterns.append("Detailed responses (> 1500 chars)")

        # Count mentions of data/validation/accessibility
        if all_content.lower().count("data") > len(content_samples) * 2:
            patterns.append("Emphasizes data quality/validation")

        if "accessible" in all_content.lower() or "accessibility" in all_content.lower():
            patterns.append("Considers accessibility")

        return patterns if patterns else ["No clear patterns detected"]

    def generate_suggestion(
        self,
        current_instruction: str,
        analysis: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate improved instruction based on analysis.

        This uses an LLM to synthesize the suggestion.
        Could also be done with a cascade!
        """
        from rvbbit.agent import Agent
        from rvbbit.config import get_config

        config = get_config()

        patterns_text = "\n".join(f"- {p}" for p in analysis["patterns"])

        prompt = f"""You are a prompt optimization expert.

Current Instruction:
"{current_instruction}"

Analysis of {analysis['wins']} winning candidate attempts (out of {analysis['total_attempts']} total):
- Win rate: {analysis['win_rate']*100:.1f}%
- Cost improvement: {analysis['metrics']['cost_improvement']:.1f}% cheaper than losers
- Confidence: {analysis['confidence']}

Winning patterns observed:
{patterns_text}

Generate an improved instruction that:
1. Captures the winning patterns
2. Remains concise (< 300 chars)
3. Is specific and actionable
4. Preserves the original intent

Return ONLY the improved instruction, no explanation.
"""

        agent = Agent(
            model=config.default_model,
            system_prompt="You are a concise prompt optimization expert.",
            base_url=config.provider_base_url,
            api_key=config.provider_api_key
        )

        response = agent.run(prompt)
        suggested_instruction = response.get("content", "").strip()

        return {
            "phase": analysis["phase"],
            "current_instruction": current_instruction,
            "suggested_instruction": suggested_instruction,
            "rationale": patterns_text,
            "impact": {
                "cost_improvement": f"{analysis['metrics']['cost_improvement']:.0f}%",
                "confidence": analysis['confidence'],
                "based_on_runs": analysis['wins']
            }
        }


class PromptSuggestionManager:
    """Manages prompt improvement suggestions."""

    def __init__(self):
        self.suggestions_dir = Path("suggestions")
        self.suggestions_dir.mkdir(exist_ok=True)

    def save_suggestions(self, analysis: Dict[str, Any]) -> Path:
        """Save analysis to file for review."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cascade_name = Path(analysis["cascade_file"]).stem
        filename = f"{cascade_name}_{timestamp}.json"

        filepath = self.suggestions_dir / filename

        with open(filepath, 'w') as f:
            json.dump(analysis, f, indent=2)

        print(f"Suggestions saved: {filepath}")
        return filepath

    def apply_suggestion(
        self,
        cascade_file: str,
        cell_name: str,
        new_instruction: str,
        auto_commit: bool = False
    ) -> bool:
        """
        Apply a suggestion to a cascade file.

        Args:
            cascade_file: Path to cascade JSON
            cell_name: Which phase to update
            new_instruction: New instruction text
            auto_commit: Whether to auto-commit to git

        Returns:
            True if successful
        """
        # Load cascade
        with open(cascade_file, 'r') as f:
            cascade = json.load(f)

        # Find and update the cell
        updated = False
        for phase in cascade.get("cells", []):
            if phase.get("name") == cell_name:
                old_instruction = phase.get("instructions", "")
                phase["instructions"] = new_instruction
                updated = True

                print(f"Updated phase: {cell_name}")
                print()
                print("Diff:")
                print(f"- {old_instruction[:80]}...")
                print(f"+ {new_instruction[:80]}...")
                print()
                break

        if not updated:
            print(f"Phase '{cell_name}' not found in cascade")
            return False

        # Write back
        with open(cascade_file, 'w') as f:
            json.dump(cascade, f, indent=2)

        print(f"✓ Cascade updated: {cascade_file}")

        # Auto-commit if requested
        if auto_commit:
            import subprocess

            commit_msg = f"""Auto-optimize: Improved {cell_name} prompt

Based on candidate analysis:
- Applied winning pattern
- See suggestions/ directory for details

Auto-generated commit
"""

            try:
                subprocess.run(["git", "add", cascade_file], check=True)
                subprocess.run(["git", "commit", "-m", commit_msg], check=True)
                print("✓ Changes committed to git")
            except subprocess.CalledProcessError as e:
                print(f"Note: Git commit failed (maybe not in a repo?): {e}")

        return True


def analyze_and_suggest(
    cascade_file: str,
    cell_name: str = None,
    min_runs: int = 10
) -> Dict[str, Any]:
    """
    Convenience function: Analyze cascade and generate suggestions.

    Args:
        cascade_file: Path to cascade JSON
        cell_name: Specific phase to analyze (None = all phases)
        min_runs: Minimum runs needed

    Returns:
        Full analysis with suggestions
    """
    analyzer = SoundingAnalyzer()
    analysis = analyzer.analyze_cascade(cascade_file, min_runs=min_runs)

    if not analysis["suggestions"]:
        print("No suggestions available (not enough data or no clear winners)")
        return analysis

    # Load current cascade to get instructions
    with open(cascade_file) as f:
        cascade = json.load(f)

    # Generate suggestions for each phase
    for suggestion in analysis["suggestions"]:
        cell = suggestion["phase"]

        # Skip if we're only analyzing a specific phase
        if cell_name and phase != cell_name:
            continue

        # Find current instruction
        current_instruction = None
        for p in cascade.get("cells", []):
            if p.get("name") == phase:
                current_instruction = p.get("instructions", "")
                break

        if current_instruction:
            # Generate improved instruction
            improved = analyzer.generate_suggestion(current_instruction, suggestion)
            suggestion.update(improved)

    return analysis
