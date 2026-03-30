from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .models import FaultCase, FeedbackRecord
from .text import (
    ParsedFaultText,
    RuntimeSettings,
    SimilarityScorer,
    normalize_text,
    unique_preserve_order,
)


class SqlSeedLoader:
    INSERT_PREFIX = "INSERT INTO `guzhanganli` VALUES "

    def __init__(self, sql_path: Path) -> None:
        self._sql_path = sql_path

    def iter_cases(self) -> Iterable[FaultCase]:
        if not self._sql_path.exists():
            return

        statement_buffer: list[str] = []
        with self._sql_path.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not statement_buffer and not line.startswith(self.INSERT_PREFIX):
                    continue
                if line:
                    statement_buffer.append(line)
                if not line.endswith(";"):
                    continue
                case = self._parse_insert_statement(" ".join(statement_buffer))
                statement_buffer.clear()
                if case is not None:
                    yield case

    def _parse_insert_statement(self, line: str) -> FaultCase | None:
        payload = line[len(self.INSERT_PREFIX) :].strip()
        if payload.endswith(";"):
            payload = payload[:-1]
        if payload.startswith("(") and payload.endswith(")"):
            payload = payload[1:-1]

        row = self._split_sql_values(payload)
        if row is None:
            return None

        if len(row) < 3:
            return None

        return FaultCase(
            id=None,
            cause=row[0].strip(),
            phenomenon=row[1].strip(),
            analysis=row[2].strip(),
            source="seed",
            created_at=self._seed_timestamp(),
        )

    def _seed_timestamp(self) -> str:
        return datetime(2019, 7, 25, 16, 49, 17, tzinfo=timezone.utc).isoformat()

    def _split_sql_values(self, payload: str) -> list[str] | None:
        fields: list[str] = []
        current: list[str] = []
        in_string = False
        escaped = False

        for char in payload:
            if escaped:
                current.append(self._unescape_char(char))
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == "'":
                in_string = not in_string
                continue
            if char == "," and not in_string:
                fields.append("".join(current).strip())
                current = []
                continue
            current.append(char)

        if escaped or in_string:
            return None

        fields.append("".join(current).strip())
        return fields

    def _unescape_char(self, char: str) -> str:
        mapping = {
            "r": "\r",
            "n": "\n",
            "t": "\t",
            "'": "'",
            '"': '"',
            "\\": "\\",
            "0": "\0",
        }
        return mapping.get(char, char)


