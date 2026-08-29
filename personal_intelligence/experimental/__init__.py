"""
Personal Intelligence Experimental & Research Module (Deferred from V1).

Contains research prototypes that are not part of the active V1 execution path:
  - MCTS Multi-Step Causal World Simulator (mcts_simulator.py)
  - Theory of Mind Collaborator Profiles (person_model.py)
  - Predictive Processing & Karl Friston Free Energy Baselines (predictive.py)
  - Hippocampal Memory Consolidation (compaction.py)
  - Bayesian Probabilistic Fact Reinforcement (ProbabilisticFact)

The core V1 runtime operates deterministically without these components.
"""

from personal_intelligence.core.world.mcts_simulator import MCTSOptionNode, MCTSWorldSimulator
from personal_intelligence.core.world.person_model import PersonEntity, PersonModelEngine
from personal_intelligence.core.world.predictive import ExpectedState, PredictiveProcessingEngine
from personal_intelligence.core.patterns.compaction import CompactionSummary, HippocampalCompactor

__all__ = [
    "MCTSWorldSimulator",
    "MCTSOptionNode",
    "PersonModelEngine",
    "PersonEntity",
    "PredictiveProcessingEngine",
    "ExpectedState",
    "HippocampalCompactor",
    "CompactionSummary",
]
