"""Ambiguity case requirements; no held-out question content is embedded."""
from dataclasses import dataclass

from stark_t2sql.contracts import ExpectedOutcome
from stark_t2sql.evaluation.cases import CaseSet
from stark_t2sql.semantic.models import SemanticCatalog
from benchmarks.accuracy.spec import load_tuning_cases


@dataclass(frozen=True,slots=True)
class AmbiguitySpec:
    term: str
    governed_meanings: tuple[str,...]
    expected_outcome: ExpectedOutcome=ExpectedOutcome.CLARIFICATION_REQUIRED
    require_no_generation: bool=True
    require_no_execution: bool=True


def build_specs(catalog:SemanticCatalog) -> tuple[AmbiguitySpec,...]:
    # Concepts are catalog IDs, not natural-language questions or answers.
    return tuple(AmbiguitySpec(item.term,item.targets) for item in catalog.ambiguities)


def load_ambiguity(index,case_ids,*,loader):
    loaded=load_tuning_cases(index,case_ids,expected_set=CaseSet.AMBIGUITY,loader=loader)
    for item in loaded:
        if item.case.expected_outcome not in {ExpectedOutcome.CLARIFICATION_REQUIRED,ExpectedOutcome.CANONICAL_RESOLUTION}:
            raise ValueError("Ambiguity cases must distinguish clarification from documented canonical resolution")
    return loaded
