#!/usr/bin/env python3
"""Verify an APK in place; this command never copies, edits, or deletes it."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile

MIN_LOAD_ALIGNMENT = 16 * 1024
NATIVE_TOKENS = (
    b"requesting IDR frame", b"Capping stream MTU",
    b"minimal format after full-format rejection", b"clamped by kernel",
    b"receive buffer (", b"discarding frames",
)


def default_apk(repo):
    return repo / "android/app/build/outputs/apk/debug/app-debug.apk"


def default_identity(repo):
    """Read debug identity from this app's Gradle config and app_name resource."""
    gradle = (repo / "android/app/build.gradle").read_text()

    def match(pattern, label):
        found = re.search(pattern, gradle)
        if not found:
            raise ValueError(f"cannot determine {label} from android/app/build.gradle")
        return found.group(1)

    app_id = match(r'applicationId\s+["\']([^"\']+)', "applicationId")
    code = match(r'versionCode\s+(\d+)', "versionCode")
    version = match(r'versionName\s+["\']([^"\']+)', "versionName")
    suffix = re.search(r'applicationIdSuffix\s+["\']([^"\']+)', gradle)
    name_suffix = re.search(r'versionNameSuffix\s+["\']([^"\']+)', gradle)
    label = None
    for source_set in ("main", "debug"):
        resource = repo / f"android/app/src/{source_set}/res/values/strings.xml"
        if resource.is_file():
            strings = ET.parse(resource)
            label = next((item.text for item in strings.iter("string")
                          if item.attrib.get("name") == "app_name"), label)
    if not label:
        raise ValueError("cannot determine app label from strings.xml")
    return (app_id + (suffix.group(1) if suffix else ""), code,
            version + (name_suffix.group(1) if name_suffix else ""), label)


def resolve_tools(args):
    sdk = args.sdk or os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not sdk:
        raise ValueError("Android SDK not set; pass --sdk or set ANDROID_HOME/ANDROID_SDK_ROOT")
    tools = Path(sdk) / "build-tools" / args.build_tools
    jdk = args.jdk or os.environ.get("JAVA_HOME")
    env = os.environ.copy()
    if jdk:
        env["JAVA_HOME"] = str(jdk)
        env["PATH"] = str(Path(jdk) / "bin") + os.pathsep + env.get("PATH", "")
    return tools, env


def run_tool(tool, arguments, env=None):
    result = subprocess.run([str(tool), *map(str, arguments)], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=env, check=False)
    if result.returncode:
        raise ValueError(f"{tool.name} failed: {result.stdout.strip()}")
    return result.stdout


def verify_identity(apk, tools, env, expected):
    badging = run_tool(tools / "aapt", ["dump", "badging", apk], env)
    package = re.search(r"^package: name='([^']+)' versionCode='([^']+)' versionName='([^']*)'", badging, re.M)
    label = re.search(r"^application-label:'(.*)'$", badging, re.M)
    if not package or not label:
        raise ValueError("aapt did not report package identity and application label")
    actual = (*package.groups(), label.group(1))
    for name, got, wanted in zip(("package", "versionCode", "versionName", "label"), actual, expected):
        if got != wanted:
            raise ValueError(f"APK {name} mismatch: expected {wanted!r}, got {got!r}")
    tree = run_tool(tools / "aapt", ["dump", "xmltree", apk, "AndroidManifest.xml"], env)
    test_only = re.search(r"android:testOnly\([^)]*\)\s*=\s*(.*)", tree, re.I)
    if test_only:
        value = re.sub(r"^\(type [^)]+\)\s*", "", test_only.group(1)).strip().lower()
        if value not in ("0", "0x0", "false"):
            raise ValueError("APK manifest has android:testOnly enabled")


