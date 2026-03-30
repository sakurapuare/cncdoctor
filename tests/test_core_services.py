from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Shukongdashi.core.models import DiagnosisCandidate, FaultQuery, FeedbackRecord, ParsedFaultText, ReasoningStep
from Shukongdashi.core.repositories import GraphKnowledgeRepository, NullGraphKnowledgeRepository, SqlSeedLoader, SQLiteFaultCaseRepository
from Shukongdashi.core.services import CompletionService, DiagnosisService, QuestionAnsweringService
from Shukongdashi.core.text import (
    FaultTextParser,
    HybridFaultTextClassifier,
    ResourceCatalog,
    RuntimeSettings,
    SimilarityScorer,
    Tokenizer,
)


class CoreServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        (self.base_dir / "Shukongdashi" / "demo").mkdir(parents=True, exist_ok=True)
        (self.base_dir / "Shukongdashi" / "demo" / "stopwords.txt").write_text("的\n了\n", encoding="utf-8")
        (self.base_dir / "Shukongdashi" / "demo" / "zhuyu.txt").write_text("主轴\n刀库\n", encoding="utf-8")
        (self.base_dir / "Shukongdashi" / "demo" / "fencidian.txt").write_text("换刀\n报警\n", encoding="utf-8")

        self.seed_path = self.base_dir / "guzhanganli.sql"
        self.seed_path.write_text(
            "\n".join(
                [
                    "INSERT INTO `guzhanganli` VALUES ('主轴联轴器损坏', '开机后主轴异响，报警', '更换联轴器后恢复正常。');",
                    "INSERT INTO `guzhanganli` VALUES ('刀库位置偏移', '自动换刀卡住，主轴报警', '调整刀库四零位置参数后恢复正常。');",
                ]
            ),
            encoding="utf-8",
        )

        self.settings = RuntimeSettings(
            base_dir=self.base_dir,
            seed_sql_path=self.seed_path,
            case_db_path=self.base_dir / "Shukongdashi" / "runtime" / "fault_cases.sqlite3",
            demo_dir=self.base_dir / "Shukongdashi" / "demo",
            online_search_enabled=False,
            web_search_timeout_seconds=8,
            cors_allow_origin="*",
            cors_allow_methods="GET,POST,OPTIONS",
            cors_allow_headers="Content-Type,Authorization,X-Requested-With",
            neo4j_uri="",
            neo4j_user="",
            neo4j_password="",
        )

        self.resources = ResourceCatalog(self.settings)
        self.tokenizer = Tokenizer(self.resources)
        self.scorer = SimilarityScorer(self.tokenizer)
        self.classifier = HybridFaultTextClassifier(self.resources)
        self.parser = FaultTextParser(self.tokenizer, self.classifier, self.resources)
        self.case_repository = SQLiteFaultCaseRepository(
            db_path=self.settings.case_db_path,
            seed_loader=SqlSeedLoader(self.settings.seed_sql_path),
            scorer=self.scorer,
        )
        self.graph_repository = NullGraphKnowledgeRepository()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_repository_seeds_cases(self) -> None:
        cases = self.case_repository.list_cases()
        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[0].cause, "主轴联轴器损坏")

    def test_diagnosis_falls_back_to_case_repository(self) -> None:
        service = DiagnosisService(
            parser=self.parser,
            scorer=self.scorer,
            case_repository=self.case_repository,
            graph_repository=self.graph_repository,
        )

        result = service.diagnose(
            FaultQuery(
                brand="FANUC",
                alarm_code="ALM401",
                question="开机后主轴异响并报警",
            )
        )
        self.assertTrue(result.candidates)
        self.assertEqual(result.candidates[0].cause, "主轴联轴器损坏")

    def test_completion_and_qa_use_case_repository(self) -> None:
        completion_service = CompletionService(self.case_repository, self.graph_repository)
        qa_service = QuestionAnsweringService(
            scorer=self.scorer,
            case_repository=self.case_repository,
            graph_repository=self.graph_repository,
        )

        completion = completion_service.complete("自动换")
        self.assertIn("自动换刀卡住，主轴报警", completion.suggestions)

        answer = qa_service.answer("主轴联轴器损坏会引起哪些现象？")
        self.assertIn("开机后主轴异响，报警", answer.answers)

    def test_duplicate_feedback_is_deduplicated(self) -> None:
        record = FeedbackRecord(
            brand="FANUC",
            model="0M",
            alarm_code="ALM401",
            question="开机后主轴异响并报警",
            selected_signals=["主轴异响"],
            cause="主轴联轴器损坏",
            answer="更换联轴器后恢复正常。",
        )

        first = self.case_repository.save_feedback(record)
        second = self.case_repository.save_feedback(record)

        self.assertEqual(first.id, second.id)
        self.assertEqual(self.case_repository.case_count(), 3)

    def test_diagnosis_merges_graph_and_case_candidates(self) -> None:
        service = DiagnosisService(
            parser=self.parser,
            scorer=self.scorer,
            case_repository=self.case_repository,
            graph_repository=FakeGraphRepository(),
        )

        result = service.diagnose(
            FaultQuery(
                question="开机后主轴异响并报警",
                related_symptoms=["开机后主轴异响，报警"],
            )
        )

        top_candidate = result.candidates[0]
        self.assertEqual(top_candidate.cause, "主轴联轴器损坏")
        self.assertIn("graph", top_candidate.source)
        self.assertIn("case_repo", top_candidate.source)


