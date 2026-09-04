"""
Personal Intelligence Experimental & Research Module (Deferred from V1).

Contains research prototypes that are not part of the active V1 execution path:
  - MCTS Multi-Step Causal World Simulator (mcts_simulator.py)
  - Theory of Mind Collaborator Profiles (person_model.py)
  - Predictive Processing & Karl Friston Free Energy Baselines (predictive.py)
  - Bayesian Probabilistic Fact Reinforcement (ProbabilisticFact)

The core V1 runtime operates deterministically without these components.
"""

from personal_intelligence.experimental.mcts_simulator import MCTSOptionNode, MCTSTreeResult, MCTSWorldSimulator
from personal_intelligence.experimental.probabilistic_fact import ProbabilisticFact
from personal_intelligence.experimental.predictive import ExpectedState, PredictiveProcessingEngine
from personal_intelligence.core.world.person_model import PersonEntity, PersonModelEngine

__all__ = [
    "MCTSWorldSimulator",
    "MCTSOptionNode",
    "MCTSTreeResult",
    "ProbabilisticFact",
    "PersonModelEngine",
    "PersonEntity",
    "PredictiveProcessingEngine",
    "ExpectedState",
]
