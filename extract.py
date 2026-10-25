"""Read only the reviewed unencrypted resources needed to reproduce the build."""
import hashlib,json
from inspect_pack import ROOT,inventory
from pathlib import Path
from patch import sha
from scene_patch import Resource

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game',required=True,help='Game installation directory')
    EXE=Path(parser.parse_args().game).resolve()/'Melvor2.exe'
    if sha(EXE)!='c7249cff551d5420b7b1dd31f138cb55517e71105dc0c53e5952352c8e9bb3e4':
        raise SystemExit('Unsupported original EXE hash; nothing extracted')
    result=inventory(EXE);private=ROOT/'private';private.mkdir(exist_ok=True)
    (private/'inventory.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    with EXE.open('rb') as f:
        for e in result['entries']:
            if e['path'] not in ('Data/Packages/MelvorDemo.json','project.binary','Locale/en.po'):continue
            if e['flags']:raise RuntimeError('Encrypted/special resource refused')
            f.seek(e['offset']);b=f.read(e['size'])
            if hashlib.md5(b).hexdigest()!=e['md5']:raise RuntimeError('Resource hash mismatch')
            path=private/e['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b)
    print('Extracted private build inputs. Never distribute private/ or original game assets.')
