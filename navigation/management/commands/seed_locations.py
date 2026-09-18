# navigation/management/commands/seed_locations.py
from django.core.management.base import BaseCommand
from core.mongo import locations
from core.utils import now


# All coordinates as [longitude, latitude] (GeoJSON order)
# Get exact values from Google Maps: right-click → copy coords (gives lat,lon → swap them)
LPU_LOCATIONS = [
    # Gates
    {"name": "Main Gate (Gate 1)", "coordinates": [75.705252, 31.255992], "category": "gate"},
    {"name": "Gate 2", "coordinates": [75.706120, 31.255010], "category": "gate"},
    {"name": "Gate 3", "coordinates": [75.706850, 31.254200], "category": "gate"},

    # Core facilities
    {"name": "Baldev Raj Mittal Unipolis", "coordinates": [75.704800, 31.256000], "category": "facility"},
    {"name": "Shanti Devi Mittal Auditorium", "coordinates": [75.704200, 31.256500], "category": "facility"},
    {"name": "Central Library (Block 37)", "coordinates": [75.703900, 31.255400], "category": "academic"},
    {"name": "Uni Mall", "coordinates": [75.704500, 31.256200], "category": "shopping"},
    {"name": "Uni Hospital (Health Center)", "coordinates": [75.705500, 31.257000], "category": "medical"},
    {"name": "Administrative Block (Block 29)", "coordinates": [75.704200, 31.254500], "category": "admin"},

    # Academic
    {"name": "Block 34 (CSE)", "coordinates": [75.703700, 31.253600], "category": "academic"},
    {"name": "Block 33", "coordinates": [75.703550, 31.253900], "category": "academic"},
    {"name": "Block 32 (ECE)", "coordinates": [75.703300, 31.254300], "category": "academic"},
    {"name": "Block 38", "coordinates": [75.703100, 31.254800], "category": "academic"},
    {"name": "Block 36 (Agriculture)", "coordinates": [75.703200, 31.255200], "category": "academic"},
    {"name": "Block 55", "coordinates": [75.709000, 31.251000], "category": "academic"},
    {"name": "Block 56", "coordinates": [75.709200, 31.250500], "category": "academic"},
    {"name": "Block 25", "coordinates": [75.701500, 31.255200], "category": "academic"},
    {"name": "Block 27", "coordinates": [75.702000, 31.255000], "category": "academic"},
    {"name": "Block 14 (Architecture)", "coordinates": [75.701800, 31.256500], "category": "academic"},

    # Hostels
    {"name": "Boys Hostel 1 (BH-1)", "coordinates": [75.706500, 31.253000], "category": "hostel"},
    {"name": "Boys Hostel 2 (BH-2)", "coordinates": [75.707000, 31.252500], "category": "hostel"},
    {"name": "Boys Hostel 3 (BH-3)", "coordinates": [75.707500, 31.252000], "category": "hostel"},
    {"name": "Boys Hostel 4 (BH-4)", "coordinates": [75.708000, 31.251500], "category": "hostel"},
    {"name": "Boys Hostel 5 (BH-5)", "coordinates": [75.708500, 31.251000], "category": "hostel"},
    {"name": "Girls Hostel 1 (GH-1)", "coordinates": [75.701000, 31.252000], "category": "hostel"},
    {"name": "Girls Hostel 2 (GH-2)", "coordinates": [75.701500, 31.251500], "category": "hostel"},
    {"name": "Girls Hostel 3 (GH-3)", "coordinates": [75.702000, 31.251000], "category": "hostel"},
    {"name": "Block 26 (Hostel)", "coordinates": [75.701000, 31.255000], "category": "hostel"},

    # Sports
    {"name": "Indoor Stadium / Sports Complex", "coordinates": [75.708000, 31.255000], "category": "sports"},
    {"name": "Swimming Pool", "coordinates": [75.708200, 31.254800], "category": "sports"},
    {"name": "Cricket Ground", "coordinates": [75.707500, 31.256000], "category": "sports"},
    {"name": "Basketball Courts", "coordinates": [75.707800, 31.255500], "category": "sports"},

    # Food & utility
    {"name": "Food Court (Near Unipolis)", "coordinates": [75.704600, 31.255800], "category": "food"},
    {"name": "Main Canteen", "coordinates": [75.704000, 31.254000], "category": "food"},
    {"name": "SBI ATM Zone", "coordinates": [75.703500, 31.254200], "category": "atm"},
    {"name": "Post Office", "coordinates": [75.703600, 31.254400], "category": "facility"},
]


class Command(BaseCommand):
    help = "Seed LPU campus locations for navigation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing locations before seeding",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            result = locations().delete_many({})
            self.stdout.write(self.style.WARNING(
                f"🗑️  Deleted {result.deleted_count} existing locations"
            ))

        # Geospatial index
        locations().create_index([("coordinates", "2dsphere")])

        created = 0
        skipped = 0

        for loc in LPU_LOCATIONS:
            existing = locations().find_one({"name": loc["name"]})
            if existing:
                self.stdout.write(self.style.WARNING(f"⚠️  {loc['name']} exists"))
                skipped += 1
                continue

            # ✅ Store BOTH formats — top-level for logic, GeoJSON for indexing
            doc = {
                "name": loc["name"],
                "coordinates": loc["coordinates"],           # ← what services.py expects
                "location": {                                 # ← for future geospatial queries
                    "type": "Point",
                    "coordinates": loc["coordinates"],
                },
                "category": loc["category"],
                "created_at": now(),
            }
            locations().insert_one(doc)
            self.stdout.write(self.style.SUCCESS(f"✅ {loc['name']}"))
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f"\n🎉 Seeded {created} new locations, skipped {skipped}."
        ))