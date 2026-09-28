import json
import os
import unittest

from career.tests.test_fixture_vocabulary import REFERENCE

# Only reachable when both repos are checked out side by side, which is the local layout.
FRONTEND_COPY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))),
    'frontend', 'eslint-rules', 'substitutes.json',
)


class SubstitutesReferenceTests(unittest.TestCase):
    def test_the_canonical_list_has_every_section_its_readers_index(self):
        with open(REFERENCE, encoding='utf-8') as handle:
            reference = json.load(handle)
        for key in ('companies', 'people', 'titles', 'locations', 'dates', 'figures'):
            self.assertIn(key, reference)

    def test_the_frontend_copy_matches_this_one(self):
        if not os.path.exists(FRONTEND_COPY):
            self.skipTest('the frontend repo is not checked out beside this one')
        with open(REFERENCE, encoding='utf-8') as handle:
            canonical = json.load(handle)
        with open(FRONTEND_COPY, encoding='utf-8') as handle:
            self.assertEqual(
                json.load(handle), canonical,
                'frontend/eslint-rules/substitutes.json has drifted; copy this file over it',
            )
