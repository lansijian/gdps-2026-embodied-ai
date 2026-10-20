"""Keep requested XML immutable; explicitly cap socket minimum to kernel capability."""
import json
from pathlib import Path
import re
import tempfile
import xml.etree.ElementTree as ET


def bytes_value(value):
    match=re.fullmatch(r'\s*(\d+)\s*(B|kB|KB|MB|GB)?\s*',value or '')
    if not match:raise ValueError('Unsupported DDS buffer size: '+str(value))
    return int(match[1])*{'B':1,None:1,'kB':1024,'KB':1024,'MB':1024**2,'GB':1024**3}[match[2]]


def prepare(path,cap=None,output=None):
    path=Path(path).resolve();tree=ET.parse(str(path));ns={'c':'https://cdds.io/config'}
    element=tree.find('.//c:MinimumSocketReceiveBufferSize',ns)
    report={'requested_profile':str(path),'effective_profile':str(path),'warnings':[]}
    if element is None:return report
    requested=bytes_value(element.text);report['requested_receive_minimum_bytes']=requested
    if cap is None:
        try:cap=int(Path('/proc/sys/net/core/rmem_max').read_text())
        except (OSError,ValueError):cap=None
    report['kernel_rmem_max_bytes']=cap
    if cap is not None and 0<cap<requested:
        applied=max(1,cap)
        if output is None:
            fd,name=tempfile.mkstemp(prefix='g1_nav_dds_',suffix='.xml')
            import os
            os.close(fd);output=name
        output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
        element.text=str(applied)+'B';ET.register_namespace('','https://cdds.io/config')
        tree.write(str(output),encoding='utf-8',xml_declaration=True)
        report.update(effective_profile=str(output.resolve()),applied_receive_minimum_bytes=applied,
                      warnings=['DDS_BUFFER_KERNEL_CAP: requested %d, applying %d bytes; NO sysctl change'%(requested,applied)])
        output.with_suffix('.json').write_text(json.dumps(report,indent=2))
    else:report['applied_receive_minimum_bytes']=requested
    return report
