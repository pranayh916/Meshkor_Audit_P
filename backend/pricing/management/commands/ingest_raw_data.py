"""Discover and process configured raw inputs through the production pipeline."""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Run the configured source ingestion and comparison pipeline."

    def handle(self, *args, **options):
        from pipeline.run_all import main

        result = main()
        if result:
            raise CommandError("One or more ingestion stages failed; see the stage diagnostics above.")
        self.stdout.write(self.style.SUCCESS("Configured raw data ingestion completed."))
