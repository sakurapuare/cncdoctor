from __future__ import annotations

from functools import cached_property, lru_cache
from pathlib import Path

from .repositories import SqlSeedLoader, SQLiteFaultCaseRepository, build_graph_repository
from .services import (
    CompletionService,
    DiagnosisService,
    FeedbackService,
    OnlineAnalysisService,
    QuestionAnsweringService,
    WebSearchClient,
)
from .text import (
    FaultTextParser,
    HybridFaultTextClassifier,
    ResourceCatalog,
    RuntimeSettings,
    SimilarityScorer,
    Tokenizer,
)


class ServiceContainer:
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir

    @cached_property
    def settings(self) -> RuntimeSettings:
        return RuntimeSettings.from_base_dir(self._base_dir)

    @cached_property
    def resources(self) -> ResourceCatalog:
        return ResourceCatalog(self.settings)

    @cached_property
    def tokenizer(self) -> Tokenizer:
        return Tokenizer(self.resources)

    @cached_property
    def scorer(self) -> SimilarityScorer:
        return SimilarityScorer(self.tokenizer)

    @cached_property
    def classifier(self) -> HybridFaultTextClassifier:
        return HybridFaultTextClassifier(self.resources)

    @cached_property
    def parser(self) -> FaultTextParser:
        return FaultTextParser(self.tokenizer, self.classifier, self.resources)

    @cached_property
    def case_repository(self) -> SQLiteFaultCaseRepository:
        return SQLiteFaultCaseRepository(
            db_path=self.settings.case_db_path,
            seed_loader=SqlSeedLoader(self.settings.seed_sql_path),
            scorer=self.scorer,
        )

    @cached_property
    def graph_repository(self):
        return build_graph_repository(self.settings)

    @cached_property
    def diagnosis_service(self) -> DiagnosisService:
        return DiagnosisService(
            parser=self.parser,
            scorer=self.scorer,
            case_repository=self.case_repository,
            graph_repository=self.graph_repository,
        )

    @cached_property
    def completion_service(self) -> CompletionService:
        return CompletionService(
            case_repository=self.case_repository,
            graph_repository=self.graph_repository,
        )

    @cached_property
    def qa_service(self) -> QuestionAnsweringService:
        return QuestionAnsweringService(
            scorer=self.scorer,
            case_repository=self.case_repository,
            graph_repository=self.graph_repository,
        )

    @cached_property
    def feedback_service(self) -> FeedbackService:
        return FeedbackService(
            parser=self.parser,
            case_repository=self.case_repository,
            graph_repository=self.graph_repository,
        )

    @cached_property
    def search_client(self) -> WebSearchClient:
        return WebSearchClient(self.settings, self.scorer)

    @cached_property
    def online_analysis_service(self) -> OnlineAnalysisService:
        return OnlineAnalysisService(
            parser=self.parser,
            case_repository=self.case_repository,
            web_search_client=self.search_client,
        )


@lru_cache(maxsize=1)
def get_container() -> ServiceContainer:
    base_dir = Path(__file__).resolve().parents[2]
    return ServiceContainer(base_dir=base_dir)
