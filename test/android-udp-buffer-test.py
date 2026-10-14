#!/usr/bin/env python3
"""Compile actual Takion socket receive-buffer setup for Android and desktop."""
from pathlib import Path
import os
import subprocess
import tempfile

root=Path(__file__).resolve().parents[1]
s=(root/'lib/src/takion.c').read_text()
start=s.index('\tint rcvbuf_val = takion->a_rwnd;')
block=s[start:s.index('\tif(info->ip_dontfrag)',start)]
assert 'TAKION_ANDROID_STREAM_RCVBUF' in block, 'named constant missing from extracted block'
assert 'enable_crypt' in block and 'SO_RCVBUF' in block, 'extracted block does not contain socket setup'
harness=r'''
#include <stdbool.h>
#include <stdio.h>
#include <sys/socket.h>
#include <string.h>
#include <errno.h>
#define CHIAKI_ERR_NETWORK -1
#define TAKION_ANDROID_STREAM_RCVBUF (4*1024*1024)
static void log_emit(const void *log, const char *fmt, ...) { (void)log; (void)fmt; }
#define CHIAKI_LOGE(...) log_emit(__VA_ARGS__)
#define CHIAKI_LOGI(...) log_emit(__VA_ARGS__)
static int warn_count;
#define CHIAKI_LOGW(...) do { warn_count++; } while(0)
struct Takion { int sock,a_rwnd; void *log; };
struct Info { bool enable_crypt; };
static int requested;
static int clamp;
static int fake_setsockopt(int s,int l,int o,const void *p,socklen_t n) { (void)s;(void)l;(void)o;(void)n; requested=*(const int*)p; return 0; }
static int fake_getsockopt(int s,int l,int o,void *p,socklen_t *n) { (void)s;(void)l;(void)o;(void)n; *(int*)p=clamp?requested/2:requested*2; return 0; }
#define setsockopt fake_setsockopt
#define getsockopt fake_getsockopt
static int configure(bool stream) {
    struct Takion t={.sock=1,.a_rwnd=0x19000}; struct Takion *takion=&t;
    struct Info i={.enable_crypt=stream}; struct Info *info=&i; (void)info;
    int ret=0;
'''+block+r'''
    return requested;
error_sock:
    return ret;
}
int main(void) {
    (void)warn_count;
#ifdef __ANDROID__
    int expected=4*1024*1024;
#else
    int expected=0x19000;
#endif
    int actual=configure(true);
    if(actual!=expected) { fprintf(stderr,"FAIL stream receive buffer %d, expected %d\n",actual,expected); return 1; }
    if(configure(false)!=0x19000) { fputs("FAIL bootstrap receive buffer changed\n",stderr); return 1; }
#ifdef __ANDROID__
    clamp=1; configure(true);
    if(warn_count==0) { fputs("FAIL kernel clamp not warned\n",stderr); return 1; }
    puts("PASS clamped stream buffer warned");
    clamp=0;
#endif
#ifdef __ANDROID__
    puts("PASS Android streaming receive capacity; bootstrap unchanged");
#else
    puts("PASS desktop receive-buffer behavior unchanged");
#endif
}
'''
with tempfile.TemporaryDirectory(prefix='chiaki-udp-',dir=os.environ.get('TMPDIR')) as tmp:
    c=Path(tmp)/'test.c'; c.write_text(harness)
    for platform,flags in [('android',['-D__ANDROID__']),('desktop',[])]:
        exe=Path(tmp)/platform
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-function',*flags,str(c),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
