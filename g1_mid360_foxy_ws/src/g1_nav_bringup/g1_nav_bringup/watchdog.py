"""5s descendant-only RSS monitor. Resources merge into pipeline /g1_nav/health."""
import json
import os
from pathlib import Path
import signal
import time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


def processes(root):
    rows={}
    for directory in Path('/proc').glob('[0-9]*'):
        try:
            pid=int(directory.name)
            fields=(directory/'stat').read_text().rsplit(')',1)[1].split()
            status=dict(row.split(':',1) for row in (directory/'status').read_text().splitlines() if ':' in row)
            argv=(directory/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
            rows[pid]={'pid':pid,'ppid':int(fields[1]),'name':status.get('Name','').strip(),
                       'rss_kib':int(status.get('VmRSS','0 kB').split()[0]),'command':argv}
        except (OSError,ValueError,IndexError):continue
    descendants={root}
    for _ in range(len(rows)):
        added={pid for pid,row in rows.items() if row['ppid'] in descendants}-descendants
        if not added:break
        descendants.update(added)
    return [rows[pid] for pid in descendants if pid in rows and pid!=root]


class Watchdog(Node):
    def __init__(self):
        super().__init__('g1_nav_resource_watchdog')
        self.declare_parameter('standalone_health',False)
        self.root=os.getppid();self.errors=[]
        self.pub=self.create_publisher(String,'/g1_nav/resource_health',5)
        self.health=self.create_publisher(String,'/g1_nav/health',5) if self.get_parameter('standalone_health').value else None
        directory=Path(os.environ.get('G1_NAV_LOG_DIR',str(Path.home()/'.ros/g1_nav_logs')))
        directory.mkdir(parents=True,exist_ok=True)
        self.log=directory/('resources-stage3-%d.jsonl'%os.getpid())
        self.create_timer(5.,self.tick)

    def tick(self):
        rows=processes(self.root)
        for row in rows:
            if row['rss_kib']>2*1024*1024:
                # Topic ownership is resolved from discovered node names, never inferred from RSS alone.
                names={row['name']}
                command=row['command'].split()
                names.update(token.split(':=',1)[1] for token in command if token.startswith('__node:='))
                row['published_topics']={topic:[p.node_name for p in self.get_publishers_info_by_topic(topic) if p.node_name in names]
                    for topic,_ in self.get_topic_names_and_types()}
                row['published_topics']={k:v for k,v in row['published_topics'].items() if v}
                self.get_logger().warning('RSS_WARN '+json.dumps(row))
            if row['rss_kib']>4*1024*1024:
                reason='RSS_ERROR_PID_'+str(row['pid']);self.errors.append(reason)
                self.get_logger().error(reason+' '+json.dumps(row))
        report={'schema_version':1,'source':'resource_watchdog','realtime':time.time(),'processes':rows,
                'errors':sorted(set(self.errors))}
        message=String();message.data=json.dumps(report);self.pub.publish(message)
        if self.health:
            message=String();message.data=json.dumps({**report,'healthy':not self.errors,'reasons':report['errors'],'map_ready':False})
            self.health.publish(message)
        with self.log.open('a') as stream:stream.write(json.dumps(report)+'\n')
        for row in rows:
            if row['rss_kib']>4*1024*1024:
                try:os.kill(row['pid'],signal.SIGTERM)
                except ProcessLookupError:pass


def main(args=None):
    rclpy.init(args=args);node=Watchdog()
    from g1_nav_perception.runtime import spin
    spin(node)
