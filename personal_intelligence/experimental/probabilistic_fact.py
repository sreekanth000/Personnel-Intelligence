"""
Probabilistic Fact Store with Bayesian Belief Updating.
[EXPERIMENTAL / FUTURE RESEARCH - DEFERRED FROM V1]

Represents facts with continuous Bayesian probability confidence scores P(H|E)
and Ebbinghaus temporal memory salience decay.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
from typing import Any, Dict, List, Optional
import uuid

from personal_intelligence.core.events.models import ensure_timezone_aware, format_iso8601


@dataclass
class ProbabilisticFact:
    """
    Represents a fact with a Bayesian belief confidence score (0.0 to 1.0)
    and Ebbinghaus temporal memory salience decay.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    subject: str = ""
    predicate: str = ""
    object: str = ""
    belief_score: float = 0.5  # P(Fact | Evidence)
    salience_score: float = 1.0  # Memory salience
    status: str = "active"  # active, retracted, expired
    evidence_ids: List[str] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.created_at = ensure_timezone_aware(self.created_at, "ProbabilisticFact created_at")
        self.updated_at = ensure_timezone_aware(self.updated_at, "ProbabilisticFact updated_at")

    def reinforce_evidence(self, evidence_confidence: float) -> None:
        """Applies Bayesian update when supporting evidence is observed."""
        self.belief_score = 1.0 - (1.0 - self.belief_score) * (1.0 - max(0.0, min(1.0, evidence_confidence)))
        self.salience_score = min(1.0, self.salience_score + 0.2)
        self.updated_at = datetime.now(timezone.utc)

    def apply_decay(self, elapsed_days: float, decay_lambda: float = 0.05) -> None:
        """Applies Ebbinghaus exponential temporal decay to memory salience score."""
        self.salience_score = max(0.0, self.salience_score * math.exp(-decay_lambda * max(0.0, elapsed_days)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.object,
            "belief_score": round(self.belief_score, 4),
            "salience_score": round(self.salience_score, 4),
            "status": self.status,
            "evidence_ids": self.evidence_ids,
            "provenance": self.provenance,
            "created_at": format_iso8601(self.created_at),
            "updated_at": format_iso8601(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProbabilisticFact":
        ev_ids = data.get("evidence_ids") or data.get("evidence_ids_json", [])
        if isinstance(ev_ids, str):
            try:
                ev_ids = json.loads(ev_ids)
            except Exception:
                ev_ids = []
        prov = data.get("provenance") or data.get("provenance_json", {})
        if isinstance(prov, str):
            try:
                prov = json.loads(prov)
            except Exception:
                prov = {}
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            subject=data.get("subject", ""),
            predicate=data.get("predicate", ""),
            object=data.get("object", ""),
            belief_score=float(data.get("belief_score", 0.5)),
            salience_score=float(data.get("salience_score", 1.0)),
            status=data.get("status", "active"),
            evidence_ids=ev_ids,
            provenance=prov,
            created_at=ensure_timezone_aware(data.get("created_at", datetime.now(timezone.utc)), "created_at"),
            updated_at=ensure_timezone_aware(data.get("updated_at", datetime.now(timezone.utc)), "updated_at"),
        )
