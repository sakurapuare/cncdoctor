from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urljoin

from .models import (
    AutocompleteResult,
    DiagnosisCandidate,
    DiagnosisResult,
    FaultCase,
    FaultQuery,
    FeedbackRecord,
    QuestionAnswerResult,
    ReasoningStep,
    SearchResult,
)
from .repositories import GraphKnowledgeRepository, SQLiteFaultCaseRepository
from .text import (
    FaultTextParser,
    RuntimeSettings,
    SimilarityScorer,
    normalize_text,
    unique_preserve_order,
)


class DiagnosisService:
    def __init__(
        self,
        parser: FaultTextParser,
        scorer: SimilarityScorer,
        case_repository: SQLiteFaultCaseRepository,
        graph_repository: GraphKnowledgeRepository,
    ) -> None:
        self._parser = parser
        self._scorer = scorer
        self._case_repository = case_repository
        self._graph_repository = graph_repository

    def diagnose(self, query: FaultQuery) -> DiagnosisResult:
        parsed = self._parser.parse(query)
        selected = unique_preserve_order(parsed.symptoms + query.related_symptoms)

        hidden: list[str] = []
        candidate_map: dict[str, DiagnosisCandidate] = {}
        selected_from_graph = list(selected)

        if self._graph_repository.available():
            graph_payload = self._diagnose_with_graph(parsed, selected)
            selected_from_graph = unique_preserve_order(selected + graph_payload["selected"])
            hidden = unique_preserve_order(graph_payload["hidden"])
            for candidate in graph_payload["candidates"]:
                self._merge_candidate(candidate_map, candidate)

        for candidate in self._diagnose_with_cases(query, parsed, selected_from_graph):
            self._merge_candidate(candidate_map, candidate)

        candidates = sorted(candidate_map.values(), key=lambda item: item.score, reverse=True)[:5]
        return DiagnosisResult(
            selectedlist=selected_from_graph,
            hiddenlist=hidden,
            candidates=candidates,
            parsed=parsed,
        )

    def _diagnose_with_graph(
        self,
        parsed,
        selected: list[str],
    ) -> dict[str, list]:
        matched_operations = self._match_entities(parsed.operations, "Caozuo", threshold=0.55)
        matched_symptoms = self._match_entities(parsed.symptoms, "Xianxiang", threshold=0.5)
        matched_alarm_codes = self._match_entities(parsed.alarm_codes, "Errorid", threshold=0.9)
        matched_parts = self._match_entities(parsed.parts, "GuzhangBuwei", threshold=1.0)

        derived_symptoms: list[str] = []
        for operation in matched_operations:
            derived_symptoms.extend(self._graph_repository.find_related_from(operation, "引起"))
        for alarm_code in matched_alarm_codes:
            derived_symptoms.extend(self._graph_repository.find_related_to(alarm_code, "报警信息"))
        for part in matched_parts:
            derived_symptoms.extend(self._graph_repository.find_related_to(part, "故障部位"))

        selected_graph = unique_preserve_order(selected + matched_symptoms + derived_symptoms)
        hidden = []
        for symptom in selected_graph:
            hidden.extend(self._graph_repository.find_related_from(symptom, "相关"))
        hidden = [item for item in unique_preserve_order(hidden) if item not in selected_graph]

        cause_hits: dict[str, list[str]] = defaultdict(list)
        for symptom in selected_graph:
            for cause in self._graph_repository.find_related_from(symptom, "间接原因"):
                cause_hits[cause].append(symptom)

        candidates: list[DiagnosisCandidate] = []
        for cause, evidence in cause_hits.items():
            total = max(self._graph_repository.count_related_to(cause, "间接原因"), 1)
            score = round(len(unique_preserve_order(evidence)) / total, 2)
            answers = self._case_repository.answers_for_cause(cause)
            reasoning = [
                ReasoningStep(
                    entity1=symptom,
                    rel="间接原因",
                    entity2=cause,
                    entity1_type="现象",
                    entity2_type="最终原因",
                )
                for symptom in unique_preserve_order(evidence)
            ]
            reasoning.extend(
                ReasoningStep(
                    entity1=cause,
                    rel="解决办法",
                    entity2=answer,
                    entity1_type="最终原因",
                    entity2_type="解决办法",
                )
                for answer in answers
            )
            candidates.append(
                DiagnosisCandidate(
                    cause=cause,
                    answers=answers,
                    score=score,
                    reasoning_steps=reasoning,
                    source="graph",
                )
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        return {"selected": selected_graph, "hidden": hidden, "candidates": candidates[:5]}

    def _diagnose_with_cases(
        self,
        query: FaultQuery,
        parsed,
        selected: list[str],
    ) -> list[DiagnosisCandidate]:
        query_text = " ".join(
            part
            for part in [
                query.brand,
                query.model,
                query.alarm_code,
                query.question,
                " ".join(selected),
            ]
            if part
        )
        case_hits = self._case_repository.search_similar(query_text, limit=12)
        grouped: dict[str, dict[str, object]] = {}

        for case, score in case_hits:
            bucket = grouped.setdefault(
                case.cause,
                {
                    "score": 0.0,
                    "answers": [],
                    "steps": [],
                    "cases": [],
                },
            )
            bucket["score"] = max(float(bucket["score"]), score)
            bucket["answers"].append(case.analysis)
            bucket["cases"].append(case)

        candidates: list[DiagnosisCandidate] = []
        for cause, bucket in grouped.items():
            answers = unique_preserve_order(bucket["answers"])[:5]
            cases: list[FaultCase] = bucket["cases"]  # type: ignore[assignment]
            steps: list[ReasoningStep] = []
            for case in cases[:3]:
                evidence = self._pick_case_evidence(selected, case)
                if evidence:
                    steps.append(
                        ReasoningStep(
                            entity1=evidence,
                            rel="案例匹配",
                            entity2=cause,
                            entity1_type="现象",
                            entity2_type="最终原因",
                        )
                    )
            steps.extend(
                ReasoningStep(
                    entity1=cause,
                    rel="解决办法",
                    entity2=answer,
                    entity1_type="最终原因",
                    entity2_type="解决办法",
                )
                for answer in answers
            )
            candidates.append(
                DiagnosisCandidate(
                    cause=cause,
                    answers=answers,
                    score=round(float(bucket["score"]), 2),
                    reasoning_steps=steps,
                    source="case_repo",
                )
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[:5]

    def _match_entities(self, values: list[str], label: str, threshold: float) -> list[str]:
        entities = self._graph_repository.list_entities(label)
        matches: list[tuple[float, str]] = []
        for value in values:
            for entity in entities:
                score = self._scorer.score(value, entity)
                if normalize_text(value) == normalize_text(entity):
                    score = 1.0
                if score >= threshold:
                    matches.append((score, entity))
        matches.sort(key=lambda item: item[0], reverse=True)
        return unique_preserve_order(entity for _, entity in matches)

    def _pick_case_evidence(self, selected: list[str], case: FaultCase) -> str:
        if not selected:
            return case.phenomenon[:80]
        scored = [(self._scorer.score(item, case.phenomenon), item) for item in selected]
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    def _merge_candidate(
        self,
        candidate_map: dict[str, DiagnosisCandidate],
        candidate: DiagnosisCandidate,
    ) -> None:
        existing = candidate_map.get(candidate.cause)
        existing_answers = existing.answers if existing else []
        merged_answers = unique_preserve_order(existing_answers + candidate.answers)
        merged_steps = (existing.reasoning_steps if existing else []) + candidate.reasoning_steps
        merged_sources = unique_preserve_order(
            (existing.source.split("+") if existing else []) + candidate.source.split("+")
        )
        candidate_map[candidate.cause] = DiagnosisCandidate(
            cause=candidate.cause,
            answers=merged_answers[:5],
            score=max(candidate.score, existing.score if existing else 0.0),
            reasoning_steps=merged_steps[:12],
            source="+".join(merged_sources),
        )


class CompletionService:
    def __init__(
        self,
        case_repository: SQLiteFaultCaseRepository,
        graph_repository: GraphKnowledgeRepository,
    ) -> None:
        self._case_repository = case_repository
        self._graph_repository = graph_repository

    def complete(self, fragment: str) -> AutocompleteResult:
        suggestions = self._case_repository.search_prefix(fragment, limit=5)
        if self._graph_repository.available():
            suggestions.extend(self._graph_repository.search_descriptions(fragment, limit=5))
        return AutocompleteResult(
            query=fragment, suggestions=unique_preserve_order(suggestions)[:5]
        )


class QuestionAnsweringService:
    QUESTION_PATTERNS = [
        (0, [r"会引起哪些现象", r"会引起什么现象", r"引起的现象", r"会引起的现象"]),
        (1, [r"会遇到什么错误", r"会遇到哪些错误", r"会出现哪些现象"]),
        (2, [r"部位常出现哪些故障", r"部位常见的故障", r"部位会出现什么问题"]),
        (3, [r"报警的含义是什么", r"报警的含义", r"报警是什么意思", r"报警的原因是什么"]),
    ]

    def __init__(
        self,
        scorer: SimilarityScorer,
        case_repository: SQLiteFaultCaseRepository,
        graph_repository: GraphKnowledgeRepository,
    ) -> None:
        self._scorer = scorer
        self._case_repository = case_repository
        self._graph_repository = graph_repository

    def answer(self, question: str) -> QuestionAnswerResult:
        subject, question_type = self._parse_question(question)
        if question_type == -1:
            fallback = self._case_repository.search_similar(question, limit=3)
            return QuestionAnswerResult(
                question=question,
                answers=unique_preserve_order(case.analysis for case, _ in fallback),
            )

        if self._graph_repository.available():
            answers = self._answer_from_graph(subject, question_type)
            if answers:
                return QuestionAnswerResult(question=question, answers=answers)

        return QuestionAnswerResult(
            question=question, answers=self._answer_from_cases(subject, question_type)
        )

    def _answer_from_graph(self, subject: str, question_type: int) -> list[str]:
        if question_type == 0:
            causes = self._best_graph_matches(subject, "Yuanyin")
            answers: list[str] = []
            for cause in causes:
                answers.extend(self._graph_repository.find_related_to(cause, "间接原因"))
            return unique_preserve_order(answers)

        if question_type == 1:
            operations = self._best_graph_matches(subject, "Caozuo")
            answers: list[str] = []
            for operation in operations:
                answers.extend(self._graph_repository.find_related_from(operation, "引起"))
            return unique_preserve_order(answers)

        if question_type == 2:
            parts = self._best_graph_matches(subject, "GuzhangBuwei")
            answers: list[str] = []
            for part in parts:
                answers.extend(self._graph_repository.find_related_to(part, "故障部位"))
            return unique_preserve_order(answers)

        if question_type == 3:
            alarms = self._best_graph_matches(subject, "Errorid")
            answers: list[str] = []
            for alarm in alarms:
                answers.extend(self._graph_repository.find_related_from(alarm, "直接原因"))
            return unique_preserve_order(answers)

        return []

    def _answer_from_cases(self, subject: str, question_type: int) -> list[str]:
        hits = self._case_repository.search_similar(subject, limit=10)
        answers: list[str] = []
        if question_type == 0:
            cause_cases = self._case_repository.cases_for_cause(subject, limit=5)
            answers = [case.phenomenon for case in cause_cases]
        elif question_type == 3:
            answers = [
                case.cause for case, _ in hits if subject.upper() in case.searchable_text().upper()
            ]
        else:
            answers = [case.analysis for case, _ in hits]
        return unique_preserve_order(answers)[:5]

    def _best_graph_matches(self, subject: str, label: str) -> list[str]:
        scored: list[tuple[float, str]] = []
        for entity in self._graph_repository.list_entities(label):
            score = self._scorer.score(subject, entity)
            if normalize_text(subject) == normalize_text(entity):
                score = 1.0
            if score >= 0.52:
                scored.append((score, entity))
        scored.sort(key=lambda item: item[0], reverse=True)
        return unique_preserve_order(entity for _, entity in scored)

    def _parse_question(self, question: str) -> tuple[str, int]:
        for question_type, patterns in self.QUESTION_PATTERNS:
            for pattern in patterns:
                matched = re.search(pattern, question)
                if matched:
                    return question[: matched.start()].strip("？?。 "), question_type
        return question.strip(), -1


class FeedbackService:
    def __init__(
        self,
        parser: FaultTextParser,
        case_repository: SQLiteFaultCaseRepository,
        graph_repository: GraphKnowledgeRepository,
    ) -> None:
        self._parser = parser
        self._case_repository = case_repository
        self._graph_repository = graph_repository

    def save(self, record: FeedbackRecord) -> dict[str, object]:
        cause = normalize_text(record.cause)
        if not cause:
            parsed = self._parser.parse(
                FaultQuery(
                    brand=record.brand,
                    model=record.model,
                    alarm_code=record.alarm_code,
                    question=record.question,
                    related_symptoms=record.selected_signals,
                )
            )
            last_symptom = parsed.symptoms[-1] if parsed.symptoms else "待确认故障"
            record = FeedbackRecord(
                brand=record.brand,
                model=record.model,
                alarm_code=record.alarm_code,
                question=record.question,
                selected_signals=record.selected_signals,
                cause=f"{last_symptom}引起的故障",
                answer=record.answer,
            )
        saved_case = self._case_repository.save_feedback(record)
        parsed = self._parser.parse(
            FaultQuery(
                brand=record.brand,
                model=record.model,
                alarm_code=record.alarm_code,
                question=record.question,
                related_symptoms=record.selected_signals,
            )
        )
        graph_updated = self._graph_repository.upsert_feedback(parsed, record)
        return {
            "message": "保存成功",
            "saved_case": saved_case.to_dict(),
            "graph_updated": graph_updated,
        }


class WebSearchClient:
    def __init__(self, settings: RuntimeSettings, scorer: SimilarityScorer) -> None:
        self._settings = settings
        self._scorer = scorer

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        if not self._settings.online_search_enabled:
            return []
        results = self._search_baidu(query, limit) + self._search_duckduckgo(query, limit)
        deduped: list[SearchResult] = []
        seen: set[tuple[str, str]] = set()
        for item in sorted(results, key=lambda value: value.score, reverse=True):
            key = (normalize_text(item.title), item.url)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= limit:
                break
        return deduped

    def _search_baidu(self, query: str, limit: int) -> list[SearchResult]:
        response = self._get("https://www.baidu.com/s", params={"wd": query})
        if response is None:
            return []
        try:
            from bs4 import BeautifulSoup
        except ModuleNotFoundError:
            return []

        soup = BeautifulSoup(response, "html.parser")
        items: list[SearchResult] = []
        for container in soup.select("div.result, div.result-op, div.c-container"):
            anchor = container.select_one("h3 a")
            if anchor is None:
                continue
            title = normalize_text(anchor.get_text(" ", strip=True))
            url = anchor.get("href", "").strip()
            snippet_node = container.select_one(".c-abstract, .content-right_8Zs40, .c-color-text")
            snippet = normalize_text(snippet_node.get_text(" ", strip=True) if snippet_node else "")
            if not title or not url:
                continue
            items.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    score=self._scorer.score(query, f"{title} {snippet}"),
                )
            )
            if len(items) >= limit:
                break
        return items

    def _search_duckduckgo(self, query: str, limit: int) -> list[SearchResult]:
        response = self._get("https://duckduckgo.com/html/", params={"q": query})
        if response is None:
            return []
        try:
            from bs4 import BeautifulSoup
        except ModuleNotFoundError:
            return []

        soup = BeautifulSoup(response, "html.parser")
        items: list[SearchResult] = []
        for container in soup.select(".result"):
            anchor = container.select_one(".result__a")
            if anchor is None:
                continue
            title = normalize_text(anchor.get_text(" ", strip=True))
            url = urljoin("https://duckduckgo.com", anchor.get("href", "").strip())
            snippet_node = container.select_one(".result__snippet")
            snippet = normalize_text(snippet_node.get_text(" ", strip=True) if snippet_node else "")
            if not title or not url:
                continue
            items.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    score=self._scorer.score(query, f"{title} {snippet}"),
                )
            )
            if len(items) >= limit:
                break
        return items

    def _get(self, url: str, params: dict[str, str]) -> str | None:
        try:
            import requests
        except ModuleNotFoundError:
            return None

        try:
            response = requests.get(
                url,
                params=params,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
                    )
                },
                timeout=self._settings.web_search_timeout_seconds,
            )
        except Exception:
            return None

        if response.status_code != 200:
            return None
        response.encoding = response.encoding or "utf-8"
        return response.text


