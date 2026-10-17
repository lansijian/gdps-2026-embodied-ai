"""G1 official SDK2 locomotion backend. Compatible with the on-robot older SDK.

The real G1 PC2 SDK has LocoClient._Call(7001) but no public GetFsmId().
Do not patch or reinstall Unitree's SDK on the robot. Python 3.8 compatible.
"""
from __future__ import annotations

import json
import math
from typing import Optional, Tuple

G1_LOCO_SERVICE_NAME = "sport"
G1_LOCO_GET_FSM_ID_API_ID = 7001
G1_LOCO_GET_FSM_MODE_API_ID = 7002
G1_LOCO_GET_BALANCE_MODE_API_ID = 7003


class LocoReadOnlyClient:
    """SDK2 RPC adapter. RPC code=0 confirms delivery, NOT physical movement."""

    name = "unitree_loco_readonly"

    def __init__(self, network_interface: str, timeout_s: float = 1.0) -> None:
        if not network_interface:
            raise ValueError("network_interface must be verified on site")
        self._iface = network_interface
        self._timeout_s = timeout_s
        self._client = None
        if not math.isfinite(timeout_s) or not 0 < timeout_s <= 10:
            raise ValueError("RPC timeout must be within (0,10] seconds")
        self.last_error = ""

    def connect(self) -> int:
        try:
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize
            from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
        except ImportError as exc:
            self.last_error = repr(exc)
            return -10
        try:
            ChannelFactoryInitialize(0, self._iface)
            c = LocoClient()
            c.SetTimeout(self._timeout_s)
            c.Init()
            self._client = c
            return 0
        except Exception as exc:
            self.last_error = repr(exc)
            self._client = None
            return -11

    @staticmethod
    def rpc_code(value):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("missing or non-integer RPC status")
        return value

    @staticmethod
    def _decode_int(raw: object) -> int:
        if isinstance(raw, str):
            raw = json.loads(raw)
        if isinstance(raw, dict):
            raw = raw.get("data")
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ValueError("unexpected SDK integer RPC payload")
        return raw

    def _read_integer(self, method: str, api_id: int) -> Tuple[int, Optional[int]]:
        if self._client is None:
            return -2, None
        try:
            public_method = getattr(self._client, method, None)
            if callable(public_method):
                code, raw = public_method()
            else:
                lower = {"GetFsmId": "get_fsm_id", "GetFsmMode": "get_fsm_mode", "GetBalanceMode": "get_balance_mode"}[method]
                public_method = getattr(self._client, lower, None)
                if callable(public_method):
                    code, raw = public_method()
                else:
                    code, raw = self._client._Call(api_id, "{}")
            # Only the already-registered read-only query APIs are used.
            code = self.rpc_code(code)
            if code != 0:
                self.last_error = "{} RPC failed: {}".format(method, code)
                return code, None
            value = self._decode_int(raw)
            self.last_error = ""
            return 0, value
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self.last_error = "malformed {} response: {!r}".format(method, exc)
            return -15, None
        except Exception as exc:
            self.last_error = "{} transport failure: {!r}".format(method, exc)
            return -14, None

    def get_fsm_id(self) -> Tuple[int, Optional[int]]:
        return self._read_integer("GetFsmId", G1_LOCO_GET_FSM_ID_API_ID)

    def get_fsm_mode(self) -> Tuple[int, Optional[int]]:
        return self._read_integer("GetFsmMode", G1_LOCO_GET_FSM_MODE_API_ID)

    def get_balance_mode(self) -> Tuple[int, Optional[int]]:
        return self._read_integer("GetBalanceMode", G1_LOCO_GET_BALANCE_MODE_API_ID)

    def get_client_api_version(self):
        if self._client is None:
            return -2, None
        try:
            value = self._client.GetApiVersion()
            if not isinstance(value, str) or not value.strip():
                raise ValueError("invalid client API version")
            return 0, value
        except Exception:
            self.last_error = "client API version unavailable"
            return -15, None

    def get_server_api_version(self):
        if self._client is None:
            return -2, None
        try:
            code, value = self._client.GetServerApiVersion()
            code = self.rpc_code(code)
            if code != 0:
                self.last_error = "server API version RPC failed: {}".format(code)
                return code, None
            if not isinstance(value, str) or not value.strip():
                raise ValueError("missing server API version")
            self.last_error = ""
            return 0, value
        except Exception:
            self.last_error = "server API version response unavailable or malformed"
            return -15, None

    def close(self):
        self._client = None
