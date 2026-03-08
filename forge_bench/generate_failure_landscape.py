import os
import json
from collections import Counter
from typing import List, Dict
import sys

# Ensure imports work from the root dir
sys.path.insert(0, os.getcwd())

try:
    from forgeos.providers.model_router import ProviderRouter, ModelRole
except ImportError:
    print("Warning: ProviderRouter not found. Run from the project root.")
    ProviderRouter, ModelRole = None, None

FAILURE_DB_PATH = os.path.join(os.getcwd(), "forgeos", "memory", "failure_db")

def parse_failures() -> List[Dict]:
    records = []
    if not os.path.exists(FAILURE_DB_PATH):
        return records
        
    for fname in os.listdir(FAILURE_DB_PATH):
        if fname.endswith(".json"):
            with open(os.path.join(FAILURE_DB_PATH, fname), "r") as f:
                try:
                    records.append(json.load(f))
                except json.JSONDecodeError:
                    pass
    return records

def generate_landscape() -> str:
    records = parse_failures()
    total = len(records)
    
    if total == 0:
        return "# ForgeOS Failure Landscape\n\nNo failures recorded yet. Run `omnibench.py` to farm failures."
        
    report = f"# ForgeOS Failure Landscape\n\n**Total Analyzed Failures:** {total}\n\n"
    
    # Analyze by Failure Class
    class_counter = Counter(r.get("failure_class", "Unknown") for r in records)
    report += "## Failure Classification\n"
    for c, count in class_counter.most_common():
        pct = (count / total) * 100
        report += f"- **{c}**: {pct:.1f}% ({count} occurrences)\n"
        
    # Analyze by Failure Signature
    sig_counter = Counter(r.get("failure_signature", "Unknown") for r in records)
    report += "\n## Top Failure Signatures\n"
    for sig, count in sig_counter.most_common(10):
        pct = (count / total) * 100
        report += f"- **{sig}**: {pct:.1f}%\n"
        
    # Analyze by Outcome
    outcome_counter = Counter(r.get("outcome", "Unknown") for r in records)
    report += "\n## Run Outcomes\n"
    for o, count in outcome_counter.most_common():
        pct = (count / total) * 100
        report += f"- **{o}**: {pct:.1f}%\n"
        
    # LLM Insights Generation
    if ProviderRouter and ModelRole:
        print("Generating Architectural Insights via LLM...")
        try:
            router = ProviderRouter()
            prompt = f"""
            You are the Chief Architect of ForgeOS. Analyze the following empirical failure statistics.
            Based on the distribution of failures, write a 'Top Failure Modes Report'.
            Provide specific architectural recommendations on how to counter the dominant failure signatures.
            If "patch too wide" is common, recommend "Patch Width Limiters". If "wrong module" is common, recommend "Symbol Graph Retrieval".
            
            Stats:
            {report}
            """
            res = router.generate_response(
                ModelRole.PLANNER,
                system_prompt="You are the Chief Architect of ForgeOS.",
                user_prompt=prompt
            )
            insights = res["content"]
            report += f"\n\n## Core System Insights\n\n{insights}"
        except Exception as e:
            report += f"\n\n## Core System Insights\n\n*Failed to generate insights: {e}*"
            
    return report

def _run():
    report = generate_landscape()
    output_path = os.path.join(os.getcwd(), "forge_bench", "failure_landscape.md")
    with open(output_path, "w") as f:
        f.write(report)
    print(f"\nGenerated Failure Landscape Report at: {output_path}")

if __name__ == "__main__":
    _run()
