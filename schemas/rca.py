from pydantic import BaseModel, Field, field_validator, model_validator


class AlternativeHypothesis(BaseModel):
    hypothesis: str
    likelihood: float = Field(ge=0.0, le=1.0)

    model_config = {"frozen": True}


class RCA(BaseModel):
    root_cause: str | None
    evidence_ids: list[str]
    affected_components: list[str]
    alternative_hypotheses: list[AlternativeHypothesis] = Field(default_factory=list)
    recommended_action: str | None = None
    insufficient_evidence: bool
    model: str
    prompt_version: str

    model_config = {"frozen": True}

    @model_validator(mode="after")
    def root_cause_null_when_insufficient(self) -> "RCA":
        if self.insufficient_evidence and self.root_cause is not None:
            raise ValueError("root_cause must be null when insufficient_evidence is true")
        return self
