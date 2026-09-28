import json
import os
import re
import unittest

REFERENCE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'substitutes.json',
)


def load_reference():
    """The one canonical vocabulary; a missing file fails loudly rather than passing vacuously."""
    with open(REFERENCE, encoding='utf-8') as handle:
        return json.load(handle)


_REFERENCE = load_reference()
SUBSTITUTE_NAMES = set(_REFERENCE['companies']) | set(_REFERENCE['people'])
# Throwaway entities every fixture already spells this way: "Other Co", "Unused Company".
SCAFFOLD = re.compile(_REFERENCE['scaffoldSuffixPattern'])

# The shapes that name a real-world entity, as opposed to a label or a title.
PATTERNS = [
    re.compile(r"(?:Company|Contact)\.objects\.create\([^)]*?\bname=['\"]([^'\"]+)['\"]", re.S),
    re.compile(r"company__name=['\"]([^'\"]+)['\"]"),
    re.compile(r"\bcompany=['\"]([^'\"]+)['\"]"),
    re.compile(r"['\"]company['\"]:\s*['\"]([^'\"]+)['\"]"),
]

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))


def offending_names():
    """Every employer or person a fixture names that is neither a substitute nor scaffolding."""
    found = []
    for entry in sorted(os.listdir(TESTS_DIR)):
        if not entry.startswith('test_') or not entry.endswith('.py'):
            continue
        path = os.path.join(TESTS_DIR, entry)
        with open(path, encoding='utf-8') as handle:
            source = handle.read()
        for pattern in PATTERNS:
            for name in pattern.findall(source):
                if name in SUBSTITUTE_NAMES or SCAFFOLD.search(name):
                    continue
                found.append(f'{entry}: {name!r}')
    return found


class FixtureVocabularyTests(unittest.TestCase):
    def test_fixtures_name_only_substitutes_or_scaffolding(self):
        offenders = offending_names()
        self.assertEqual(
            offenders,
            [],
            'A fixture names an employer or person that is not in the AGENTS.md Substitutes table '
            'and is not scaffolding ending in Co/Company. Rebuild it from the table:\n  '
            + '\n  '.join(offenders),
        )
