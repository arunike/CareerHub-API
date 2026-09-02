import re
import unittest
from pathlib import Path

from availability.serializers import UserSettingsSerializer

REGISTRY = (
    Path(__file__).resolve().parents[4]
    / 'frontend'
    / 'src'
    / 'constants'
    / 'navigationItems.ts'
)


def registry_keys():
    """Every key declared in the frontend NAV_REGISTRY."""
    source = REGISTRY.read_text(encoding='utf-8')
    body = source.split('export const NAV_REGISTRY = [', 1)[1].split('] as const;', 1)[0]
    return {match.group(1) for match in re.finditer(r"key:\s*'([^']+)'", body)}


@unittest.skipUnless(REGISTRY.exists(), 'frontend checkout not present')
class NavigationKeyParityTests(unittest.TestCase):
    """The API rejects a toolbar key it does not know, so its list must track the frontend's."""

    def test_every_frontend_tab_is_accepted_by_the_api(self):
        allowed = UserSettingsSerializer.MOBILE_TOOLBAR_ROUTE_KEYS
        self.assertEqual(sorted(registry_keys() - allowed), [])

    def test_the_api_accepts_nothing_the_frontend_does_not_offer(self):
        # __smart__ is a synthetic slot with no sidebar entry, so it is the only extra.
        extra = UserSettingsSerializer.MOBILE_TOOLBAR_ROUTE_KEYS - registry_keys()
        self.assertEqual(sorted(extra), ['__smart__'])

    def test_income_is_accepted(self):
        self.assertIn('/income', UserSettingsSerializer.MOBILE_TOOLBAR_ROUTE_KEYS)