class SQLiteFaultCaseRepository:
    def __init__(
        self,
        db_path: Path,
        seed_loader: SqlSeedLoader,
        scorer: SimilarityScorer,
    ) -> None:
        self._db_path = db_path
        self._seed_loader = seed_loader
        self._scorer = scorer
        self._case_cache: list[FaultCase] | None = None
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_database()

    def list_cases(self) -> list[FaultCase]:
        if self._case_cache is not None:
            return list(self._case_cache)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, cause, phenomenon, analysis, brand, model, alarm_code,
                       selected_signals, source, created_at
                FROM fault_cases
                ORDER BY id ASC
                """
            ).fetchall()
        self._case_cache = [self._row_to_case(row) for row in rows]
        return list(self._case_cache)

    def case_count(self) -> int:
        if self._case_cache is not None:
            return len(self._case_cache)
        with closing(self._connect()) as connection:
            return int(connection.execute("SELECT COUNT(1) FROM fault_cases").fetchone()[0])

    @property
    def database_path(self) -> Path:
        return self._db_path

    def search_similar(self, query_text: str, limit: int = 5) -> list[tuple[FaultCase, float]]:
        normalized = normalize_text(query_text)
        if not normalized:
            return []

        scored_cases: list[tuple[FaultCase, float]] = []
        for case in self.list_cases():
            score = self._scorer.score(normalized, case.searchable_text())
            if normalized in normalize_text(case.searchable_text()):
                score = max(score, 0.85)
            if score >= 0.18:
                scored_cases.append((case, score))
        scored_cases.sort(key=lambda item: item[1], reverse=True)
        return scored_cases[:limit]

    def answers_for_cause(self, cause: str, limit: int = 5) -> list[str]:
        normalized_cause = normalize_text(cause)
        if not normalized_cause:
            return []

        matched: list[tuple[float, str]] = []
        for case in self.list_cases():
            score = self._scorer.score(normalized_cause, case.cause)
            if normalized_cause == normalize_text(case.cause):
                score = 1.0
            if score >= 0.52:
                matched.append((score, case.analysis))
        matched.sort(key=lambda item: item[0], reverse=True)
        return unique_preserve_order(answer for _, answer in matched[:limit])

    def search_prefix(self, fragment: str, limit: int = 5) -> list[str]:
        normalized = normalize_text(fragment)
        if not normalized:
            return []

        suggestions: list[tuple[float, str]] = []
        for case in self.list_cases():
            for candidate in (case.phenomenon, case.cause):
                candidate_text = normalize_text(candidate)
                if not candidate_text:
                    continue
                if candidate_text.startswith(normalized):
                    suggestions.append((1.0, candidate))
                elif normalized in candidate_text:
                    suggestions.append((0.8, candidate))
                else:
                    score = self._scorer.score(normalized, candidate_text)
                    if score >= 0.3:
                        suggestions.append((score, candidate))
        suggestions.sort(key=lambda item: item[0], reverse=True)
        return unique_preserve_order(candidate for _, candidate in suggestions[:limit])

    def cases_for_cause(self, cause: str, limit: int = 5) -> list[FaultCase]:
        normalized_cause = normalize_text(cause)
        if not normalized_cause:
            return []

        matched: list[tuple[float, FaultCase]] = []
        for case in self.list_cases():
            score = self._scorer.score(normalized_cause, case.cause)
            if normalized_cause == normalize_text(case.cause):
                score = 1.0
            if score >= 0.5:
                matched.append((score, case))
        matched.sort(key=lambda item: item[0], reverse=True)
        return [case for _, case in matched[:limit]]

    def save_feedback(self, record: FeedbackRecord) -> FaultCase:
        cause = normalize_text(record.cause) or "待确认故障原因"
        phenomenon = "，".join(
            part
            for part in [
                normalize_text(record.question),
                "；".join(unique_preserve_order(record.selected_signals)),
            ]
            if part
        )
        now = datetime.now(timezone.utc).isoformat()

        selected_signals = "|".join(unique_preserve_order(record.selected_signals))

        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO fault_cases (
                    cause, phenomenon, analysis, brand, model, alarm_code,
                    selected_signals, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cause,
                    phenomenon or "用户反馈案例",
                    record.answer.strip(),
                    record.brand.strip(),
                    record.model.strip(),
                    record.alarm_code.strip(),
                    selected_signals,
                    "feedback",
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT id, cause, phenomenon, analysis, brand, model, alarm_code,
                       selected_signals, source, created_at
                FROM fault_cases
                WHERE cause = ? AND phenomenon = ? AND analysis = ?
                LIMIT 1
                """,
                (cause, phenomenon or "用户反馈案例", record.answer.strip()),
            ).fetchone()
            connection.commit()
        self._invalidate_cache()

        if row is not None:
            return self._row_to_case(row)

        return FaultCase(
            id=int(cursor.lastrowid) if cursor.lastrowid else None,
            cause=cause,
            phenomenon=phenomenon or "用户反馈案例",
            analysis=record.answer.strip(),
            brand=record.brand.strip(),
            model=record.model.strip(),
            alarm_code=record.alarm_code.strip(),
            selected_signals=selected_signals,
            source="feedback",
            created_at=now,
        )

    def _ensure_database(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS fault_cases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cause TEXT NOT NULL,
                    phenomenon TEXT NOT NULL,
                    analysis TEXT NOT NULL,
                    brand TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    alarm_code TEXT NOT NULL DEFAULT '',
                    selected_signals TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'seed',
                    created_at TEXT NOT NULL,
                    UNIQUE (cause, phenomenon, analysis)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_fault_cases_cause ON fault_cases(cause)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_fault_cases_created_at ON fault_cases(created_at)"
            )
            case_count = connection.execute("SELECT COUNT(1) FROM fault_cases").fetchone()[0]
            if case_count == 0:
                self._seed_cases(connection)
            connection.commit()

    def _seed_cases(self, connection: sqlite3.Connection) -> None:
        for case in self._seed_loader.iter_cases():
            connection.execute(
                """
                INSERT OR IGNORE INTO fault_cases (
                    cause, phenomenon, analysis, brand, model, alarm_code,
                    selected_signals, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case.cause,
                    case.phenomenon,
                    case.analysis,
                    case.brand,
                    case.model,
                    case.alarm_code,
                    case.selected_signals,
                    case.source,
                    case.created_at or datetime.now(timezone.utc).isoformat(),
                ),
            )

    def _row_to_case(self, row: sqlite3.Row | tuple) -> FaultCase:
        return FaultCase(
            id=row[0],
            cause=row[1],
            phenomenon=row[2],
            analysis=row[3],
            brand=row[4],
            model=row[5],
            alarm_code=row[6],
            selected_signals=row[7],
            source=row[8],
            created_at=row[9],
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _invalidate_cache(self) -> None:
        self._case_cache = None

    def rebuild_from_seed(self) -> int:
        if self._db_path.exists():
            self._db_path.unlink()
        wal_path = self._db_path.with_suffix(self._db_path.suffix + "-wal")
        shm_path = self._db_path.with_suffix(self._db_path.suffix + "-shm")
        if wal_path.exists():
            wal_path.unlink()
        if shm_path.exists():
            shm_path.unlink()
        self._invalidate_cache()
        self._ensure_database()
        return self.case_count()


class GraphKnowledgeRepository:
    def available(self) -> bool:
        raise NotImplementedError

    def list_entities(self, label: str) -> list[str]:
        raise NotImplementedError

    def find_related_from(self, entity: str, relation: str) -> list[str]:
        raise NotImplementedError

    def find_related_to(self, entity: str, relation: str) -> list[str]:
        raise NotImplementedError

    def count_related_to(self, entity: str, relation: str) -> int:
        raise NotImplementedError

    def search_descriptions(self, fragment: str, limit: int = 5) -> list[str]:
        raise NotImplementedError

    def upsert_feedback(self, parsed: ParsedFaultText, record: FeedbackRecord) -> bool:
        raise NotImplementedError


class NullGraphKnowledgeRepository(GraphKnowledgeRepository):
    def available(self) -> bool:
        return False

    def list_entities(self, label: str) -> list[str]:
        return []

    def find_related_from(self, entity: str, relation: str) -> list[str]:
        return []

    def find_related_to(self, entity: str, relation: str) -> list[str]:
        return []

    def count_related_to(self, entity: str, relation: str) -> int:
        return 0

    def search_descriptions(self, fragment: str, limit: int = 5) -> list[str]:
        return []

    def upsert_feedback(self, parsed: ParsedFaultText, record: FeedbackRecord) -> bool:
        return False


class Neo4jKnowledgeRepository(GraphKnowledgeRepository):
    def __init__(self, settings: RuntimeSettings) -> None:
        self._settings = settings
        self._graph = self._connect()
        self._entity_cache: dict[str, list[str]] = {}

    def available(self) -> bool:
        return self._graph is not None

    def list_entities(self, label: str) -> list[str]:
        if label in self._entity_cache:
            return self._entity_cache[label]
        records = self._run(
            f"MATCH (n:{label}) RETURN n.title AS title",
        )
        values = [record["title"] for record in records if record.get("title")]
        self._entity_cache[label] = values
        return values

    def find_related_from(self, entity: str, relation: str) -> list[str]:
        records = self._run(
            """
            MATCH (n1 {title:$entity})-[rel {type:$relation}]->(n2)
            RETURN n2.title AS title
            """,
            entity=entity,
            relation=relation,
        )
        return [record["title"] for record in records if record.get("title")]

    def find_related_to(self, entity: str, relation: str) -> list[str]:
        records = self._run(
            """
            MATCH (n1)-[rel {type:$relation}]->(n2 {title:$entity})
            RETURN n1.title AS title
            """,
            entity=entity,
            relation=relation,
        )
        return [record["title"] for record in records if record.get("title")]

    def count_related_to(self, entity: str, relation: str) -> int:
        records = self._run(
            """
            MATCH (n)-[rel {type:$relation}]->(m {title:$entity})
            RETURN COUNT(n) AS total
            """,
            entity=entity,
            relation=relation,
        )
        if not records:
            return 0
        return int(records[0].get("total", 0))

    def search_descriptions(self, fragment: str, limit: int = 5) -> list[str]:
        records = self._run(
            """
            MATCH (n:Describe)
            WHERE n.title CONTAINS $fragment
            RETURN n.title AS title
            LIMIT $limit
            """,
            fragment=fragment,
            limit=limit,
        )
        return [record["title"] for record in records if record.get("title")]

    def upsert_feedback(self, parsed: ParsedFaultText, record: FeedbackRecord) -> bool:
        if not self.available():
            return False

        cause = normalize_text(record.cause) or "待确认故障原因"
        for symptom in parsed.symptoms:
            self._upsert_relation(symptom, "间接原因", cause, "Xianxiang", "Yuanyin")
        for operation in parsed.operations:
            for symptom in parsed.symptoms:
                self._upsert_relation(operation, "引起", symptom, "Caozuo", "Xianxiang")
        for alarm_code in parsed.alarm_codes:
            for symptom in parsed.symptoms:
                self._upsert_relation(symptom, "报警信息", alarm_code, "Xianxiang", "Errorid")
        for part in parsed.parts:
            for symptom in parsed.symptoms:
                self._upsert_relation(symptom, "故障部位", part, "Xianxiang", "GuzhangBuwei")
        return True

    def _upsert_relation(
        self,
        entity1: str,
        relation: str,
        entity2: str,
        label1: str,
        label2: str,
    ) -> None:
        self._run(
            f"""
            MERGE (a:{label1} {{title:$entity1}})
            MERGE (b:{label2} {{title:$entity2}})
            MERGE (a)-[r:{label1[0]}{label2[0]} {{type:$relation}}]->(b)
            RETURN r
            """,
            entity1=entity1,
            entity2=entity2,
            relation=relation,
        )
        self._entity_cache.pop(label1, None)
        self._entity_cache.pop(label2, None)

    def _run(self, query: str, **parameters):
        if self._graph is None:
            return []
        try:
            return self._graph.run(query, parameters).data()
        except TypeError:
            return self._graph.run(query, **parameters).data()
        except Exception:
            return []

    def _connect(self):
        if not (
            self._settings.neo4j_uri and self._settings.neo4j_user and self._settings.neo4j_password
        ):
            return None

        try:
            from py2neo import Graph
        except ModuleNotFoundError:
            return None

        try:
            return Graph(
                self._settings.neo4j_uri,
                auth=(self._settings.neo4j_user, self._settings.neo4j_password),
            )
        except TypeError:
            try:
                return Graph(
                    self._settings.neo4j_uri,
                    username=self._settings.neo4j_user,
                    password=self._settings.neo4j_password,
                )
            except Exception:
                return None
        except Exception:
            return None


def build_graph_repository(settings: RuntimeSettings) -> GraphKnowledgeRepository:
    repository = Neo4jKnowledgeRepository(settings)
    if repository.available():
        return repository
    return NullGraphKnowledgeRepository()
