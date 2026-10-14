#!/usr/bin/env python3
"""Ensure CoordinatorLayout behavior classes resolve for suffixed app IDs."""
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / 'android/app/src/main/res'
JAVA = ROOT / 'android/app/src/main/java'
APP_NS = '{http://schemas.android.com/apk/res-auto}'

class SideBySideLayoutTest(unittest.TestCase):
    def test_behaviors_resolve_for_production_and_test_packages(self):
        classes = set()
        for file in JAVA.rglob('*.kt'):
            text = file.read_text()
            package = re.search(r'^package\s+([\w.]+)', text, re.M)
            if package:
                for name in re.findall(r'^\s*(?:open\s+)?class\s+(\w+)', text, re.M):
                    classes.add(package.group(1)+'.'+name)
        checked = 0
        for file in RES.rglob('*.xml'):
            for element in ET.parse(file).iter():
                behavior = element.get(APP_NS+'layout_behavior')
                if not behavior or behavior.startswith('@'):
                    continue
                checked += 1
                for app_id in ['com.gameblabla.chiaki','com.gameblabla.chiaki.hevcfix']:
                    with self.subTest(file=str(file.relative_to(ROOT)), behavior=behavior, app_id=app_id):
                        resolved = app_id + behavior if behavior.startswith('.') else behavior
                        self.assertIn(resolved, classes, f'CoordinatorLayout resolves {behavior} as {resolved}; no such class')
        self.assertGreater(checked,0)

if __name__ == '__main__':
    unittest.main()
