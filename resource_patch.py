"""Minimal embedded-PCK resource replacement; never edits machine code."""
import struct, hashlib, shutil
from pathlib import Path
from inspect_pack import START, inventory

def replace_resources(source, target, replacements):
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve():
        raise ValueError('Build only into a separate file')
    if target.exists():
        raise FileExistsError(target)
    entries={e['path']:e for e in inventory(source)['entries']}
    missing=set(replacements)-set(entries)
    if missing:raise ValueError(f'Only existing resource paths can be changed: {missing}')
    shutil.copy2(source,target)
    with target.open('r+b') as f:
        f.seek(START+24);base=struct.unpack('<Q',f.read(8))[0]+START
        changes=[]
        for name,data in replacements.items():
            e=entries[name]
            if e['flags']:raise ValueError('Encrypted/special resource refused')
            f.seek(0,2);f.write(b'\0'*((-f.tell())%16));offset=f.tell();f.write(data)
            f.seek(e['record']);f.write(struct.pack('<QQ16s',offset-base,len(data),hashlib.md5(data).digest()))
            changes.append({'path':name,'record':e['record'],'offset':offset,'size':len(data)})
    return changes

def config_binary(values):
    def string(s):
        b=s.encode('utf-8');return struct.pack('<II',4,len(b))+b+b'\0'*((-len(b))%4)
    out=b'ECFG'+struct.pack('<I',len(values))
    for k,v in values.items():
        k=k.encode();v=struct.pack('<II',1,int(v)) if isinstance(v,bool) else string(v)
        out+=struct.pack('<I',len(k))+k+struct.pack('<I',len(v))+v
    return out

def add_qa_resources(source,target,replacements):
    """QA only: rebuild an unencrypted directory to add our isolated harness."""
    source,target=Path(source),Path(target)
    if target.exists():raise FileExistsError(target)
    es=inventory(source)['entries'];shutil.copy2(source,target)
    with target.open('r+b') as f:
        f.seek(START+24);base=struct.unpack('<Q',f.read(8))[0]+START
        new={}
        for name,data in replacements.items():
            f.seek(0,2);f.write(b'\0'*((-f.tell())%16));offset=f.tell();f.write(data)
            new[name]=dict(path=name,offset=offset,size=len(data),md5=hashlib.md5(data).hexdigest(),flags=0)
        combined=[new.pop(e['path'],e) for e in es]+list(new.values())
        f.seek(0,2);directory=f.tell();f.write(struct.pack('<I',len(combined)))
        for e in combined:
            name=e['path'].encode();name+=b'\0'*((-len(name))%4)
            f.write(struct.pack('<I',len(name))+name+struct.pack('<QQ16sI',e['offset']-base,e['size'],bytes.fromhex(e['md5']),e['flags']))
        f.seek(START+32);f.write(struct.pack('<Q',directory-START))
