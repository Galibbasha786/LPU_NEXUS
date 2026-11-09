from django.core.management.base import BaseCommand

from core.mongo import init_indexes


class Command(BaseCommand):
    help = 'Create or verify the MongoDB indexes used by LPU Nexus.'

    def handle(self, *args, **options):
        init_indexes()
        self.stdout.write(self.style.SUCCESS('MongoDB indexes are ready.'))
