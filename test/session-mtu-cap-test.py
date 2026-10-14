#!/usr/bin/env python3
"""Exercise actual session MTU cap: never exceed tunnel-friendly 1280."""
from pathlib import Path
import os
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'lib/src/session.c').read_text()
start=s.index('\tif(session->mtu_in > 1280)')
end=s.index('#endif', start)
block=s[start:end]
assert block.strip() and 'Capping stream MTU' in block and 'session->mtu_in = 1280;' in block, 'extracted MTU cap block is empty or narrowed'
harness=r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#define CHIAKI_LOGI(...) ((void)0)
typedef struct { uint32_t mtu_in; void *log; } Session;
static void cap(Session *session) {
'''+block+r'''
}
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); return 1; } } while(0)
int main(void) {
    Session s={.mtu_in=1454}; cap(&s); CHECK(s.mtu_in==1280);
    puts("PASS oversized path MTU capped to 1280");
    s.mtu_in=1200; cap(&s); CHECK(s.mtu_in==1200);
    puts("PASS sub-cap MTU unchanged");
    s.mtu_in=1280; cap(&s); CHECK(s.mtu_in==1280);
    puts("PASS boundary MTU unchanged");
}
'''
with tempfile.TemporaryDirectory(prefix='chiaki-mtu-',dir=os.environ.get('TMPDIR')) as tmp:
    c=Path(tmp)/'test.c'; exe=Path(tmp)/'test'; c.write_text(harness)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
