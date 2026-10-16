"""Optional Unitree SDK2 Python LocoClient backend (control path B).

Requires `unitree_sdk2py` on the robot (or a DDS-capable Linux host).
This module does not import the SDK until connect() is called.
"""

from __future__ import annotations

from .command import VelocityCommand

# Official G1 loco service name is still "sport" in unitree_sdk2_python
# (g1_loco_api.LOCO_SERVICE_NAME). That is not Go2 SportClient.
G1_LOCO_SET_VELOCITY_API_ID = 7105
G1_LOCO_SERVICE_NAME = "sport"


class UnitreeLocoBackend:
    """Wraps unitree_sdk2py.g1.loco.g1_loco_client.LocoClient.

    Allowed live calls: SetVelocity / StopMove / optional GetFsmId.
    Forbidden as software stop: ZeroTorque, Damp, SwitchToUserCtrl.
    """

    name = "unitree_loco"

    def __init__(self, network_interface: str, timeout_s: float = 10.0) -> None:
        if not network_interface:
            raise ValueError("network_interface is required and must be verified on site")
        self._iface = network_interface
        self._timeout_s = timeout_s
        self._client = None

    def connect(self) -> int:
        try:
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize
            from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
        except ImportError:
            return -10
        try:
            ChannelFactoryInitialize(0, self._iface)
            client = LocoClient()
            client.SetTimeout(self._timeout_s)
            client.Init()
            self._client = client
            return 0
        except Exception:
            self._client = None
            return -11

    def set_velocity(self, command: VelocityCommand) -> int:
        if self._client is None:
            return -2
        try:
            return int(
                self._client.SetVelocity(
                    float(command.vx),
                    float(command.vy),
                    float(command.wz),
                    float(command.duration_s),
                )
            )
        except Exception:
            return -12

    def stop_move(self) -> int:
        if self._client is None:
            return -2
        try:
            # Official StopMove() is SetVelocity(0,0,0); capture the RPC code.
            code = self._client.SetVelocity(0.0, 0.0, 0.0, 1.0)
            return int(code) if code is not None else 0
        except Exception:
            return -13

    def get_fsm_id(self) -> tuple[int, object | None]:
        """Read-only FSM query. Never used as a software stop."""
        if self._client is None:
            return -2, None
        try:
            code, data = self._client.GetFsmId()
            return int(code), data
        except Exception:
            return -14, None

    def close(self) -> None:
        self._client = None
