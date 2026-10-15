#!/usr/bin/env python3
"""Compile real frameprocessor/receiver C; host seams for session, clock and stats.

No Android/device validation. FEC uses the bundled Jerasure/gf-complete code.
Select individual cases by passing their names; SANITIZE=1 enables ASan/UBSan.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
packet = (root / 'lib/include/chiaki/takion.h').read_text()
packet = packet[packet.index('typedef struct chiaki_takion_av_packet_t'):packet.index('} ChiakiTakionAVPacket;') + len('} ChiakiTakionAVPacket;')]
assert 'units_in_frame_total' in packet
preamble = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <chiaki/common.h>
#include <chiaki/log.h>
#include <chiaki/seqnum.h>
#define CHIAKI_TAKION_H
''' + packet + r'''
#include <chiaki/videoreceiver.h>
#include <chiaki/fec.h>
#include <jerasure.h>
#include <cauchy.h>
static int alloc_fail_after = -1;
static void *test_malloc(size_t n) { if(alloc_fail_after == 0) return NULL; if(alloc_fail_after > 0) alloc_fail_after--; return malloc(n); }
static void *test_realloc(void *p, size_t n) { if(alloc_fail_after == 0) return NULL; if(alloc_fail_after > 0) alloc_fail_after--; return realloc(p,n); }
#define malloc test_malloc
#define realloc test_realloc
#include "FRAMEPROCESSOR"
#undef malloc
#undef realloc
#include "VIDEORECEIVER"
void chiaki_log(ChiakiLog *l, ChiakiLogLevel v, const char *fmt, ...) { (void)l; (void)v; (void)fmt; }
void chiaki_log_hexdump(ChiakiLog *l, ChiakiLogLevel v, const uint8_t *b, size_t n) { (void)l; (void)v; (void)b; (void)n; }
void chiaki_packet_stats_push_generation(ChiakiPacketStats *s, uint64_t r, uint64_t l) { s->gen_received += r; s->gen_lost += l; }
static int decoded, idrs, corrupts;
uint64_t chiaki_time_now_monotonic_ms(void) { return 10000; }
ChiakiErrorCode stream_connection_send_idr_request(int *s) { (void)s; idrs++; return CHIAKI_ERR_SUCCESS; }
ChiakiErrorCode stream_connection_send_corrupt_frame(int *s, ChiakiSeqNum16 a, ChiakiSeqNum16 b) { (void)s; (void)a; (void)b; corrupts++; return CHIAKI_ERR_SUCCESS; }
static bool decode(uint8_t *b, size_t n, void *u) { (void)b; (void)u; if(n) decoded++; return true; }
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"FAIL %s:%d: %s\n",__func__,__LINE__,#x); return 1; } } while(0)
static uint8_t bytes[16] = {0,0,0,0,1,0x26,1,2,3,4,5,6,7,8,9,10};
static ChiakiTakionAVPacket pkt(void) { return (ChiakiTakionAVPacket){.is_video=true,.frame_index=1,.units_in_frame_total=3,.units_in_frame_fec=1,.data=bytes,.data_size=16}; }
static int boundary(void) {
    ChiakiFrameProcessor f; chiaki_frame_processor_init(&f,NULL); ChiakiTakionAVPacket p=pkt();
    CHECK(chiaki_frame_processor_alloc_frame(&f,&p)==CHIAKI_ERR_SUCCESS);
    /* Spare physical slot makes the old logical off-by-one deterministic. */
    f.unit_slots=realloc(f.unit_slots,(f.unit_slots_size+1)*sizeof(*f.unit_slots));
    memset(f.unit_slots+f.unit_slots_size,0,sizeof(*f.unit_slots));
    p.unit_index=f.unit_slots_size;
    CHECK(chiaki_frame_processor_put_unit(&f,&p)==CHIAKI_ERR_INVALID_DATA);
    CHECK(f.units_source_received+f.units_fec_received==0);
    chiaki_frame_processor_fini(&f); return 0;
}
static int allocation(void) {
    ChiakiFrameProcessor f; chiaki_frame_processor_init(&f,NULL); uint8_t *out=NULL; size_t n=0;
    for(int i=0;i<9;i++) {
        ChiakiTakionAVPacket p=pkt();
        switch(i) {
        case 0: p.units_in_frame_total=0; p.units_in_frame_fec=0; break;
        case 1: p.units_in_frame_fec=3; break;
        case 2: p.units_in_frame_fec=4; break;
        case 3: p.units_in_frame_total=257; break;
        case 4: p.unit_index=3; break;
        case 5: p.data=NULL; break;
        case 6: p.data_size=1; break;
        case 7: p.is_video=false; break;
        case 8: p.data_size=SIZE_MAX; break;
        }
        CHECK(chiaki_frame_processor_alloc_frame(&f,&p)!=CHIAKI_ERR_SUCCESS);
        CHECK(!chiaki_frame_processor_flush_possible(&f));
        CHECK(chiaki_frame_processor_flush(&f,&out,&n)==CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FAILED);
    }
    ChiakiTakionAVPacket p=pkt();
    CHECK(chiaki_frame_processor_alloc_frame(&f,&p)==CHIAKI_ERR_SUCCESS);
    CHECK(chiaki_frame_processor_put_unit(&f,&p)==CHIAKI_ERR_SUCCESS);
    p.units_in_frame_total=0;
    CHECK(chiaki_frame_processor_alloc_frame(&f,&p)!=CHIAKI_ERR_SUCCESS);
    CHECK(!chiaki_frame_processor_flush_possible(&f));
    CHECK(chiaki_frame_processor_put_unit(&f,&p)!=CHIAKI_ERR_SUCCESS);
    p=pkt(); p.units_in_frame_total=2; p.units_in_frame_fec=0;
    CHECK(chiaki_frame_processor_alloc_frame(&f,&p)==CHIAKI_ERR_SUCCESS);
    CHECK(f.unit_slots_size==2 && f.units_fec_expected==0);
    ChiakiPacketStats stats={0}; chiaki_frame_processor_report_packet_stats(&f,&stats);
    CHECK(stats.gen_lost==2);
    chiaki_frame_processor_fini(&f); return 0;
}
static int insertion(void) {
    ChiakiFrameProcessor f; chiaki_frame_processor_init(&f,NULL); ChiakiTakionAVPacket p=pkt();
    CHECK(chiaki_frame_processor_alloc_frame(&f,&p)==CHIAKI_ERR_SUCCESS);
    for(int i=0;i<11;i++) {
        p=pkt();
        switch(i) {
        case 0: p.frame_index++; break;
        case 1: p.units_in_frame_total++; break;
        case 2: p.units_in_frame_fec++; break;
        case 3: p.adaptive_stream_index++; break;
        case 4: p.codec++; break;
        case 5: p.is_video=false; break;
        case 6: p.data=NULL; break;
        case 7: p.data_size=1; break;
        case 8: p.data_size=15; break; /* undeclared source padding */
        case 9: p.unit_index=2; p.data_size=15; break; /* truncated parity */
        case 10: bytes[1]=1; break; /* inconsistent source padding */
        }
        CHECK(chiaki_frame_processor_put_unit(&f,&p)!=CHIAKI_ERR_SUCCESS);
        CHECK(f.units_source_received==0 && f.units_fec_received==0);
        bytes[1]=0;
    }
    p=pkt(); CHECK(chiaki_frame_processor_put_unit(&f,&p)==CHIAKI_ERR_SUCCESS);
    CHECK(chiaki_frame_processor_put_unit(&f,&p)!=CHIAKI_ERR_SUCCESS);
    CHECK(f.units_source_received==1);
    p.unit_index=1; p.data_size=12; bytes[1]=4;
    CHECK(chiaki_frame_processor_put_unit(&f,&p)==CHIAKI_ERR_SUCCESS);
    bytes[1]=0;
    chiaki_frame_processor_fini(&f); return 0;
}
static int assembly(void) {
    /* Real Cauchy parity exercises reconstructed padding, not a fake decoder. */
    for(int mode=0;mode<8;mode++) {
        uint8_t a[16]={0,0,1,2,3,4,5,6}, b[16]={0,4,9,8,7,6,5,4,3,2,1,0}, parity[16]={0};
        if(mode==0) b[1]=16; /* reconstructed length zero */
        if(mode==1) b[1]=15; /* reconstructed length one */
        char *data[2]={(char *)a,(char *)b}, *coding[1]={(char *)parity};
        int *matrix=cauchy_original_coding_matrix(2,1,8); CHECK(matrix);
        jerasure_matrix_encode(2,1,8,matrix,data,coding,16); free(matrix);
        ChiakiFrameProcessor f; chiaki_frame_processor_init(&f,NULL);
        ChiakiTakionAVPacket p=pkt(); p.data=a;
        if(mode==3) { p.unit_index=2; p.data=parity; } /* parity arrives first */
        if(mode==7) { p.units_in_frame_total=1; p.units_in_frame_fec=0; p.data_size=2; }
        CHECK(chiaki_frame_processor_alloc_frame(&f,&p)==CHIAKI_ERR_SUCCESS);
        CHECK(chiaki_frame_processor_put_unit(&f,&p)==CHIAKI_ERR_SUCCESS);
        if(mode==3) { p.unit_index=0; p.data=a; CHECK(chiaki_frame_processor_put_unit(&f,&p)==CHIAKI_ERR_SUCCESS); }
        else if(mode==2 || mode==6) {
            p.unit_index=1; p.data=b; p.data_size=12;
            CHECK(chiaki_frame_processor_put_unit(&f,&p)==CHIAKI_ERR_SUCCESS);
            if(mode==6) f.unit_slots[1].data_size=1; /* defensive assembly validation */
        } else if(mode<2 || mode==4) {
            p.unit_index=2; p.data=parity;
            CHECK(chiaki_frame_processor_put_unit(&f,&p)==CHIAKI_ERR_SUCCESS);
        }
        uint8_t *out=(void *)1; size_t n=123;
        ChiakiFrameProcessorFlushResult r=chiaki_frame_processor_flush(&f,&out,&n);
        if(mode<2 || mode>=5) {
            CHECK(r==CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FEC_FAILED);
            CHECK(out==NULL && n==0); CHECK(f.stream_stats.frames==0);
        } else {
            CHECK(r==(mode==2 ? CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_SUCCESS : CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FEC_SUCCESS));
            CHECK(n==24); CHECK(!memcmp(out,a+2,14)); CHECK(!memcmp(out+14,b+2,10));
            CHECK(f.stream_stats.frames==1 && f.stream_stats.bytes==24);
        }
        CHECK(f.flushed); CHECK(!chiaki_frame_processor_flush_possible(&f));
        CHECK(chiaki_frame_processor_flush(&f,&out,&n)==CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FAILED);
        /* Late packets count once, but cannot rewrite a compacted AU. */
        if(mode==3 || mode==4) {
            uint8_t saved[24]; memcpy(saved,f.frame_buf,24);
            p.unit_index=1; p.data=b; p.data_size=12;
            CHECK(chiaki_frame_processor_put_unit(&f,&p)==CHIAKI_ERR_SUCCESS);
            CHECK(f.units_source_received==2 && f.units_fec_received==1);
            CHECK(!memcmp(saved,f.frame_buf,24));
            CHECK(chiaki_frame_processor_put_unit(&f,&p)!=CHIAKI_ERR_SUCCESS);
            ChiakiPacketStats stats={0}; chiaki_frame_processor_report_packet_stats(&f,&stats);
            CHECK(stats.gen_received==3 && stats.gen_lost==0);
        }
        chiaki_frame_processor_fini(&f);
    }
    return 0;
}
static int receiver(void) {
    ChiakiSession session={.video_sample_cb=decode}; ChiakiPacketStats stats={0}; ChiakiVideoReceiver v;
    chiaki_video_receiver_init(&v,&session,&stats); v.profiles_count=2;
    /* Allocation failures are handled, not inserted or decoded; next generation recovers. */
    ChiakiTakionAVPacket p=pkt(); alloc_fail_after=0;
    chiaki_video_receiver_av_packet(&v,&p);
    CHECK(decoded==0 && v.profile_cur==-1); CHECK(v.frame_index_prev==1);
    CHECK(v.frame_index_prev_complete==0 && idrs==1);
    chiaki_video_receiver_av_packet(&v,&p); CHECK(decoded==0 && idrs==1);
    alloc_fail_after=-1; p.frame_index=2;
    chiaki_video_receiver_av_packet(&v,&p);
    CHECK(v.frame_processor.units_source_received==1 && decoded==0 && v.profile_cur==0);
    chiaki_video_receiver_av_packet(&v,&p); CHECK(v.frame_processor.units_source_received==1 && idrs==1);
    p.adaptive_stream_index=1; chiaki_video_receiver_av_packet(&v,&p);
    CHECK(v.profile_cur==0 && v.frame_processor.units_source_received==1);
    p.adaptive_stream_index=0; p.unit_index=1; p.data_size=1;
    chiaki_video_receiver_av_packet(&v,&p); CHECK(decoded==0 && v.frame_index_prev==1);
    p.data_size=16; chiaki_video_receiver_av_packet(&v,&p);
    CHECK(decoded==1 && v.frame_index_prev==2 && v.frame_index_prev_complete==2 && !v.idr_pending);
    p.unit_index=2; chiaki_video_receiver_av_packet(&v,&p); /* late parity, stats only */
    CHECK(decoded==1 && v.frame_processor.units_fec_received==1);
    p.frame_index=3; p.unit_index=3; chiaki_video_receiver_av_packet(&v,&p);
    CHECK(decoded==1 && v.frame_index_prev==3 && v.frame_index_prev_complete==2);
    CHECK(stats.gen_received==3 && stats.gen_lost==0);
    p.frame_index=4; p.unit_index=0; p.units_in_frame_total=1; p.units_in_frame_fec=0;
    chiaki_video_receiver_av_packet(&v,&p); CHECK(decoded==2 && v.frame_index_prev_complete==4);
    p.frame_index=2; chiaki_video_receiver_av_packet(&v,&p); CHECK(decoded==2 && v.frame_index_cur==4);
    chiaki_video_receiver_fini(&v);
    /* Both allocation sites fail closed and remain reusable. */
    for(int fail=0;fail<2;fail++) {
        ChiakiFrameProcessor f; chiaki_frame_processor_init(&f,NULL); p=pkt(); alloc_fail_after=fail;
        CHECK(chiaki_frame_processor_alloc_frame(&f,&p)==CHIAKI_ERR_MEMORY);
        CHECK(!chiaki_frame_processor_flush_possible(&f)); CHECK(chiaki_frame_processor_put_unit(&f,&p)!=CHIAKI_ERR_SUCCESS);
        alloc_fail_after=-1; CHECK(chiaki_frame_processor_alloc_frame(&f,&p)==CHIAKI_ERR_SUCCESS);
        CHECK(chiaki_frame_processor_put_unit(&f,&p)==CHIAKI_ERR_SUCCESS); chiaki_frame_processor_fini(&f);
        chiaki_frame_processor_init(&f,NULL); p=pkt();
        CHECK(chiaki_frame_processor_alloc_frame(&f,&p)==CHIAKI_ERR_SUCCESS);
        CHECK(chiaki_frame_processor_put_unit(&f,&p)==CHIAKI_ERR_SUCCESS);
        p.units_in_frame_total=4; alloc_fail_after=fail;
        CHECK(chiaki_frame_processor_alloc_frame(&f,&p)==CHIAKI_ERR_MEMORY);
        CHECK(!chiaki_frame_processor_flush_possible(&f));
        CHECK(chiaki_frame_processor_put_unit(&f,&p)!=CHIAKI_ERR_SUCCESS);
        alloc_fail_after=-1; CHECK(chiaki_frame_processor_alloc_frame(&f,&p)==CHIAKI_ERR_SUCCESS);
        chiaki_frame_processor_fini(&f);
    }
    /* Boundary-sized, no-parity generations remain legitimate. */
    ChiakiFrameProcessor f; chiaki_frame_processor_init(&f,NULL); p=pkt();
    p.units_in_frame_total=256; p.units_in_frame_fec=0;
    CHECK(chiaki_frame_processor_alloc_frame(&f,&p)==CHIAKI_ERR_SUCCESS);
    for(unsigned i=0;i<256;i++) { p.unit_index=i; CHECK(chiaki_frame_processor_put_unit(&f,&p)==CHIAKI_ERR_SUCCESS); }
    uint8_t *out; size_t n;
    CHECK(chiaki_frame_processor_flush(&f,&out,&n)==CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_SUCCESS);
    CHECK(n==256*14); chiaki_frame_processor_fini(&f);
    return 0;
}
int main(int argc, char **argv) {
    if(argc!=2) return 2;
    if(!strcmp(argv[1],"boundary")) return boundary();
    if(!strcmp(argv[1],"allocation")) return allocation();
    if(!strcmp(argv[1],"insertion")) return insertion();
    if(!strcmp(argv[1],"assembly")) return assembly();
    if(!strcmp(argv[1],"receiver")) return receiver();
    return 2;
}
'''

with tempfile.TemporaryDirectory(prefix='chiaki-assembly-', dir=os.environ.get('TMPDIR')) as tmp:
    tmp = Path(tmp)
    stubs = tmp / 'chiaki'
    stubs.mkdir()
    (stubs / 'session.h').write_text('''#pragma once
#include <chiaki/videoreceiver.h>
typedef struct chiaki_session_t { ChiakiLog *log; bool (*video_sample_cb)(uint8_t*,size_t,void*); void *video_sample_cb_user; int stream_connection; } ChiakiSession;
''')
    (stubs / 'streamconnection.h').write_text('''#pragma once
ChiakiErrorCode stream_connection_send_idr_request(int *);
ChiakiErrorCode stream_connection_send_corrupt_frame(int *, ChiakiSeqNum16, ChiakiSeqNum16);
''')
    (stubs / 'time.h').write_text('#pragma once\nuint64_t chiaki_time_now_monotonic_ms(void);\n')
    c = tmp / 'test.c'
    c.write_text(preamble.replace('FRAMEPROCESSOR', str(root / 'lib/src/frameprocessor.c')).replace('VIDEORECEIVER', str(root / 'lib/src/videoreceiver.c')))
    exe = tmp / 'test'
    gf = root / 'third-party/gf-complete'
    jer = root / 'third-party/jerasure'
    flags = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer'] if os.environ.get('SANITIZE') else []
    # Compile dependencies separately: upstream code has warnings on modern cc.
    objs = []
    sources = [*sorted((gf / 'src').glob('*.c')), *(jer / 'src' / x for x in ['jerasure.c', 'galois.c', 'cauchy.c']), root / 'lib/src/fec.c']
    includes = ['-I'+str(p) for p in [tmp, root / 'lib/include', gf / 'include', jer / 'include']]
    for i, source in enumerate(sources):
        obj = tmp / f'{i}.o'
        subprocess.run(['cc', '-std=c11', '-D_GNU_SOURCE', '-w', *flags, *includes, '-c', str(source), '-o', str(obj)], check=True)
        objs.append(str(obj))
    subprocess.run(['cc', '-std=c11', '-D_GNU_SOURCE', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', *flags, *includes, str(c), *objs, '-lm', '-o', str(exe)], check=True)
    for case in sys.argv[1:] or ['boundary', 'allocation', 'insertion', 'assembly', 'receiver']:
        subprocess.run([str(exe), case], check=True)
        print('PASS', case, flush=True)