class OnlineAnalysisService:
    def __init__(
        self,
        parser: FaultTextParser,
        case_repository: SQLiteFaultCaseRepository,
        web_search_client: WebSearchClient,
    ) -> None:
        self._parser = parser
        self._case_repository = case_repository
        self._web_search_client = web_search_client

    def analyze(self, query: FaultQuery) -> dict[str, object]:
        parsed = self._parser.parse(query)
        search_queries = self._build_queries(query, parsed)
        links: list[SearchResult] = []
        for search_query in search_queries:
            links = self._web_search_client.search(search_query, limit=5)
            if links:
                break

        if not links:
            fallback_cases = self._case_repository.search_similar(query.merged_text(), limit=5)
            answers = [(case.analysis, score) for case, score in fallback_cases]
            return {
                "answer": [
                    {"answer": answer, "zan": max(int(score * 100), 1)} for answer, score in answers
                ],
                "simple_url": [],
                "source": "case_repo",
            }

        return {
            "answer": [
                {"answer": item.snippet or item.title, "zan": int(item.score * 100)}
                for item in links
            ],
            "simple_url": [{"title": item.title, "sub_url": item.url} for item in links],
            "source": "web",
        }

    def _build_queries(self, query: FaultQuery, parsed) -> list[str]:
        candidates: list[str] = []
        if query.brand and parsed.symptoms:
            for symptom in parsed.symptoms[:3]:
                candidates.append(f"{query.brand} {symptom}")
        if query.alarm_code and query.brand:
            candidates.append(f"{query.brand} {query.alarm_code} 故障")
        if query.question:
            candidates.append(query.question)
        if query.related_symptoms:
            candidates.extend(query.related_symptoms[:3])
        if parsed.symptoms:
            candidates.extend(parsed.symptoms[:3])
        return unique_preserve_order(candidates)[:5]