def verify_elf(data, name):
    if len(data) < 64 or data[:4] != b"\x7fELF":
        raise ValueError(f"{name}: not an ELF file")
    if data[4] != 2 or data[5] != 1:
        raise ValueError(f"{name}: expected ELF64 little-endian")
    if struct.unpack_from("<H", data, 18)[0] != 183:
        raise ValueError(f"{name}: expected EM_AARCH64")
    phoff = struct.unpack_from("<Q", data, 32)[0]
    phentsize, phnum = struct.unpack_from("<HH", data, 54)
    if phentsize < 56 or phoff + phentsize * phnum > len(data):
        raise ValueError(f"{name}: invalid ELF program-header table")
    loads = []
    for index in range(phnum):
        header = struct.unpack_from("<IIQQQQQQ", data, phoff + index * phentsize)
        if header[0] == 1 and header[5] > 0:
            if header[2] + header[5] > len(data):
                raise ValueError(f"{name}: PT_LOAD file range extends outside the ELF")
            loads.append((header[2], header[3], header[7]))
    if not loads:
        raise ValueError(f"{name}: no nonempty PT_LOAD segments")
    for offset, vaddr, alignment in loads:
        if alignment < MIN_LOAD_ALIGNMENT:
            raise ValueError(f"{name}: PT_LOAD alignment is below 16KiB")
        if alignment & (alignment - 1):
            raise ValueError(f"{name}: PT_LOAD alignment is not a power of two")
        if offset % alignment != vaddr % alignment:
            raise ValueError(f"{name}: PT_LOAD offset/vaddr alignment mismatch")


def verify_apk(apk, tools, env, expected):
    if not apk.is_file():
        raise ValueError(f"APK does not exist: {apk}")
    signer_output = run_tool(tools / "apksigner", ["verify", "--verbose", apk], env)
    if not re.search(r"Verified using v2 scheme \(APK Signature Scheme v2\):\s*true\b", signer_output, re.I):
        raise ValueError("apksigner did not explicitly confirm APK Signature Scheme v2")
    run_tool(tools / "zipalign", ["-c", "-P", "16", "4", apk], env)
    verify_identity(apk, tools, env, expected)
    try:
        with zipfile.ZipFile(apk) as archive:
            members = [name for name in archive.namelist() if name.endswith(".so")]
            if not members:
                raise ValueError("APK contains no native libraries")
            if any(not name.startswith("lib/arm64-v8a/") for name in members):
                raise ValueError("APK contains a native library outside lib/arm64-v8a/")
            for name in members:
                verify_elf(archive.read(name), name)
            native_path = "lib/arm64-v8a/libchiaki-jni.so"
            if native_path not in members:
                raise ValueError(f"APK is missing {native_path}")
            native = archive.read(native_path)
            for token in NATIVE_TOKENS:
                if token not in native:
                    raise ValueError(f"native library is missing token: {token.decode()}")
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError(f"invalid APK ZIP: {exc}") from exc


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, default=None,
                        help="APK to verify in place (default: debug build output)")
    parser.add_argument("--sdk", type=Path, help="Android SDK root")
    parser.add_argument("--jdk", type=Path, help="JDK root (otherwise JAVA_HOME)")
    parser.add_argument("--build-tools", default="35.0.0", help="build-tools version (default: 35.0.0)")
    parser.add_argument("--expected-package")
    parser.add_argument("--expected-version-code")
    parser.add_argument("--expected-version-name")
    parser.add_argument("--expected-label")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    try:
        apk = (args.apk or default_apk(repo)).expanduser().resolve()
        defaults = default_identity(repo)
        supplied = (args.expected_package, args.expected_version_code,
                    args.expected_version_name, args.expected_label)
        expected = tuple(value if value is not None else default
                         for value, default in zip(supplied, defaults))
        tools, env = resolve_tools(args)
        for executable in ("apksigner", "zipalign", "aapt"):
            if not (tools / executable).is_file():
                raise ValueError(f"missing Android build tool: {tools / executable}")
        verify_apk(apk, tools, env, expected)
        digest = hashlib.sha256(apk.read_bytes()).hexdigest()
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"APK: {apk}")
    print(f"SHA256: {digest}")
    print("signature v2, identity, ZIP/ELF alignment, native tokens: VERIFIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
