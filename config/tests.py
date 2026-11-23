from datetime import datetime, timedelta, timezone as datetime_timezone

from django.conf import settings
from django.test import SimpleTestCase
from django.utils import timezone


class CostaRicaTimezoneTests(SimpleTestCase):
    def test_project_uses_costa_rica_timezone(self):
        self.assertEqual(settings.TIME_ZONE, "America/Costa_Rica")
        self.assertEqual(timezone.get_current_timezone_name(), "America/Costa_Rica")

    def test_utc_datetime_is_converted_to_utc_minus_six(self):
        utc_time = datetime(2026, 11, 23, 12, 30, tzinfo=datetime_timezone.utc)

        costa_rica_time = timezone.localtime(utc_time)

        self.assertEqual(costa_rica_time.utcoffset(), timedelta(hours=-6))
        self.assertEqual(
            costa_rica_time.isoformat(),
            "2026-11-23T06:30:00-06:00",
        )
