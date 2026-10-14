#!/usr/bin/env python3
"""Isolated stdlib regression tests for the APK artifact verifier."""
import os
import importlib.util
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[1]
VERIFIER = REPO / "test/verify-apk-artifact.py"
EXPECTED = ("com.gameblabla.chiaki.hevcfix", "32", "1.1.0-hevcfix", "Chiaki-Up")
TOKENS = (b"requesting IDR frame", b"Capping stream MTU",
          b"minimal format after full-format rejection", b"clamped by kernel",
          b"receive buffer (", b"discarding frames")

sys.dont_write_bytecode = True  # Keep host regression runs out of the source tree.
spec = importlib.util.spec_from_file_location("apk_verifier", VERIFIER)
assert spec is not None and spec.loader is not None
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def fake_elf(valid=True, bad_alignment=False):
    """Clearly synthetic ELF64/AArch64 with one 16KiB PT_LOAD segment."""
    data = bytearray(128 + 56)
    data[:16] = b"\x7fELF\x02\x01\x01" + bytes(9)
    struct.pack_into("<HHIQQQIHHHHHH", data, 16, 3, 183 if valid else 62, 1,
                     0, 64, 0, 0, 64, 56, 1, 0, 0, 0)
    struct.pack_into("<IIQQQQQQ", data, 64, 1, 5, 0, 0, 0, 1, 1,
                     4096 if bad_alignment else 16384)
    data[120:128] = b"fixture!"
    return bytes(data) + b"\n" + b"\n".join(TOKENS)


class ArtifactVerifierTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="apk-verifier-fixtures-")
        self.root = Path(self.temp.name)
        self.sdk = self.root / "sdk"
        tools = self.sdk / "build-tools/35.0.0"
        tools.mkdir(parents=True)
        self.tools = tools
        self._tool("apksigner", '''#!/usr/bin/env python3
import os, sys
if os.environ.get("FAKE_V2", "yes") == "yes":
 print("Verified using v2 scheme (APK Signature Scheme v2): true")
else:
 print("Verified using v1 scheme (JAR signing): true")
sys.exit(0)
''')
        self._tool("zipalign", "#!/usr/bin/env python3\nraise SystemExit(0)\n")
        self._tool("aapt", '''#!/usr/bin/env python3
import os, sys
if sys.argv[1:3] == ["dump", "badging"]:
 print("package: name='%s' versionCode='%s' versionName='%s'" % (
  os.environ.get("FAKE_PACKAGE", "com.gameblabla.chiaki.hevcfix"),
  os.environ.get("FAKE_CODE", "32"), os.environ.get("FAKE_VERSION", "1.1.0-hevcfix")))
 print("application-label:'%s'" % os.environ.get("FAKE_LABEL", "Chiaki-Up"))
else:
 print("android:testOnly(0x01010272)= (type 0x12)" + os.environ.get("FAKE_TEST_ONLY", "0x0"))
''')
        self.apk = self.root / "candidate.apk"
        self.release = self.root / "existing-release.apk"
        self.release.write_bytes(b"preserve this artifact")
        self.expected_release = self.release.read_bytes()
        self.make_apk()

    def tearDown(self):
        self.temp.cleanup()

    def _tool(self, name, content):
        path = self.tools / name
        path.write_text(content)
        path.chmod(0o755)

    def make_apk(self, elf=True, corrupt=False, bad_alignment=False):
        if corrupt:
            self.apk.write_bytes(b"not a ZIP/APK")
            return
        with zipfile.ZipFile(self.apk, "w") as archive:
            archive.writestr("lib/arm64-v8a/libchiaki-jni.so",
                             fake_elf(elf, bad_alignment=bad_alignment))

    def run_verifier(self, apk=None, **env):
        environ = os.environ.copy()
        environ.update({"ANDROID_HOME": str(self.sdk), "FAKE_V2": "yes"})
        environ.update(env)
        return subprocess.run(
            [sys.executable, str(VERIFIER), "--apk", str(apk or self.apk),
             "--sdk", str(self.sdk), "--expected-package", EXPECTED[0],
             "--expected-version-code", EXPECTED[1], "--expected-version-name", EXPECTED[2],
             "--expected-label", EXPECTED[3]],
            cwd=REPO, env=environ, text=True, capture_output=True, check=False)

    def test_missing_or_invalid_source_leaves_existing_artifact_unchanged(self):
        missing = self.root / "missing.apk"
        self.assertNotEqual(self.run_verifier(missing).returncode, 0)
        self.make_apk(corrupt=True)
        self.assertNotEqual(self.run_verifier().returncode, 0)
        self.assertEqual(self.release.read_bytes(), self.expected_release)

    def test_requires_explicit_v2_signature_result(self):
        result = self.run_verifier(FAKE_V2="no")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("v2", (result.stdout + result.stderr).lower())

    def test_default_identity_uses_debug_resource_override(self):
        debug_strings = ET.parse(REPO / "android/app/src/debug/res/values/strings.xml")
        expected_label = next(item.text for item in debug_strings.iter("string")
                              if item.attrib.get("name") == "app_name")
        self.assertEqual(verifier.default_identity(REPO)[3], expected_label)

    def test_rejects_wrong_identity_and_non_aarch64_elf(self):
        identity = self.run_verifier(FAKE_PACKAGE="wrong.package")
        self.assertNotEqual(identity.returncode, 0)
        self.make_apk(elf=False)
        elf = self.run_verifier()
        self.assertNotEqual(elf.returncode, 0)

    def test_rejects_test_only_and_under_aligned_load_segment(self):
        test_only = self.run_verifier(FAKE_TEST_ONLY="0xffffffff")
        self.assertNotEqual(test_only.returncode, 0)
        self.assertIn("testOnly", test_only.stderr)
        self.make_apk(bad_alignment=True)
        alignment = self.run_verifier()
        self.assertNotEqual(alignment.returncode, 0)
        self.assertIn("16KiB", alignment.stderr)

    def test_rejects_non_power_of_two_elf_alignment(self):
        data = bytearray(fake_elf())
        struct.pack_into("<Q", data, 64 + 48, 16385)
        with self.assertRaisesRegex(ValueError, "power of two"):
            verifier.verify_elf(data, "synthetic-invalid-alignment.so")

    def test_rejects_elf_load_range_outside_file(self):
        data = bytearray(fake_elf())
        struct.pack_into("<Q", data, 64 + 8, 16384)
        with self.assertRaisesRegex(ValueError, "outside"):
            verifier.verify_elf(data, "synthetic-out-of-file-load.so")

    def test_accepts_matching_synthetic_fixture_without_modifying_it(self):
        before = self.apk.read_bytes()
        result = self.run_verifier()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.apk.read_bytes(), before)
        self.assertEqual(self.release.read_bytes(), self.expected_release)


if __name__ == "__main__":
    unittest.main(verbosity=2)
