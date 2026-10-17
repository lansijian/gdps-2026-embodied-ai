#!/usr/bin/env python3
"""G1 Foxy rosbag2 extraction. Run on G1; Windows consumes derived JSON/NPY."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'tracks/quality-inspection')]
from field_evidence import EvidenceCollector, add_capture_arguments


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('bag_dir')
    p.add_argument('--max-messages', type=int, default=200000)
    add_capture_arguments(p)
    args = p.parse_args()
    if not 1 <= args.max_frames <= 200 or not 1 <= args.max_messages <= 2000000:
        p.error("max-frames must be 1..200 and max-messages 1..2000000")
    import rclpy
    from rclpy.serialization import deserialize_message
    from rosidl_runtime_py.utilities import get_message
    # Foxy branch predates modern rosbag2_py.SequentialReader on many installations.
    # Read the original rosbag2 sqlite storage read-only; deserialize only with G1 ROS type support.
    # This is an extraction adapter, never a replacement recording format.
    import sqlite3
    import heapq
    import yaml
    bag = Path(args.bag_dir)
    meta_file = bag / 'metadata.yaml'
    meta = yaml.safe_load(meta_file.read_text(encoding='utf-8'))['rosbag2_bagfile_information']
    if meta['storage_identifier'] != 'sqlite3':
        raise ValueError('unsupported_storage: use ros2 bag play with live collector')
    rclpy.init()
    connections = []
    try:
        collector = EvidenceCollector(args, 'RECORDED_REPLAY')
        entries = meta['topics_with_message_count']
        topics = {t['topic_metadata']['name']: t['topic_metadata'] for t in entries}
        collector.discovery = [{'topic': n, 'type': t['type']} for n,t in topics.items()]
        collector.qos = {n: t.get('offered_qos_profiles', 'see metadata.yaml') for n,t in topics.items()}
        selected = set(filter(None, [args.rgb_topic, args.depth_topic, args.camera_info_topic,
            args.pc_topic, args.scan_topic, args.odom_topic, '/tf', '/tf_static']))
        types = {n: get_message(t['type']) for n,t in topics.items() if n in selected}
        streams = []
        for relative in meta['relative_file_paths']:
            db = (bag / relative).resolve()
            if bag.resolve() not in db.parents:
                raise ValueError('bag path escapes bag directory')
            con = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)
            connections.append(con)
            streams.append(iter(con.execute('SELECT m.timestamp,t.name,m.data FROM messages m JOIN topics t ON t.id=m.topic_id ORDER BY m.timestamp,m.id')))
        count = 0
        merged = heapq.merge(*streams, key=lambda row: row[0])
        truncated = False
        for ts, name, data in merged:
            if count >= args.max_messages:
                truncated = True
                break
            if name in types:
                collector.ingest(name, deserialize_message(bytes(data), types[name]), ts)
            count += 1
        report = collector.finish()
        report['bag'] = str(bag)
        report['messages_scanned'] = count
        report['truncated'] = truncated
        # Preserve raw metadata/QoS verbatim alongside derived data.
        (Path(args.out_dir) / 'rosbag2_metadata.yaml').write_bytes((bag / 'metadata.yaml').read_bytes())
        (Path(args.out_dir) / 'evidence.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
        print(json.dumps({'out_dir': args.out_dir, 'counts': report['counts'], 'truncated': truncated}))
        return 1 if truncated or report["errors"] else 0
    finally:
        for con in connections:
            con.close()
        rclpy.shutdown()

if __name__ == '__main__':
    raise SystemExit(main())
