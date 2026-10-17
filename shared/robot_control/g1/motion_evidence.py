"""Motion evidence and audit events. Measurements never grant motion authority."""
from __future__ import annotations
import hashlib
import json
import math
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path


class MotionState(str, Enum):
    UNKNOWN = 'UNKNOWN'
    QUERY_OK_NOT_AUTHORIZED = 'QUERY_OK_NOT_AUTHORIZED'
    WALKABLE_CONFIRMATION_PENDING = 'WALKABLE_CONFIRMATION_PENDING'
    MOTION_OBSERVED = 'MOTION_OBSERVED'
    BLOCKED = 'BLOCKED'


def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k,v in value.items() if not any(s in k.lower() for s in ('password','token','secret'))}
    if isinstance(value, (tuple,list)):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class MotionEventLog:
    def __init__(self, path=None, data_source='SYNTHETIC_TEST'):
        self.path = Path(path or ('logs/field/g1-motion/events-'+uuid.uuid4().hex+'.jsonl'))
        self.data_source = data_source
        self._lock = threading.Lock()

    def emit(self, event, **details):
        row = clean(dict(event=event, timestamp_unix=time.time(), monotonic_s=time.monotonic(),
                         data_source=self.data_source, **details))
        with self._lock:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with self.path.open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(row,allow_nan=False,ensure_ascii=True)+'\n')


class NativeDdsEvidence:
    """Bounded aggregates of native DDS reads, separate from ROS/TF/navigation."""
    def __init__(self):
        self._lock = threading.Lock()
        self.topics = {}

    def ingest(self, topic, msg, received=None):
        received = time.monotonic() if received is None else received
        sensor_stamp = None
        if topic == 'rt/odommodestate':
            st = getattr(msg,'stamp',None)
            if st is not None:
                sensor_stamp = float(st.sec)+float(st.nanosec)*1e-9
            position = list(getattr(msg,'position',[]))
            velocity = list(getattr(msg,'velocity',[]))
            yaw_speed = getattr(msg,'yaw_speed',None)
        else:
            sensor_stamp = getattr(msg,'tick',None)  # Raw SDK tick, NOT ROS seconds or a high-level FSM.
            position,velocity,yaw_speed = [],[],None
        with self._lock:
            row = self.topics.setdefault(topic,dict(count=0,first_received=received,last_received=received,
                first_sensor_stamp=sensor_stamp,last_sensor_stamp=None,advancing_stamps=0,
                nonadvancing_stamps=0,first_position=None,last_position=None,last_velocity=None,
                last_yaw_speed=None,first_yaw=None,last_yaw=None,first_velocity=None,
                first_received_unix=time.time(),last_received_unix=time.time(),invalid_values=0))
            row['count'] += 1
            row['last_received'] = received
            row['last_received_unix'] = time.time()
            if sensor_stamp is not None:
                if row['last_sensor_stamp'] is not None:
                    row['advancing_stamps' if sensor_stamp > row['last_sensor_stamp'] else 'nonadvancing_stamps'] += 1
                row['last_sensor_stamp'] = sensor_stamp
            if topic == 'rt/odommodestate':
                if len(position)==3 and all(math.isfinite(x) for x in position):
                    if row['first_position'] is None: row['first_position'] = [float(x) for x in position]
                    row['last_position'] = [float(x) for x in position]
                else: row['invalid_values'] += 1
                if len(velocity)==3 and all(math.isfinite(x) for x in velocity):
                    if row['first_velocity'] is None: row['first_velocity'] = [float(x) for x in velocity]
                    row['last_velocity'] = [float(x) for x in velocity]
                else: row['invalid_values'] += 1
                rpy = list(getattr(getattr(msg,'imu_state',None),'rpy',[]))
                if len(rpy)==3 and math.isfinite(rpy[2]):
                    if row['first_yaw'] is None: row['first_yaw'] = float(rpy[2])
                    row['last_yaw'] = float(rpy[2])
                if yaw_speed is not None and math.isfinite(yaw_speed): row['last_yaw_speed'] = float(yaw_speed)
            elif hasattr(msg,'mode_machine'):
                row['lowstate_mode_machine'] = int(msg.mode_machine)

    def summary(self, now=None, max_age_s=.5):
        now = time.monotonic() if now is None else now
        with self._lock:
            rows = json.loads(json.dumps(clean(self.topics)))
        for row in rows.values():
            row['age_s'] = now-row['last_received']
            span = row['last_received']-row['first_received']
            row['hz'] = (row['count']-1)/span if span>0 else None
            row['fresh'] = (0 <= row['age_s'] <= max_age_s and row['count']>=2
                            and row['advancing_stamps']>0 and row['nonadvancing_stamps']==0 and row['invalid_values']==0)
            a,b = row['first_position'],row['last_position']
            row['position_delta'] = [y-x for x,y in zip(a,b)] if a is not None and b is not None else None
            va,vb = row['first_velocity'],row['last_velocity']
            row['velocity_delta'] = [y-x for x,y in zip(va,vb)] if va is not None and vb is not None else None
            ya,yb = row['first_yaw'],row['last_yaw']
            row['yaw_delta_rad'] = math.atan2(math.sin(yb-ya),math.cos(yb-ya)) if ya is not None and yb is not None else None
            row['direction_frame'] = 'native DDS odometry frame, uncalibrated to body directions'
        return rows


