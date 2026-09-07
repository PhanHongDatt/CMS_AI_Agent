from pydantic import BaseModel, Field, model_validator


class ConfidenceSubScores(BaseModel):
    evidence_quality: float = Field(ge=0.0, le=1.0)
    evidence_completeness: float = Field(ge=0.0, le=1.0)
    evidence_consistency: float = Field(ge=0.0, le=1.0)
    rca_agreement: float = Field(ge=0.0, le=1.0)
    model_output_quality: float = Field(ge=0.0, le=1.0)
    historical_success: float = Field(ge=0.0, le=1.0)

    model_config = {"frozen": True}


class ConfidenceWeights(BaseModel):
    evidence_quality: float = 0.25
    evidence_completeness: float = 0.20
    evidence_consistency: float = 0.20
    rca_agreement: float = 0.15
    model_output_quality: float = 0.10
    historical_success: float = 0.10

    model_config = {"frozen": True}

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "ConfidenceWeights":
        total = (
            self.evidence_quality
            + self.evidence_completeness
            + self.evidence_consistency
            + self.rca_agreement
            + self.model_output_quality
            + self.historical_success
        )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"Weights must sum to 1.0, got {total}")
        return self


class Confidence(BaseModel):
    id: str
    incident_id: str
    sub_scores: ConfidenceSubScores
    weights: ConfidenceWeights = Field(default_factory=ConfidenceWeights)
    final_score: float = Field(ge=0.0, le=1.0)
    calibration_version: str

    model_config = {"frozen": True}

    @model_validator(mode="after")
    def final_score_matches_calculation(self) -> "Confidence":
        w = self.weights
        s = self.sub_scores
        expected = (
            w.evidence_quality * s.evidence_quality
            + w.evidence_completeness * s.evidence_completeness
            + w.evidence_consistency * s.evidence_consistency
            + w.rca_agreement * s.rca_agreement
            + w.model_output_quality * s.model_output_quality
            + w.historical_success * s.historical_success
        )
        if abs(expected - self.final_score) > 1e-4:
            raise ValueError(
                f"final_score {self.final_score} does not match weighted calculation {expected:.4f}"
            )
        return self
