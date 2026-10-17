"""Single velocity gate; fail closed. Watchdog is cooperative, never a hardware E-stop."""
from __future__ import annotations
import atexit
import math
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple
from .command import VelocityCommand
from .motion_lock import MotionLock, MotionLockError
from .motion_evidence import MotionEventLog


class MotionMode(str, Enum):
    DRY_RUN = 'dry-run'
    LIVE = 'live'


@dataclass
class AdapterLimits:
    max_vx: float = .10
    max_vy: float = .00
    max_wz: float = .15
    command_timeout_s: float = .25
    command_duration_s: float = 1.
    comm_fail_stop: bool = True


def direction_command(direction, speed=.04, duration=.2):
    if not math.isfinite(speed) or speed <= 0:
        raise ValueError('speed must be finite and positive')
    axes = {'forward':(speed,0,0),'back':(-speed,0,0),'backward':(-speed,0,0),
            'left':(0,speed,0),'right':(0,-speed,0),'yaw':(0,0,speed),
            'yaw_left':(0,0,speed),'yaw_right':(0,0,-speed)}
    if direction not in axes: raise ValueError('unknown direction')
    return VelocityCommand(*axes[direction],duration_s=duration,source='move_once:'+direction)


@dataclass
class G1MotionAdapter:
    backend: object
    owner: str = 'gdps_g1_navigation'
    limits: AdapterLimits = field(default_factory=AdapterLimits)
    mode: MotionMode = MotionMode.DRY_RUN
    live_token: str = ''
    lock_path: Optional[str] = None
    motion_authority_confirmed: bool = False
    allowed_live_fsm_ids: Tuple[int,...] = ()
    authority_evidence_id: str = ''
    data_source: str = 'SYNTHETIC_TEST'
    event_log: object = None
    _lock: Optional[MotionLock] = None
    last_return_code: Optional[int] = None
    last_velocity_rpc_code: Optional[int] = None
    last_stop_return_code: Optional[int] = None
    last_command: Optional[VelocityCommand] = None
    last_command_monotonic: float = 0.
    last_error: str = ''
    last_log_error: str = ''
    dry_run_history: list = field(default_factory=list)
    physical_motion_verified: bool = False
    _closed: bool = False
    _live_enabled: bool = False

    def __post_init__(self):
        if self.event_log is None: self.event_log = MotionEventLog(data_source=self.data_source)
        atexit.register(self.close)

    def _event(self,event,**details):
        try:
            self.event_log.emit(event,mode=self.mode.value,**details)
            return True
        except Exception:
            self.last_log_error = 'event log write failed'
            return False

    @staticmethod
    def _code(value):
        if type(value) is not int: raise ValueError('missing/non-integer RPC status')
        return value

    def _owns_lock(self):
        return self._lock is not None and self._lock._handle is not None

    def connect(self):
        if self._closed: return -31
        if self._owns_lock(): return self.last_return_code
        try:
            self._lock = MotionLock.acquire(self.owner,self.lock_path)
        except MotionLockError:
            self.last_error,self.last_return_code = 'motion lock unavailable',-30
            self._event('errors',code=-30,reason='lock_unavailable')
            return -30
        try: code = self._code(self.backend.connect())
        except Exception: code = -11
        self.last_return_code = code
        self._event('connect',code=code,backend=getattr(self.backend,'name','unknown'))
        if code != 0:
            self.last_error = 'backend connect failed: '+str(code)
            self._release_lock()
        return code

    def enable_live(self,token,confirm_phrase):
        if os.environ.get('GDPS_G1_LIVE') != '1': raise PermissionError('site LIVE transport gate closed')
        if not self.live_token or token != self.live_token: raise PermissionError('live token mismatch')
        if confirm_phrase != 'ENABLE LIVE MOTION': raise PermissionError('confirm phrase mismatch')
        self.mode,self._live_enabled = MotionMode.LIVE,True
        self.limits.max_vy = float(getattr(self,'_live_max_vy',0.))
        # This does not grant nonzero velocity authority.

    def clamp(self,command):
        values = (command.vx,command.vy,command.wz,command.duration_s)
        limits = (self.limits.max_vx,self.limits.max_vy,self.limits.max_wz,
                  self.limits.command_duration_s,self.limits.command_timeout_s)
        if not all(math.isfinite(v) for v in values+limits) or any(v < 0 for v in limits):
            raise ValueError('non-finite command or invalid limits')
        if not 0 < command.duration_s <= self.limits.command_duration_s or self.limits.command_timeout_s <= 0:
            raise ValueError('duration outside configured bounds')
        return VelocityCommand(max(-limits[0],min(limits[0],command.vx)),
            max(-limits[1],min(limits[1],command.vy)),max(-limits[2],min(limits[2],command.wz)),
            command.duration_s,command.source)

    def _authorize_nonzero_velocity(self):
        from .mock_backend import MockLocoBackend
        if (not self._live_enabled or os.environ.get('GDPS_G1_LIVE') != '1'
                or not self.motion_authority_confirmed or not self.allowed_live_fsm_ids):
            return -40
        if not isinstance(self.backend,MockLocoBackend) and (self.data_source != 'REAL_SENSOR' or not self.authority_evidence_id):
            return -40
        if any(type(x) is not int or x < 0 for x in self.allowed_live_fsm_ids): return -42
        try:
            start = time.monotonic()
            code,fsm = self.backend.get_fsm_id()
            valid = (self._code(code)==0 and type(fsm) is int and fsm >= 0 and time.monotonic()-start <= 1.)
            if not self._event('read',method='fsm_id',code=code if type(code) is int else -15,value=fsm if valid else None): return -43
            if not valid: return -41
            return 0 if fsm in self.allowed_live_fsm_ids else -42
        except Exception:
            self._event('errors',code=-41,reason='fsm_query_failed')
            return -41

    def _reject(self,code,reason):
        # A rejected renewal must stop a preceding outstanding command.
        if self.mode is MotionMode.LIVE and self._owns_lock() and self.last_command and not self.last_command.is_zero():
            self.stop('rejected_renewal')
        self.last_return_code,self.last_error = code,reason
        self._event('errors',code=code,reason=reason)
        return code

    def send_velocity(self,command):
        if self._closed: return self._reject(-31,'adapter_closed')
        if not self._owns_lock(): return self._reject(-32,'motion_lock_not_held')
        if not isinstance(command,VelocityCommand): return self._reject(-33,'invalid_command')
        requested = dict(vx=command.vx,vy=command.vy,wz=command.wz,duration_s=command.duration_s)
        audit_ok = self._event('command_requested',command=requested)
        try: clamped = self.clamp(command)
        except (ValueError,TypeError,OverflowError): return self._reject(-33,'invalid_command')
        if self.mode is MotionMode.LIVE and not clamped.is_zero():
            if not audit_ok: return self._reject(-43,'audit_unavailable')
            code = self._authorize_nonzero_velocity()
            if code != 0: return self._reject(code,'motion_authority_or_fsm_rejected')
        self.last_command,self.last_command_monotonic = clamped,time.monotonic()
        if self.mode is MotionMode.DRY_RUN:
            self.dry_run_history.append(clamped)
            self.last_return_code = 0
            return 0
        try:
            start = time.monotonic()
            code = self._code(self.backend.set_velocity(clamped))
            elapsed = time.monotonic()-start
            self.last_velocity_rpc_code = code
            if code == 0:
                if not self._event('rpc_accepted',code=0,elapsed_s=elapsed,physical_verified=False): code = -43
                if elapsed > self.limits.command_timeout_s: code = -34
        except Exception:
            code = -12
            self.last_velocity_rpc_code = None
        if code != 0:
            if self.limits.comm_fail_stop: self.stop('backend_error')
            return self._reject(code,'velocity_rpc_failed_or_late')
        self.last_return_code = code
        return code

    def watchdog_tick(self,now=None):
        """Cooperative polling only; no independent protection if caller/SDK blocks."""
        now = time.monotonic() if now is None else now
        if self.last_command is None or self.last_command.is_zero(): return None
        if now-self.last_command_monotonic <= self.limits.command_timeout_s: return None
        return self.stop('command_timeout')

    def stop(self,reason):
        zero = VelocityCommand(source='stop:'+reason)
        self._event('stop_requested',reason=reason)
        self.last_command,self.last_command_monotonic = zero,time.monotonic()
        if self.mode is MotionMode.DRY_RUN:
            self.dry_run_history.append(zero)
            code = 0
        elif not self._owns_lock(): code = -32
        else:
            try: code = self._code(self.backend.stop_move())
            except Exception: code = -13
        self.last_stop_return_code,self.last_return_code = code,code
        self.last_error = reason if code==0 else 'software_stop_rpc_failed:'+str(code)
        self._event('stop_rpc',code=code,physical_verified=False)
        return code

    def move_once(self,command,speed=.04,duration=.2):
        code,stop_code = -33,0
        error = ''
        try:
            if isinstance(command,str):
                command = direction_command(command,speed,duration)
            code = self.send_velocity(command)
            error = self.last_error
            if code==0 and self.mode is MotionMode.LIVE and not self.last_command.is_zero():
                time.sleep(self.last_command.duration_s)
        except (ValueError,TypeError,OverflowError):
            code = self._reject(-33,'invalid_direction_command')
            error = self.last_error
        finally:
            if self.mode is MotionMode.LIVE and self._owns_lock(): stop_code = self.stop('bounded_move_end')
        if code != 0:
            self.last_return_code,self.last_error = code,error
            return code
        return stop_code

    def stand_from_supine(self):
        # No audited site stand script is included in the repository. Never synthesize FSM transitions.
        result = dict(state='BLOCKED',execute_allowed=False,physical_completion='UNKNOWN',
            reason='preview_only_no_bound_site_script_or_fall_protection_evidence',
            required_conditions=['face_up_pose','not_charging','trained_operator','independent_estop',
                'physical_fall_protection','explicit_site_authorization','audited_stand_script','state_and_video_confirmation'])
        self._event('stand_preview',state='BLOCKED',physical_verified=False)
        return result

    def close(self):
        if self._closed: return
        try:
            if self._owns_lock(): self.stop('adapter_close')
            if hasattr(self.backend,'close'): self.backend.close()
        except Exception:
            self.last_error = 'backend_close_failed'
            self._event('errors',reason='backend_close_failed')
        finally:
            self._release_lock()
            self._closed = True

    def _release_lock(self):
        if self._lock is not None:
            self._lock.release()
            self._lock = None
