"""Rebuild comparisons from the current validated Parquet inputs."""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Run the comparison builder using the current CMS scope and hospital rates."

    def handle(self, *args, **options):
        from pipeline.build_compare import main

        result = main()
        if result:
            raise CommandError("Comparison build failed; see the diagnostics above.")
        self.stdout.write(self.style.SUCCESS("Comparison build completed."))
