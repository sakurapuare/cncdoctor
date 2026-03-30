from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from .models import FaultQuery, ParsedFaultText


def normalize_text(value: str) -> str:
    value = (value or "").strip()
    value = value.replace("\u3000", " ")
    value = re.sub(r"\s+", "", value)
    return value


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = normalize_text(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


@dataclass(frozen=True)
class RuntimeSettings:
    base_dir: Path
    seed_sql_path: Path
    case_db_path: Path
    demo_dir: Path
    online_search_enabled: bool
    web_search_timeout_seconds: int
    cors_allow_origin: str
    cors_allow_methods: str
    cors_allow_headers: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str

    @classmethod
    def from_base_dir(cls, base_dir: Path) -> RuntimeSettings:
        import os

        def _resolve_path(name: str, default: Path) -> Path:
            raw = os.getenv(name, "").strip()
            if not raw:
                return default
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = base_dir / candidate
            return candidate

        return cls(
            base_dir=base_dir,
            seed_sql_path=_resolve_path("APP_CASE_SQL_SEED", base_dir / "guzhanganli.sql"),
            case_db_path=_resolve_path(
                "APP_CASE_DB_PATH",
                base_dir / "Shukongdashi" / "runtime" / "fault_cases.sqlite3",
            ),
            demo_dir=_resolve_path("APP_DEMO_DIR", base_dir / "Shukongdashi" / "demo"),
            online_search_enabled=os.getenv("APP_ENABLE_ONLINE_SEARCH", "1") != "0",
            web_search_timeout_seconds=max(int(os.getenv("APP_WEB_SEARCH_TIMEOUT", "8")), 1),
            cors_allow_origin=os.getenv("APP_CORS_ALLOW_ORIGIN", "*").strip() or "*",
            cors_allow_methods=os.getenv(
                "APP_CORS_ALLOW_METHODS",
                "GET,POST,OPTIONS",
            ).strip(),
            cors_allow_headers=os.getenv(
                "APP_CORS_ALLOW_HEADERS",
                "Content-Type,Authorization,X-Requested-With",
            ).strip(),
            neo4j_uri=os.getenv("APP_NEO4J_URI", "").strip(),
            neo4j_user=os.getenv("APP_NEO4J_USER", "").strip(),
            neo4j_password=os.getenv("APP_NEO4J_PASSWORD", "").strip(),
        )


class ResourceCatalog:
    def __init__(self, settings: RuntimeSettings) -> None:
        self._settings = settings

    @cached_property
    def stopwords(self) -> set[str]:
        return self._load_lines(self._settings.demo_dir / "stopwords.txt")

    @cached_property
    def fault_parts(self) -> set[str]:
        return self._load_lines(self._settings.demo_dir / "zhuyu.txt")

    @cached_property
    def user_dictionary_path(self) -> Path:
        return self._settings.demo_dir / "fencidian.txt"

    @cached_property
    def operation_keywords(self) -> set[str]:
        defaults = {
            "开机",
            "关机",
            "启动",
            "换刀",
            "加工",
            "运行",
            "执行",
            "手动",
            "移动",
            "装卸",
            "夹紧",
            "回零",
            "调试",
            "刀库",
            "主轴",
            "进给",
        }
        words = set(defaults)
        words.update(word for word in self._load_lines(self.user_dictionary_path) if len(word) >= 2)
        return words

    def _load_lines(self, path: Path) -> set[str]:
        if not path.exists():
            return set()
        with path.open("r", encoding="utf-8") as handle:
            return {
                line.strip().encode("utf-8").decode("utf-8-sig") for line in handle if line.strip()
            }


class Tokenizer:
    def __init__(self, resources: ResourceCatalog) -> None:
        self._resources = resources
        self._jieba = self._try_load_jieba()

    def tokenize(self, text: str) -> list[str]:
        text = normalize_text(text)
        if not text:
            return []
        if self._jieba is not None:
            return [
                token
                for token in self._jieba.cut(text)
                if token and token not in self._resources.stopwords
            ]
        tokens = re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", text)
        return [token for token in tokens if token and token not in self._resources.stopwords]

    def sentence_split(self, text: str) -> list[str]:
        text = normalize_text(text)
        if not text:
            return []
        parts = re.split(r"[。；;.!！？?]", text)
        return [part for part in parts if part]

    def clause_split(self, text: str) -> list[str]:
        pieces = re.split(r"[，,、]", text)
        return [piece for piece in pieces if piece]

    def _try_load_jieba(self):
        try:
            import logging

            import jieba
        except ModuleNotFoundError:
            return None

        if hasattr(jieba, "setLogLevel"):
            jieba.setLogLevel(logging.WARNING)
        dictionary_path = self._resources.user_dictionary_path
        if dictionary_path.exists():
            with dictionary_path.open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    word = raw_line.strip().split(" ", 1)[0]
                    if word:
                        jieba.add_word(word)
        return jieba


class SimilarityScorer:
    def __init__(self, tokenizer: Tokenizer) -> None:
        self._tokenizer = tokenizer
        self._token_cache: dict[str, set[str]] = {}

    def score(self, left: str, right: str) -> float:
        from difflib import SequenceMatcher

        normalized_left = normalize_text(left)
        normalized_right = normalize_text(right)
        if not normalized_left or not normalized_right:
            return 0.0

        seq_ratio = SequenceMatcher(None, normalized_left, normalized_right).ratio()
        left_tokens = self._token_set(normalized_left)
        right_tokens = self._token_set(normalized_right)
        union = left_tokens | right_tokens
        token_ratio = len(left_tokens & right_tokens) / len(union) if union else 0.0

        left_chars = set(normalized_left)
        right_chars = set(normalized_right)
        char_union = left_chars | right_chars
        char_ratio = len(left_chars & right_chars) / len(char_union) if char_union else 0.0

        return round((seq_ratio * 0.5) + (token_ratio * 0.3) + (char_ratio * 0.2), 4)

    def _token_set(self, text: str) -> set[str]:
        if text not in self._token_cache:
            self._token_cache[text] = set(self._tokenizer.tokenize(text))
        return self._token_cache[text]


class TextClassifier:
    def classify(self, segment: str) -> str:
        raise NotImplementedError


class HybridFaultTextClassifier(TextClassifier):
    def __init__(self, resources: ResourceCatalog) -> None:
        self._resources = resources
        self._cnn_backend = self._load_cnn_backend()

    def classify(self, segment: str) -> str:
        cleaned = normalize_text(segment)
        if not cleaned:
            return "故障现象"

        if self._cnn_backend is not None:
            try:
                return str(self._cnn_backend.predict(cleaned))
            except Exception:
                pass

        if re.search(
            r"(FANUC|SIEMENS|MITSUBISHI|GSK|KND|HNC|HASS|840D|802D|0M|0T|6M|MATE)",
            cleaned,
            re.IGNORECASE,
        ):
            return "机床类型"
        if re.search(r"[A-Z]{1,6}\d{2,6}", cleaned):
            return "故障现象"
        if any(keyword in cleaned for keyword in self._resources.operation_keywords):
            return "执行操作"
        return "故障现象"

    def _load_cnn_backend(self):
        try:
            from Shukongdashi.test_my.test_cnnrnn.predict import CnnModel
        except Exception:
            return None

        try:
            return CnnModel()
        except Exception:
            return None


class FaultTextParser:
    def __init__(
        self,
        tokenizer: Tokenizer,
        classifier: TextClassifier,
        resources: ResourceCatalog,
    ) -> None:
        self._tokenizer = tokenizer
        self._classifier = classifier
        self._resources = resources

    def parse(self, query: FaultQuery) -> ParsedFaultText:
        merged = query.merged_text()
        machine_fragments: list[str] = [query.brand, query.model]
        operations: list[str] = []
        symptoms: list[str] = []

        for sentence in self._tokenizer.sentence_split(merged):
            for clause in self._tokenizer.clause_split(sentence):
                label = self._classifier.classify(clause)
                if label == "机床类型":
                    machine_fragments.append(clause)
                elif label == "执行操作":
                    operations.append(clause)
                else:
                    symptoms.append(clause)

        parts = self._extract_parts(symptoms)
        alarm_codes = self._extract_alarm_codes(merged, query.alarm_code)
        if query.question and not symptoms:
            symptoms = [query.question]

        return ParsedFaultText(
            machine_fragments=unique_preserve_order(machine_fragments),
            operations=unique_preserve_order(operations),
            symptoms=unique_preserve_order(symptoms),
            parts=unique_preserve_order(parts),
            alarm_codes=unique_preserve_order(alarm_codes),
        )

    def _extract_alarm_codes(self, merged: str, explicit_alarm_code: str) -> list[str]:
        alarm_codes = re.findall(r"[A-Z]{1,6}\d{2,6}", merged.upper())
        if explicit_alarm_code:
            alarm_codes.append(explicit_alarm_code.upper())
        return alarm_codes

    def _extract_parts(self, symptoms: Iterable[str]) -> list[str]:
        parts: list[str] = []
        for symptom in symptoms:
            for token in self._tokenizer.tokenize(symptom):
                if token in self._resources.fault_parts:
                    parts.append(token)
        return parts
