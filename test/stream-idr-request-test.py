#!/usr/bin/env python3
"""Exercise actual IDR-request message against real nanopb encoding."""
from pathlib import Path
import os
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'lib/src/streamconnection.c').read_text()
start=s.index('CHIAKI_EXPORT ChiakiErrorCode stream_connection_send_idr_request(ChiakiStreamConnection *stream_connection)\n{')
block=s[start:]
pb=root/'build-host/lib/protobuf'
np=root/'third-party/nanopb'
assert (pb/'takion.pb.h').exists() and (pb/'takion.pb.c').exists() and (np/'pb_common.c').exists() and (np/'pb_encode.c').exists()
harness=r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include "pb.h"
#include "pb_encode.h"
#include "takion.pb.h"
#define CHIAKI_EXPORT
#define CHIAKI_LOGE(...) ((void)0)
#define CHIAKI_LOGI(...) ((void)0)
#define CHIAKI_ERR_SUCCESS 0
#define CHIAKI_ERR_UNKNOWN -1
typedef int ChiakiErrorCode;
typedef struct { void *log; int takion; } ChiakiStreamConnection;
static int sent; static uint8_t sent_flags; static uint16_t sent_channel; static uint8_t sent_buf[0x10]; static size_t sent_size;
ChiakiErrorCode chiaki_takion_send_message_data(int *takion, uint8_t chunk_flags, uint16_t channel, uint8_t *buf, size_t buf_size, void *seq_num) { (void)takion; (void)seq_num; sent++; sent_flags=chunk_flags; sent_channel=channel; memcpy(sent_buf,buf,buf_size); sent_size=buf_size; return CHIAKI_ERR_SUCCESS; }
'''+block+r'''
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); return 1; } } while(0)
int main(void) {
    ChiakiStreamConnection sc={0};
    CHECK(stream_connection_send_idr_request(&sc)==CHIAKI_ERR_SUCCESS);
    CHECK(sent==1); CHECK(sent_flags==1); CHECK(sent_channel==2);
    CHECK(sent_size==2); CHECK(sent_buf[0]==0x08 && sent_buf[1]==0x19);
    puts("PASS IDR request encodes TakionMessage{type=25} on channel 2");
}
'''
with tempfile.TemporaryDirectory(prefix='chiaki-idr-',dir=os.environ.get('TMPDIR')) as tmp:
    c=Path(tmp)/'test.c'; exe=Path(tmp)/'test'; c.write_text(harness)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(c),str(pb/'takion.pb.c'),str(np/'pb_common.c'),str(np/'pb_encode.c'),'-I',str(pb),'-I',str(np),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
