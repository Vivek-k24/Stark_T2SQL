"""Deterministic governed-vocabulary resolution before generation (FR-3/FR-7).

This is a single-turn metadata transformation. It performs no SQL/model calls.
Longest matches come from the original vocabulary, so an unavailable explicit
phrase cannot fall back to a shorter permitted meaning. Ambiguity is evaluated
only among role-visible targets. This is context minimization, not enforcement.
"""

from __future__ import annotations

import re
import unicodedata

from ..contracts import Clarification
from ..db.catalog import SchemaSnapshot
from ..errors import InvalidRequestError
from ..policy.loader import PolicyMatrix
from .contracts import ResolutionStatus, VocabularyResolution
from .entitlements import filter_catalog_for_role
from .models import SemanticCatalog


_SAFE_QUESTION = "Please state the business meaning and time basis you want using the available vocabulary."


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().replace("_", " ").split())


def _lexicon(catalog: SemanticCatalog) -> dict[str, frozenset[str]]:
    targets: dict[str, set[str]] = {}
    for definition in tuple(catalog.entities.values()) + tuple(catalog.metrics.values()):
        for label in (definition.id, definition.name) + definition.aliases:
            targets.setdefault(_normalize(label), set()).add(definition.id)
    for ambiguity in catalog.ambiguities:
        targets.setdefault(_normalize(ambiguity.term), set()).update(ambiguity.targets)
    return {label: frozenset(values) for label, values in targets.items()}


def _clarification(
    candidates: set[str], visible: SemanticCatalog
) -> VocabularyResolution:
    definitions = dict(visible.entities) | dict(visible.metrics)
    options = tuple(sorted({definitions[item].name for item in candidates if item in definitions}))
    if not options:
        # No permitted interpretation is not an answerable clarification.
        return VocabularyResolution(ResolutionStatus.RESOLVED, (), None)
    return VocabularyResolution(
        status=ResolutionStatus.CLARIFICATION_REQUIRED,
        concept_ids=(),
        clarification=Clarification(question=_SAFE_QUESTION, options=options),
    )


def _finish_term(
    targets: frozenset[str], visible: SemanticCatalog
) -> VocabularyResolution:
    permitted = targets & (set(visible.entities) | set(visible.metrics))
    if len(permitted) > 1:
        return _clarification(set(permitted), visible)
    return VocabularyResolution(
        status=ResolutionStatus.RESOLVED,
        concept_ids=tuple(sorted(permitted)),
        clarification=None,
    )


def _finish_question(
    matched: tuple[frozenset[str], ...], visible: SemanticCatalog
) -> VocabularyResolution:
    visible_ids = set(visible.entities) | set(visible.metrics)
    # Retain global longest-phrase matching, then evaluate role-visible meanings.
    # Zero visible targets assert no meaning; downstream guards own enforcement.
    permitted = tuple(targets & visible_ids for targets in matched)
    ambiguous = [targets for targets in permitted if len(targets) > 1]
    if ambiguous:
        ambiguous_candidates = set().union(*ambiguous)
        return _clarification(ambiguous_candidates, visible)
    resolved_visible = set().union(*permitted) if permitted else set()
    return VocabularyResolution(
        status=ResolutionStatus.RESOLVED,
        concept_ids=tuple(sorted(resolved_visible)),
        clarification=None,
    )


def resolve_term(
    term: str,
    catalog: SemanticCatalog,
    matrix: PolicyMatrix,
    snapshot: SchemaSnapshot,
    business_role: str,
) -> VocabularyResolution:
    """Resolve one explicitly requested business term, or request clarification.

    Unknown terms ask for available vocabulary when there is any. Unavailable
    terms resolve with no asserted meaning; only multiple visible meanings ask
    for disambiguation. Hidden names never enter clarification options.
    """
    if not isinstance(term, str) or not term.strip():
        raise InvalidRequestError("An explicit governed term must be nonempty text.")
    visible = filter_catalog_for_role(catalog, matrix, snapshot, business_role)
    targets = _lexicon(catalog).get(_normalize(term))
    if targets is None:
        return _clarification(set(visible.entities) | set(visible.metrics), visible)
    return _finish_term(targets, visible)


def resolve_question(
    question: str,
    catalog: SemanticCatalog,
    matrix: PolicyMatrix,
    snapshot: SchemaSnapshot,
    business_role: str,
) -> VocabularyResolution:
    """Resolve recognized vocabulary using longest whole-phrase matches.

    An explicit unique phrase such as active headcount covers its shorter
    headcount substring; a separate headcount occurrence remains ambiguous.
    The original question is never rewritten. Words outside governed vocabulary
    remain for the later generator: RESOLVED with no concept IDs asserts no
    business interpretation. Call resolve_term for an explicitly requested term
    that must have a documented meaning; an unknown term asks for visible vocabulary.
    """
    if not isinstance(question, str) or not question.strip():
        raise InvalidRequestError("Governed resolution requires a nonempty business question.")
    visible = filter_catalog_for_role(catalog, matrix, snapshot, business_role)
    lexicon = _lexicon(catalog)
    normalized = _normalize(question)
    occurrences = []
    for label in sorted(lexicon):
        expression = re.compile(r"(?<!\w)" + re.escape(label) + r"(?!\w)")
        for match in expression.finditer(normalized):
            occurrences.append((match.start(), match.end(), label))
    accepted = []
    # Length first prevents generic inner aliases from overriding an explicit
    # governed phrase; remaining ties use position and lexical order.
    for start, end, label in sorted(occurrences, key=lambda item: (-(item[1] - item[0]), item[0], item[2])):
        if any(start < prior_end and end > prior_start for prior_start, prior_end, _ in accepted):
            continue
        accepted.append((start, end, label))
    matched = tuple(lexicon[label] for _, _, label in sorted(accepted))
    return _finish_question(matched, visible)
