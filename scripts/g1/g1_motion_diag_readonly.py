#!/usr/bin/env python3
"""G1 status/watch only. No velocity, FSM-change, stand or stop RPC exists in this tool."""
from __future__ import annotations
import argparse
import contextlib
import json
import math
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from shared.robot_control.g1.loco_readonly import LocoReadOnlyClient
from shared.robot_control.g1.motion_evidence import NativeDdsEvidence, MotionEventLog, collect_snapshot


class OfflineQueryFixture:
    def connect(self): return 0
    def get_fsm_id(self): return 0,802
    def get_fsm_mode(self): return 0,0
    def get_balance_mode(self): return 7301,None
    def get_client_api_version(self): return 0,'SYNTHETIC_API_VERSION'
    def get_server_api_version(self): return 0,'SYNTHETIC_API_VERSION'
    def close(self): pass


def watch_native(client, evidence, seconds, errors, log):
    from unitree_sdk2py.core.channel import ChannelSubscriber
    from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_
    from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_
    subscribers=[]
    def receive(topic,msg):
        try: evidence.ingest(topic,msg)
        except Exception:
            if len(errors)<100: errors.append('invalid_native_dds:'+topic)
    try:
        for topic,typ in (('rt/odommodestate',SportModeState_),('rt/lowstate',LowState_)):
            sub=ChannelSubscriber(topic,typ)
            subscribers.append(sub)
            sub.Init(lambda msg,t=topic: receive(t,msg),10)
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline: time.sleep(min(.05,max(0,deadline-time.monotonic())))
        return collect_snapshot(client,evidence,event_log=log)
    finally:
        for sub in reversed(subscribers):
            try: sub.Close()
            except Exception: errors.append('subscriber_close_failed')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('status','watch'))
    p.add_argument('--iface',default='eth0')
    p.add_argument('--seconds',type=float,default=8.)
    p.add_argument('--rpc-timeout',type=float,default=1.)
    p.add_argument('--mock',action='store_true',help='SYNTHETIC_TEST queries only; never fabricates DDS observations')
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    if not math.isfinite(args.seconds) or not 0<args.seconds<=30: p.error('seconds must be (0,30]')
    if not math.isfinite(args.rpc_timeout) or not 0<args.rpc_timeout<=2: p.error('RPC timeout must be (0,2]')
    if args.out.exists(): p.error('out already exists; choose a fresh evidence filename')
    source='SYNTHETIC_TEST' if args.mock else 'REAL_SENSOR'
    log=MotionEventLog(data_source=source)
    errors=[]
    client=OfflineQueryFixture() if args.mock else LocoReadOnlyClient(args.iface,args.rpc_timeout)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            code=client.connect()
            log.emit('connect',code=code)
            if args.action=='watch' and code==0 and not args.mock:
                try: snap=watch_native(client,NativeDdsEvidence(),args.seconds,errors,log)
                except Exception as exc:
                    errors.append('native_dds_unavailable:'+type(exc).__name__)
                    snap=collect_snapshot(client,data_source=source,event_log=log)
            else:
                snap=collect_snapshot(client,data_source=source,event_log=log,connect_code=code)
        report=snap.to_dict()
        report.update(errors=errors,event_log=str(log.path.resolve()),action=args.action,
                      interface=args.iface,dds_domain=0,live_motion=False,execute_allowed=False)
        log.emit('observed_motion' if report['state']=='MOTION_OBSERVED' else 'snapshot',snapshot=report)
        if errors: log.emit('errors',reason='readonly_diagnostic_incomplete',count=len(errors))
        args.out.parent.mkdir(parents=True,exist_ok=True)
        args.out.write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
        print(json.dumps(report,indent=2,allow_nan=False))
        return 0 if code==0 and report['fsm_id'] is not None and not errors and (args.action=='status' or report['observations_fresh']) else 1
    finally:
        client.close()  # Read-only client close never sends a stop or FSM RPC.

if __name__=='__main__':
    raise SystemExit(main())
