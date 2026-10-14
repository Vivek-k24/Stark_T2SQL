"""Require actual defect provenance for externally supplied tuning regressions."""
from dataclasses import dataclass

from stark_t2sql.evaluation.cases import CaseSet
from benchmarks.accuracy.spec import load_tuning_cases


@dataclass(frozen=True,slots=True)
class RegressionEvidence:
    case_id: str
    observed_run_reference: str
    defect_reference: str
    approved_correction_reference: str

    def __post_init__(self):
        if any(not isinstance(item,str) or not item.strip() for item in (
            self.case_id,self.observed_run_reference,self.defect_reference,self.approved_correction_reference)):
            raise ValueError("An actual defect/run/correction reference is required; drafting creates no evidence")


def load_regressions(index,case_ids,*,loader,evidence:tuple[RegressionEvidence,...]):
    by_id={item.case_id:item for item in evidence}
    if len(by_id)!=len(evidence) or set(case_ids)-set(by_id):
        raise ValueError("Every selected regression requires unique actual defect provenance")
    return load_tuning_cases(index,case_ids,expected_set=CaseSet.REGRESSIONS,loader=loader)
