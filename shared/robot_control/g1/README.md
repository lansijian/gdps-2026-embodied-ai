# G1 high-level walking adapter

- Default: dry-run, mock backend.
- Live candidate: `UnitreeLocoBackend` → `LocoClient.SetVelocity` / `StopMove`.
- Optional: ROS `unitree_api/Request` api_id 7105 (unverified topics).
- Never call `ZeroTorque` / `Damp` for software stop.
- Never use Go2 `ObstaclesAvoidClient` as a G1 EDU API.
