# Third-party notices

This repository does **not** vendor full upstream trees. Ideas and small adapted snippets:

| Upstream | Commit | License | Used for |
| --- | --- | --- | --- |
| https://github.com/guruadp/unitree-g1-slam-nav | b9a1fbd5459bda72a056e71eb8f9aa9a437f0228 | Apache-2.0 | Scan restamp idea; Nav2 layering; api_id 7105 JSON velocity |
| https://github.com/Hucebot/g1pilot | 5346e52191e97d3ec07312f23c87bb58a849fdf7 | BSD-3-Clause | Confirms LocoClient Move/StopMove in ROS nodes |
| https://github.com/unitreerobotics/unitree_sdk2_python | 814556d15970dd2ecf1c9984e845ca02ab07e206 | BSD-3-Clause | Official G1 `LocoClient` API (called at runtime if installed) |

Rebuild of `cmdvel_to_sport.py` / `scan_restamper.py` / `odom_tf_broadcaster.py` is original GDPS code with the same architectural intent, behind `G1MotionAdapter`.