def reviewed_video(path, sha256, start_unix, end_unix, reviewer):
    """Only bind an externally reviewed evidence file; no automatic video-content verification."""
    file = Path(path)
    if (not reviewer or end_unix <= start_unix or file.stat().st_size == 0
            or hashlib.sha256(file.read_bytes()).hexdigest() != sha256):
        raise ValueError('invalid reviewed video evidence')
    return dict(path=str(file),sha256=sha256,start_unix=start_unix,end_unix=end_unix,
                reviewer=reviewer,reviewed=True)


@dataclass
class MotionSnapshot:
    data_source: str = 'SYNTHETIC_TEST'
    timestamp_unix: float = field(default_factory=time.time)
    monotonic_s: float = field(default_factory=time.monotonic)
    rpc_status: dict = field(default_factory=dict)
    fsm_id: object = None
    fsm_mode: object = None
    balance_mode: object = None
    sdk_client_api_version: object = None
    sdk_server_api_version: object = None
    firmware_version: str = 'UNKNOWN'
    dds: dict = field(default_factory=dict)
    independent_video: object = None
    authority_confirmed: bool = False
    allowed_fsm_ids: tuple = ()
    command_rpc_code: object = None
    blocked_reasons: list = field(default_factory=list)

    def to_dict(self):
        row = asdict(self)
        query = self.rpc_status.get('fsm_id',{})
        query_ok = (type(query.get('code')) is int and query['code']==0 and type(self.fsm_id) is int and self.fsm_id >= 0
                    and query.get('value')==self.fsm_id and 0 <= self.monotonic_s-query.get('received_monotonic',-1e9) <= 1.)
        fsm_matched = bool(query_ok and self.allowed_fsm_ids and self.fsm_id in self.allowed_fsm_ids)
        fresh = all(self.dds.get(t,{}).get('fresh',False) for t in ('rt/odommodestate','rt/lowstate'))
        odom = self.dds.get('rt/odommodestate',{})
        delta = odom.get('position_delta') or [0.,0.,0.]
        changed = math.sqrt(sum(x*x for x in delta)) >= .01 or abs(odom.get('yaw_delta_rad') or 0.) >= .02
        video = self.independent_video
        video_ok = False
        if video and video.get('reviewed'):
            try:
                reviewed_video(video['path'],video['sha256'],video['start_unix'],video['end_unix'],video['reviewer'])
                video_ok = (video['start_unix'] <= odom['first_received_unix']
                            <= odom['last_received_unix'] <= video['end_unix'])
            except (OSError,ValueError,KeyError,TypeError):
                pass
        observed = (self.data_source in ('REAL_SENSOR','RECORDED_REPLAY') and fresh and changed and video_ok)
        state = MotionState.UNKNOWN
        if self.blocked_reasons: state = MotionState.BLOCKED
        elif observed: state = MotionState.MOTION_OBSERVED
        elif query_ok:
            state = MotionState.WALKABLE_CONFIRMATION_PENDING if self.authority_confirmed and fsm_matched and fresh else MotionState.QUERY_OK_NOT_AUTHORIZED
        row.update(state=state.value,observations_fresh=fresh,independent_video_present=video_ok,
            capabilities={'SDK_RPC_ACCEPTED': type(self.command_rpc_code) is int and self.command_rpc_code==0,
                'FSM_MATCHED':fsm_matched,'DDS_OBSERVED':fresh,'PHYSICAL_ACTION_VERIFIED':False},
            execute_allowed=False,field_verified=False,live_motion=False)
        return clean(row)


def collect_snapshot(client, dds=None, data_source='REAL_SENSOR', event_log=None, connect_code=0):
    snapshot = MotionSnapshot(data_source=data_source)
    for key,method in (('fsm_mode','get_fsm_mode'),('balance_mode','get_balance_mode'),
                       ('sdk_client_api_version','get_client_api_version'),('sdk_server_api_version','get_server_api_version'),('fsm_id','get_fsm_id')):
        start = time.monotonic()
        try:
            code,value = getattr(client,method)() if connect_code==0 else (connect_code,None)
        except Exception:
            code,value = -14,None
        if type(code) is not int: code,value = -15,None
        snapshot.rpc_status[key] = dict(code=code,value=value if code==0 else None,received_monotonic=time.monotonic(),latency_s=time.monotonic()-start)
        setattr(snapshot,key,value if code==0 else None)
        if event_log:
            event_log.emit('read',method=key,code=code,value=value if code==0 else None)
    snapshot.monotonic_s = time.monotonic()
    snapshot.timestamp_unix = time.time()
    snapshot.dds = dds.summary(snapshot.monotonic_s) if dds else {}
    return snapshot
