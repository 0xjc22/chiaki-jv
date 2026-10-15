#!/usr/bin/env python3
"""Compile real packetstats.c with mutex API fakes (not a race-detector test)."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
header = (root / 'lib/include/chiaki/packetstats.h').read_text()
header = '\n'.join(line for line in header.splitlines() if not line.startswith('#include'))
source = (root / 'lib/src/packetstats.c').read_text()
source = '\n'.join(line for line in source.splitlines() if not line.startswith('#include'))
assert 'chiaki_packet_stats_push_seq' in source
harness = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHIAKI_EXPORT
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x); exit(1); } } while(0)
typedef int ChiakiErrorCode;
typedef uint16_t ChiakiSeqNum16;
typedef struct { int depth, locks; } ChiakiMutex;
static int chiaki_mutex_init(ChiakiMutex *m, bool recursive) { (void)recursive; *m=(ChiakiMutex){0}; return 0; }
static void chiaki_mutex_fini(ChiakiMutex *m) { CHECK(!m->depth); }
static void chiaki_mutex_lock(ChiakiMutex *m) { CHECK(++m->depth==1); m->locks++; }
static void chiaki_mutex_unlock(ChiakiMutex *m) { CHECK(--m->depth==0); }
static inline bool chiaki_seq_num_16_gt(uint16_t a, uint16_t b) { return (uint16_t)(a-b) != 0 && (uint16_t)(a-b)<32768; }
''' + header + '\n' + source + r'''
int main(void) {
    ChiakiPacketStats s;
    CHECK(chiaki_packet_stats_init(&s)==0);
    int locks=s.mutex.locks;
    chiaki_packet_stats_push_seq(&s,100);
    CHECK(s.mutex.locks==locks+1 && !s.mutex.depth);
    uint64_t received, lost;
    chiaki_packet_stats_get(&s,false,&received,&lost);
    CHECK(received==1 && lost==0); /* startup has no invented prefix loss */
    chiaki_packet_stats_push_seq(&s,102);
    chiaki_packet_stats_push_seq(&s,102);
    chiaki_packet_stats_get(&s,false,&received,&lost);
    CHECK(received==2 && lost==1);
    chiaki_packet_stats_push_seq(&s,101);
    chiaki_packet_stats_push_seq(&s,101);
    chiaki_packet_stats_get(&s,true,&received,&lost);
    CHECK(received==3 && lost==0);
    chiaki_packet_stats_push_seq(&s,101); /* previous interval cannot be repaired */
    chiaki_packet_stats_push_seq(&s,102);
    chiaki_packet_stats_get(&s,false,&received,&lost);
    CHECK(received==0 && lost==0);
    chiaki_packet_stats_push_seq(&s,104);
    chiaki_packet_stats_get(&s,true,&received,&lost);
    CHECK(received==1 && lost==1);
    chiaki_packet_stats_push_seq(&s,103);
    chiaki_packet_stats_get(&s,false,&received,&lost);
    CHECK(received==0 && lost==0);
    chiaki_packet_stats_push_generation(&s,7,2);
    chiaki_packet_stats_get(&s,true,&received,&lost);
    CHECK(received==7 && lost==2);
    chiaki_packet_stats_get(&s,false,&received,&lost);
    CHECK(received==0 && lost==0);
    chiaki_packet_stats_fini(&s);
    CHECK(chiaki_packet_stats_init(&s)==0);
    chiaki_packet_stats_push_seq(&s,65534);
    chiaki_packet_stats_push_seq(&s,0);
    chiaki_packet_stats_push_seq(&s,65535);
    chiaki_packet_stats_push_seq(&s,1);
    chiaki_packet_stats_get(&s,true,&received,&lost);
    CHECK(received==4 && lost==0);
    /* More than two wraps in one interval: counters must not be 16-bit spans. */
    for(unsigned i=2; i<140002; i++) chiaki_packet_stats_push_seq(&s,(uint16_t)i);
    chiaki_packet_stats_get(&s,true,&received,&lost);
    CHECK(received==140000 && lost==0);
    chiaki_packet_stats_reset(&s);
    chiaki_packet_stats_get(&s,false,&received,&lost);
    CHECK(received==0 && lost==0);
    chiaki_packet_stats_fini(&s);
    CHECK(chiaki_packet_stats_init(&s)==0);
    chiaki_packet_stats_push_seq(&s,1000);
    chiaki_packet_stats_push_seq(&s,1300);
    chiaki_packet_stats_push_seq(&s,1001); /* outside bounded reorder window */
    chiaki_packet_stats_push_seq(&s,1299);
    chiaki_packet_stats_get(&s,false,&received,&lost);
    CHECK(received==3 && lost==298);
    chiaki_packet_stats_push_seq(&s,(uint16_t)(1300+32768)); /* ambiguous half range */
    chiaki_packet_stats_get(&s,false,&received,&lost);
    CHECK(received==3 && lost==298);
    chiaki_packet_stats_fini(&s);
    puts("PASS synchronized writer, startup, duplicates, reorder, interval cut, generation totals, wrap and bounded history");
}
'''
with tempfile.TemporaryDirectory(prefix='chiaki-packetstats-', dir=os.environ.get('TMPDIR')) as tmp:
    c = Path(tmp) / 'test.c'
    exe = Path(tmp) / 'test'
    c.write_text(harness)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=5)
