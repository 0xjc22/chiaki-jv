#!/usr/bin/env python3
"""Exercise actual decoder monotonic timestamp conversion with a fake clock."""
from pathlib import Path
import os
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'android/app/src/main/cpp/video-decoder.c').read_text()
sig='static uint64_t android_chiaki_video_decoder_time_us(void)'
assert sig in s, 'Decoder monotonic timing helper is not implemented'
start=s.index(sig); end=s.index('\n}',start)+2
helper=s[start:end]
harness=r'''
#include <stdint.h>
#include <stdio.h>
#define CLOCK_MONOTONIC 1
struct timespec { long tv_sec,tv_nsec; };
static struct timespec now; static int fail_clock;
static int clock_gettime(int clk,struct timespec *ts) { if(clk!=CLOCK_MONOTONIC || fail_clock) return -1; *ts=now; return 0; }
'''+helper+r'''
int main(void) {
    now.tv_sec=12; now.tv_nsec=345678900;
    if(android_chiaki_video_decoder_time_us()!=12345678) return 1;
    fail_clock=1; if(android_chiaki_video_decoder_time_us()!=0) return 1;
    puts("PASS monotonic microsecond conversion and clock failure");
}
'''
with tempfile.TemporaryDirectory(prefix='chiaki-clock-',dir=os.environ.get('TMPDIR')) as tmp:
    c=Path(tmp)/'test.c'; exe=Path(tmp)/'test'; c.write_text(harness)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
