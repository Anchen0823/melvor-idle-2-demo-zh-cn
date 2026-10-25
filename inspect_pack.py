"""Read-only inventory of the installed, unencrypted Godot PCK."""
import struct, json, hashlib
from pathlib import Path

ROOT = Path(__file__).parent
START = 109411328

def inventory(path):
    with Path(path).open('rb') as f:
        f.seek(START)
        magic, version, major, minor, patch, flags, base, directory = struct.unpack('<4sIIIIIQQ', f.read(40))
        assert magic == b'GDPC' and version == 4
        if flags & 1:
            raise RuntimeError('Encrypted directory: stop; do not bypass')
        f.seek(START + directory)
        count, = struct.unpack('<I', f.read(4))
        entries = []
        for _ in range(count):
            length, = struct.unpack('<I', f.read(4))
            name = f.read(length).rstrip(b'\0').decode('utf-8')
            record = f.tell()
            offset, size, md5, entry_flags = struct.unpack('<QQ16sI', f.read(36))
            entries.append(dict(path=name,offset=START+base+offset,size=size,md5=md5.hex(),flags=entry_flags,record=record))
        return dict(format=version,engine=f'{major}.{minor}.{patch}',flags=flags,count=count,entries=entries)

if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game',required=True,help='Game installation directory')
    result = inventory(Path(parser.parse_args().game)/'Melvor2.exe')
    (ROOT/'private').mkdir(exist_ok=True)
    (ROOT/'private'/'inventory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print({k:v for k,v in result.items() if k!='entries'})
    from collections import Counter
    print(Counter(Path(x['path']).suffix for x in result['entries']))
    for e in result['entries']:
        if any(s in e['path'].lower() for s in ['local','translat','language','english','font','project.godot','project.binary']): print(e)
