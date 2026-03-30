from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class FaultQuery:
    brand: str = ""
    model: str = ""
    alarm_code: str = ""
    question: str = ""
    related_symptoms: list[str] = field(default_factory=list)

    def merged_text(self) -> str:
        parts = [self.question.strip()]
        if self.alarm_code.strip():
            parts.append(f"{self.alarm_code.strip()}报警")
        return "，".join(part for part in parts if part)


@dataclass(frozen=True)
class ParsedFaultText:
    machine_fragments: list[str] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)
    symptoms: list[str] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)
    alarm_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReasoningStep:
    entity1: str
    rel: str
    entity2: str
    entity1_type: str
    entity2_type: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class DiagnosisCandidate:
    cause: str
    answers: list[str]
    score: float
    reasoning_steps: list[ReasoningStep]
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "yuanyin": self.cause,
            "answer": self.answers,
            "possibility": round(self.score, 2),
            "source": self.source,
            "list": [step.to_dict() for step in self.reasoning_steps],
        }


@dataclass(frozen=True)
class DiagnosisResult:
    selectedlist: list[str]
    hiddenlist: list[str]
    candidates: list[DiagnosisCandidate]
    parsed: ParsedFaultText

    def to_dict(self) -> dict[str, Any]:
        return {
            "selectedlist": self.selectedlist,
            "hiddenlist": self.hiddenlist,
            "list": [candidate.to_dict() for candidate in self.candidates],
            "meta": {
                "operations": self.parsed.operations,
                "symptoms": self.parsed.symptoms,
                "parts": self.parsed.parts,
                "alarm_codes": self.parsed.alarm_codes,
                "machine_fragments": self.parsed.machine_fragments,
            },
        }


@dataclass(frozen=True)
class FaultCase:
    id: int | None
    cause: str
    phenomenon: str
    analysis: str
    brand: str = ""
    model: str = ""
    alarm_code: str = ""
    selected_signals: str = ""
    source: str = "seed"
    created_at: str = ""

    def searchable_text(self) -> str:
        return " ".join(
            part
            for part in [
                self.cause,
                self.phenomenon,
                self.analysis,
                self.brand,
                self.model,
                self.alarm_code,
                self.selected_signals,
            ]
            if part
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "score": round(self.score, 2),
        }


@dataclass(frozen=True)
class FeedbackRecord:
    brand: str = ""
    model: str = ""
    alarm_code: str = ""
    question: str = ""
    selected_signals: list[str] = field(default_factory=list)
    cause: str = ""
    answer: str = ""


@dataclass(frozen=True)
class QuestionAnswerResult:
    question: str
    answers: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "answer": self.answers}


@dataclass(frozen=True)
class AutocompleteResult:
    query: str
    suggestions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"query": self.query, "list": self.suggestions}
