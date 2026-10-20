"""Opt-in SDK backend. No import/init occurs unless runtime allow_live is explicit.

Finite 0.1s SetVelocity leases, bounded RPC timeout, no FSM/stand/BalanceMode APIs.
Software leases are not an independently verified physical emergency stop.
"""
import importlib
import math


class LocoBackend:
    def __init__(self, interface, domain):
        if not interface or domain<0:
            raise ValueError('LIVE requires an explicitly verified SDK interface and domain')
        channel=importlib.import_module('unitree_sdk2py.core.channel')
        channel.ChannelFactoryInitialize(domain,interface)
        cls=importlib.import_module('unitree_sdk2py.g1.loco.g1_loco_client').LocoClient
        self.client=cls();self.client.SetTimeout(.15);self.client.Init()

    def send(self,velocity):
        vx,vy,wz=velocity
        if not all(math.isfinite(v) for v in velocity) or abs(vx)>.1 or vy!=0 or abs(wz)>.15:
            raise ValueError('SDK velocity outside hard limits')
        result=self.client.SetVelocity(float(vx),float(vy),float(wz),.1)
        if result!=0:
            raise RuntimeError('SDK SetVelocity failed: '+str(result))
