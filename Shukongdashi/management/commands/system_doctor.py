import json

from django.core.management.base import BaseCommand

from Shukongdashi.core.container import get_container


class Command(BaseCommand):
    help = "Print current runtime and dependency status for diagnostics."

    def handle(self, *args, **options):
        container = get_container()
        payload = {
            "case_database": str(container.case_repository.database_path),
            "case_count": container.case_repository.case_count(),
            "seed_sql_path": str(container.settings.seed_sql_path),
            "demo_dir": str(container.settings.demo_dir),
            "graph_enabled": container.graph_repository.available(),
            "online_search_enabled": container.settings.online_search_enabled,
            "web_search_timeout_seconds": container.settings.web_search_timeout_seconds,
            "cors_allow_origin": container.settings.cors_allow_origin,
            "classifier_backend": (
                "cnn" if getattr(container.classifier, "_cnn_backend", None) is not None else "heuristic"
            ),
        }
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
