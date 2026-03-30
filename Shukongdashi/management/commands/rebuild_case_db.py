from django.core.management.base import BaseCommand

from Shukongdashi.core.container import get_container


class Command(BaseCommand):
    help = "Rebuild the runtime fault-case SQLite database from the SQL seed."

    def handle(self, *args, **options):
        container = get_container()
        count = container.case_repository.rebuild_from_seed()
        self.stdout.write(
            self.style.SUCCESS(
                f"Rebuilt case database at {container.case_repository.database_path} with {count} records."
            )
        )
