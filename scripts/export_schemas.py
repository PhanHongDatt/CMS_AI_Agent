"""Export Pydantic models to JSON Schema files in schemas/json/."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from schemas.action import Action
from schemas.confidence import Confidence
from schemas.evidence import Evidence
from schemas.incident import Incident
from schemas.policy import PolicyDecision
from schemas.rca import RCA
from schemas.verification import Verification

MODELS = {
    "incident": Incident,
    "evidence": Evidence,
    "rca": RCA,
    "confidence": Confidence,
    "policy_decision": PolicyDecision,
    "action": Action,
    "verification": Verification,
}

output_dir = Path(__file__).parent.parent / "schemas" / "json"
output_dir.mkdir(parents=True, exist_ok=True)

for name, model in MODELS.items():
    schema = model.model_json_schema()
    out_path = output_dir / f"{name}.json"
    out_path.write_text(json.dumps(schema, indent=2))
    print(f"Exported {name} -> {out_path}")

print("All schemas exported successfully.")