class FakeGraphRepository(GraphKnowledgeRepository):
    def available(self) -> bool:
        return True

    def list_entities(self, label: str) -> list[str]:
        if label == "Xianxiang":
            return ["开机后主轴异响，报警"]
        return []

    def find_related_from(self, entity: str, relation: str) -> list[str]:
        if entity == "开机后主轴异响，报警" and relation == "间接原因":
            return ["主轴联轴器损坏"]
        return []

    def find_related_to(self, entity: str, relation: str) -> list[str]:
        return []

    def count_related_to(self, entity: str, relation: str) -> int:
        return 1

    def search_descriptions(self, fragment: str, limit: int = 5) -> list[str]:
        return []

    def upsert_feedback(self, parsed: ParsedFaultText, record: FeedbackRecord) -> bool:
        return True


HAS_DJANGO = importlib.util.find_spec("django") is not None

if HAS_DJANGO:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Shukongdashi.settings")
    import django

    django.setup()

    from io import StringIO

    from django.core.management import call_command
    from django.test import RequestFactory

    from Shukongdashi.api_views import DiagnosisView, DocsView


@unittest.skipUnless(HAS_DJANGO, "django is not installed")
class ApiViewTests(unittest.TestCase):
    def test_diagnosis_view_accepts_json_post(self) -> None:
        request = RequestFactory().post(
            "/qa",
            data=json.dumps(
                {
                    "question": "开机后主轴异响并报警",
                    "pinpai": "FANUC",
                    "relationList": ["主轴异响", "报警"],
                }
            ),
            content_type="application/json",
        )

        diagnosis_result = DiagnosisCandidate(
            cause="主轴联轴器损坏",
            answers=["更换联轴器后恢复正常。"],
            score=0.9,
            reasoning_steps=[
                ReasoningStep(
                    entity1="主轴异响",
                    rel="案例匹配",
                    entity2="主轴联轴器损坏",
                    entity1_type="现象",
                    entity2_type="最终原因",
                )
            ],
            source="case_repo",
        )
        fake_result = type(
            "FakeDiagnosisResult",
            (),
            {
                "candidates": [diagnosis_result],
                "to_dict": lambda self: {"list": [diagnosis_result.to_dict()]},
            },
        )()
        fake_container = type(
            "FakeContainer",
            (),
            {
                "diagnosis_service": type(
                    "FakeDiagnosisService",
                    (),
                    {"diagnose": lambda self, query: fake_result},
                )()
            },
        )()

        with patch("Shukongdashi.api_views.get_container", return_value=fake_container):
            response = DiagnosisView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(payload["code"], 0)
        self.assertEqual(payload["data"]["list"][0]["yuanyin"], "主轴联轴器损坏")

    def test_options_response_contains_cors_headers(self) -> None:
        request = RequestFactory().options("/qa")
        fake_container = type(
            "FakeContainer",
            (),
            {
                "settings": type(
                    "FakeSettings",
                    (),
                    {
                        "cors_allow_origin": "*",
                        "cors_allow_methods": "GET,POST,OPTIONS",
                        "cors_allow_headers": "Content-Type,Authorization,X-Requested-With",
                    },
                )()
            },
        )()

        with patch("Shukongdashi.api_views.get_container", return_value=fake_container):
            response = DiagnosisView.as_view()(request)

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    def test_docs_view_returns_endpoint_catalog(self) -> None:
        request = RequestFactory().get("/docs")
        response = DocsView.as_view()(request)
        payload = json.loads(response.content.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["data"]["service"], "Shukongdashi API")
        self.assertTrue(any(item["path"] == "/qa" for item in payload["data"]["endpoints"]))


@unittest.skipUnless(HAS_DJANGO, "django is not installed")
class ManagementCommandTests(unittest.TestCase):
    def test_system_doctor_outputs_json(self) -> None:
        output = StringIO()
        call_command("system_doctor", stdout=output)
        payload = json.loads(output.getvalue())
        self.assertIn("case_database", payload)
        self.assertIn("classifier_backend", payload)


if __name__ == "__main__":
    unittest.main()
