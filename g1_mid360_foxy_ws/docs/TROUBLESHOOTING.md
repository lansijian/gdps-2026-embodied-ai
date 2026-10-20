# Troubleshooting

| Observable error | Action |
|---|---|
| SITE_MISSING / null extrinsics | Copy template to config/site.yaml, retain unknowns, run sensor_check, measure calibration; never guess |
| BLOCKED_NEEDS_CALIBRATION | Verify full robot_center->livox_frame geometry, real floor/axes, stamp source and filter frequency; attach evidence IDs |
| SDK_NOT_INSTALLED | Read-only SDK source audit pending; no SDK is needed for dry-run navigation; do not replace factory SDK |
| APT_CANDIDATE_MISSING | Check architecture/source/index logs; plan pinned Foxy source fallback; do not install another distro |
| Dependency upgrade/removal blocked | New dependencies would alter existing installed packages; resolve with site operator review; no automated system upgrade |
| FUTURE_STAMP / STALE_STAMP / CLOCK_JUMP | Read 30-second raw clock report for all sources; inspect source clock and delay; no permanent 4883-second correction |
| TF_CALIBRATION_MISMATCH | Existing external TF disagrees with recorded calibration; inspect both, choose one verified owner and restart |
| TF_DUPLICATE_OWNER / TF_CONFLICT | Stop duplicate TF publisher, preserve logs, restart whole project; do not weaken monitor |
| PUBLISHER_COUNT:/scan | Stop other project conversion nodes; do not restart factory Livox driver |
| No /scan | Pipeline must accept cloud stamp/frame and verified geometry, TF lookup must work; pipeline itself supplies lazy scan demand |
| PREFLIGHT_FAILED | Read latest health reasons and gate log; downstream deliberately never started |
| AMCL not localized / costmap waits for map TF | Check real occupancy image and initial pose; use RViz 2D Pose Estimate; never publish static map->odom |
| Zero safe preview while /cmd_vel exists | Check map_ready, health reasons, obstacle_stop, heartbeat, source publisher count and command bounds; LIVE remains disabled even if preview becomes nonzero |
| Planner path exists but robot stays still | Expected SDK-free dry-run behavior; path is not hardware acceptance |
| Room has stairs/glass/negative obstacles | STOP; missing environmental guarantees cannot be fixed by inflation tuning |

Mapping quality, real localization convergence, dynamic avoidance and ARM64 load must be judged from target logs and recordings. No robot endpoint is assumed or discovered by scanning the network.
