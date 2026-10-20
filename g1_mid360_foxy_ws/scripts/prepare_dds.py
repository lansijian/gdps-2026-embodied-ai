"""Print effective file path; warnings go to stderr. Does not initialize DDS."""
from pathlib import Path
import argparse
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/g1_nav_perception'))
from g1_nav_perception.dds_profile import prepare

parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--output',required=True)
args=parser.parse_args();report=prepare(args.input,output=args.output)
for warning in report['warnings']:print('WARN '+warning,file=sys.stderr)
print(report['effective_profile'])
