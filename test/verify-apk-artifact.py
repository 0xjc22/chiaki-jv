#!/usr/bin/env python3
"""Verify the v1.0.1 APK artifact: signature, alignment, ELF, native tokens."""
from pathlib import Path
import subprocess, os, shutil, hashlib, zipfile, struct

src = Path("android/app/build/outputs/apk/debug/app-debug.apk")
dst = Path("/home/jc/dl/chiaki-up-hevc-v1.1.0-arm64.apk")
if dst.exists():
    dst.unlink()
shutil.copy2(src, dst)

e = os.environ.copy()
e["JAVA_HOME"] = "/home/jc/.local/opt/jdk17"
e["PATH"] = e["JAVA_HOME"] + "/bin:" + e["PATH"]
tools = Path("/home/jc/.local/opt/android-sdk/build-tools/35.0.0")
subprocess.run([str(tools / "apksigner"), "verify", "--verbose", str(dst)],
               env=e, check=True, stdout=subprocess.DEVNULL)
subprocess.run([str(tools / "zipalign"), "-c", "-P", "16", "4", str(dst)], check=True)

z = zipfile.ZipFile(dst)
native = [n for n in z.namelist() if n.endswith(".so")]
assert native and all(n.startswith("lib/arm64-v8a/") for n in native)
for n in native:
    d = z.read(n)
    assert d[:5] == b"\x7fELF\x02"
    h = struct.unpack_from("<16sHHIQQQIHHHHHH", d)
    off, size, count = h[5], h[9], h[10]
    loads = [struct.unpack_from("<IIQQQQQQ", d, off + i * size) for i in range(count)]
    assert all(p[-1] >= 16384 for p in loads if p[0] == 1), n

so = z.read("lib/arm64-v8a/libchiaki-jni.so")
for token in [b"requesting IDR frame", b"Capping stream MTU",
              b"minimal format after full-format rejection",
              b"clamped by kernel", b"receive buffer (", b"discarding frames"]:
    assert token in so, token.decode()

print("APK:", dst)
print("SHA256:", hashlib.sha256(dst.read_bytes()).hexdigest())
print("signature v2, ZIP/ELF alignment, native tokens: VERIFIED")
