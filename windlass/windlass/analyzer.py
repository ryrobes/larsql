"""
Prompt optimization through sounding analysis.

The key insight: Soundings generate training data automatically.
Every sounding run = A/B test with cost, time, quality metrics.

After N runs, analyze which sounding approaches win most often,
then suggest prompt improvements based on winning patterns.
"""
import json
import duckdb
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime


class SoundingAnalyzer:
    """Analyzes sounding winners to suggest prompt improvements."""

    def __init__(self, log_dir: str = None):
        from windlass.config import get_config
        config = get_config()
        self.log_dir = Path(log_dir or config.log_dir)

    def analyze_cascade(
        self,
        cascade_file: str,
        min_runs: int = 10,
        min_confidence: float = 0.6
    ) -> Dict[str, Any]:
        """
        Analyze a cascade's sounding patterns and suggest improvements.

        Args:
            cascade_file: Path to cascade JSON
            min_runs: Minimum number of runs before suggesting (default: 10)
            min_confidence: Minimum win rate for dominant sounding (default: 60%)

        Returns:
            Analysis with suggestions for each phase
        """
        print(f"Analyzing cascade: {cascade_file}")
        print(f"Minimum runs: {min_runs}, Confidence threshold: {min_confidence*100}%")
        print()

        conn = duckdb.connect()
        parquet_pattern = str(self.log_dir / "**" / "*.parquet")

        # Get all sessions for this cascade
        sessions_query = f"""
            SELECT DISTINCT session_id
            FROM read_parquet('{parquet_pattern}')
            WHERE metadata LIKE '%{cascade_file}%'
        """

        try:
            sessions = conn.execute(sessions_query).fetchall()
        except Exception as e:
            print(f"Error querying logs: {e}")
            return {"suggestions": []}

        if len(sessions) < min_runs:
            print(f"Not enough data: Found {len(sessions)} runs, need {min_runs}")
            return {"suggestions": []}

        print(f"Found {len(sessions)} runs")

        # Analyze each phase that has soundings
        suggestions = []

        # Get phases with soundings
        phases_query = f"""
            SELECT DISTINCT metadata
            FROM read_parquet('{parquet_pattern}')
            WHERE metadata LIKE '%{cascade_file}%'
            AND role = 'phase_start'
            LIMIT 50
        """

        phase_events = conn.execute(phases_query).fetchall()

        # Extract unique phase names
        phases = set()
        for event in phase_events:
            try:
                meta = json.loads(event[0]) if event[0] else {}
                if meta.get("phase_name"):
                    phases.add(meta["phase_name"])
            except:
                pass

        print(f"Analyzing {len(phases)} phase(s) with soundings data...")
        print()

        for phase_name in phases:
            suggestion = self._analyze_phase(
                conn,
                parquet_pattern,
                cascade_file,
                phase_name,
                min_confidence
            )

            if suggestion:
                suggestions.append(suggestion)

        conn.close()

        return {
            "cascade_file": cascade_file,
            "analyzed_at": datetime.now().isoformat(),
            "total_runs": len(sessions),
            "suggestions": suggestions
        }

    def _analyze_phase(
        self,
        conn,
        parquet_pattern: str,
        cascade_file: str,
        phase_name: str,
        min_confidence: float
    ) -> Optional[Dict[str, Any]]:
        """Analyze a single phase's sounding patterns."""

        # Query for sounding winners in this phase
        query = f"""
            SELECT
                metadata,
                content,
                role
            FROM read_parquet('{parquet_pattern}')
            WHERE metadata LIKE '%{cascade_file}%'
            AND metadata LIKE '%{phase_name}%'
            AND metadata LIKE '%sounding_index%'
            ORDER BY timestamp DESC
            LIMIT 500
        """

        try:
            events = conn.execute(query).fetchall()
        except Exception as e:
            return None

        if not events:
            return None

        # Parse sounding data
        sounding_attempts = {}  # {sounding_index: {"wins": N, "costs": [], "content": []}}

        for meta_str, content, role in events:
            try:
                meta = json.loads(meta_str) if meta_str else {}
                sounding_index = meta.get("sounding_index")
                is_winner = meta.get("is_winner")

                if sounding_index is None:
                    continue

                if sounding_index not in sounding_attempts:
                    sounding_attempts[sounding_index] = {
                        "wins": 0,
                        "total": 0,
                        "costs": [],
                        "content": []
                    }

                sounding_attempts[sounding_index]["total"] += 1

                if is_winner:
                    sounding_attempts[sounding_index]["wins"] += 1

                # Track cost if available
                cost = meta.get("cost", 0)
                if cost:
                    sounding_attempts[sounding_index]["costs"].append(cost)

                # Track agent responses for pattern extraction
                if role == "agent" and content:
                    sounding_attempts[sounding_index]["content"].append(content)

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
        total_attempts = sum(d["total"] for d in sounding_attempts.values())
        win_rate = dominant_data["wins"] / total_attempts if total_attempts > 0 else 0

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
            "phase": phase_name,
            "dominant_sounding": dominant_index,
            "win_rate": win_rate,
            "total_attempts": total_attempts,
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
        from windlass.agent import Agent
        from windlass.config import get_config

        config = get_config()

        patterns_text = "\n".join(f"- {p}" for p in analysis["patterns"])

        prompt = f"""You are a prompt optimization expert.

Current Instruction:
"{current_instruction}"

Analysis of {analysis['wins']} winning sounding attempts (out of {analysis['total_attempts']} total):
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
            model=config.model,
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
        phase_name: str,
        new_instruction: str,
        auto_commit: bool = False
    ) -> bool:
        """
        Apply a suggestion to a cascade file.

        Args:
            cascade_file: Path to cascade JSON
            phase_name: Which phase to update
            new_instruction: New instruction text
            auto_commit: Whether to auto-commit to git

        Returns:
            True if successful
        """
        # Load cascade
        with open(cascade_file, 'r') as f:
            cascade = json.load(f)

        # Find and update the phase
        updated = False
        for phase in cascade.get("phases", []):
            if phase.get("name") == phase_name:
                old_instruction = phase.get("instructions", "")
                phase["instructions"] = new_instruction
                updated = True

                print(f"Updated phase: {phase_name}")
                print()
                print("Diff:")
                print(f"- {old_instruction[:80]}...")
                print(f"+ {new_instruction[:80]}...")
                print()
                break

        if not updated:
            print(f"Phase '{phase_name}' not found in cascade")
            return False

        # Write back
        with open(cascade_file, 'w') as f:
            json.dump(cascade, f, indent=2)

        print(f"✓ Cascade updated: {cascade_file}")

        # Auto-commit if requested
        if auto_commit:
            import subprocess

            commit_msg = f"""Auto-optimize: Improved {phase_name} prompt

Based on sounding analysis:
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
    phase_name: str = None,
    min_runs: int = 10
) -> Dict[str, Any]:
    """
    Convenience function: Analyze cascade and generate suggestions.

    Args:
        cascade_file: Path to cascade JSON
        phase_name: Specific phase to analyze (None = all phases)
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
        phase = suggestion["phase"]

        # Skip if we're only analyzing a specific phase
        if phase_name and phase != phase_name:
            continue

        # Find current instruction
        current_instruction = None
        for p in cascade.get("phases", []):
            if p.get("name") == phase:
                current_instruction = p.get("instructions", "")
                break

        if current_instruction:
            # Generate improved instruction
            improved = analyzer.generate_suggestion(current_instruction, suggestion)
            suggestion.update(improved)

    return analysis
