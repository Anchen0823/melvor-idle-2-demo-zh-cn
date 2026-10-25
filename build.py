"""Build redistributable text/resource deltas from the user's own installed copy."""
import base64, difflib, hashlib, json, re, struct
from collections import Counter
from pathlib import Path
from inspect_pack import ROOT,START,inventory
from scene_patch import patch_resource,VISIBLE_PROPERTIES
from patch import sha,apply_payload

def load_translations():
    merged={};conflicts=[]
    files=sorted((ROOT/'translations').glob('*.json'))
    files=[p for p in files if p.name!='overrides.json']+[ROOT/'translations/overrides.json']
    for p in files:
        data=json.loads(p.read_text(encoding='utf-8'))
        for s,t in data.items():
            for pattern in (r'\{[^{}]*\}',r'\[[^\]]*\]',r'res://[^\s\[\]"<>]+'):
                if Counter(re.findall(pattern,s))!=Counter(re.findall(pattern,t)):
                    raise ValueError(f'Token mismatch in {p.name}: {s}')
            if s in merged and merged[s]!=t:conflicts.append(s)
            merged[s]=t
    technical=set('CompletedDescription Description DialogueText DisplayName DisplayNameShort NumberFormat Observation ResistanceName ResistanceNameShort SightingText TemplateString'.split())
    return {s:t for s,t in merged.items() if s not in technical and s!=t},conflicts

def make_po(translations):
    pairs={};conflicts=[]
    data=json.loads((ROOT/'private/Data/Packages/MelvorDemo.json').read_text(encoding='utf-8-sig'))
    def add(a,b):
        if a in pairs and pairs[a]!=b:conflicts.append([a,pairs[a],b])
        else:pairs[a]=b
    def walk(x):
        if isinstance(x,dict):
            if isinstance(x.get('Singular'),str) and isinstance(x.get('Plural'),str):add(x['Singular'],x['Plural'])
            for v in x.values():walk(v)
        elif isinstance(x,list):
            for v in x:walk(v)
    walk(data)
    for a,b in json.loads((ROOT/'data/code_plural_pairs.json').read_text(encoding='utf-8')):add(a,b)
    if conflicts:raise ValueError(f'Conflicting plural pairs: {conflicts}')
    q=lambda s:json.dumps(s,ensure_ascii=False)
    out=['# Unofficial Simplified Chinese patch. English slot required by this demo.', 'msgid ""','msgstr ""',q('Project-Id-Version: Melvor2 unofficial zh-CN\n'),q('Language: en\n'),q('Content-Type: text/plain; charset=UTF-8\n'),q('Content-Transfer-Encoding: 8bit\n'),q('Plural-Forms: nplurals=2; plural=(n != 1);\n'),'']
    for s,t in sorted(translations.items()):
        out.append('msgid '+q(s))
        if s in pairs:
            plural=pairs[s]
            out.extend(['msgid_plural '+q(plural),'msgstr[0] '+q(t),'msgstr[1] '+q(translations.get(plural,t))])
        else:out.append('msgstr '+q(t))
        out.append('')
    return '\n'.join(out).encode('utf-8'),pairs

def delta(a,b):
    # Autojunk avoids expensive matching in binary padding. Unchanged spans remain local.
    sm=difflib.SequenceMatcher(None,a,b,autojunk=True)
    return [[i,j,base64.b64encode(b[k:l]).decode()] for op,i,j,k,l in sm.get_opcodes() if op!='equal']

def make_mo(translations,pairs):
    # The engine detects GNU MO magic even at the existing en.po path.
    # Binary strings avoid Godot PO c_unescape converting literal backslash-n twice.
    messages={b'':b'Project-Id-Version: Melvor2 unofficial zh-CN\nLanguage: en\nContent-Type: text/plain; charset=UTF-8\nPlural-Forms: nplurals=2; plural=(n != 1);\n'}
    for source,target in translations.items():
        if source in pairs:
            key=source+'\0'+pairs[source]
            value=target+'\0'+translations.get(pairs[source],target)
        else:key,value=source,target
        messages[key.encode('utf-8')]=value.encode('utf-8')
    rows=sorted(messages.items());n=len(rows);offset=28+16*n
    originals=[];translated=[];body=bytearray()
    for key,value in rows:
        originals.append((len(key),offset+len(body)));body.extend(key+b'\0')
    for key,value in rows:
        translated.append((len(value),offset+len(body)));body.extend(value+b'\0')
    return struct.pack('<7I',0x950412de,0,n,28,28+8*n,0,0)+b''.join(struct.pack('<II',*x) for x in originals+translated)+body

def build(game):
    EXE=Path(game).resolve()/'Melvor2.exe'
    baseline='c7249cff551d5420b7b1dd31f138cb55517e71105dc0c53e5952352c8e9bb3e4'
    dll_rel='data_GamesByMalcs.Melvor2_windows_x86_64/GamesByMalcs.Melvor2.dll'
    dll_hash='7352a8b5fd7275a19908059398babcc643ce7e30a428e2633b936f9f191c0af5'
    if sha(EXE)!=baseline or sha(EXE.parent/dll_rel)!=dll_hash:
        raise ValueError('Installed version differs from reviewed build 26074343')
    tr,conflicts=load_translations();po,pairs=make_po(tr);mo=make_mo(tr,pairs)
    build_dir=ROOT/'build';build_dir.mkdir(exist_ok=True)
    (build_dir/'zh_CN.po').write_bytes(po)
    (build_dir/'zh_CN.mo').write_bytes(mo)
    entries=inventory(EXE)['entries'];replacements={};records=[]
    with EXE.open('rb') as f:
        for e in entries:
            if e['path']=='Locale/en.po':
                f.seek(e['offset']);old=f.read(e['size']);replacements[e['path']]=(e,old,mo)
            elif e['path'].endswith(('.scn','.res')):
                f.seek(e['offset']);old=f.read(e['size'])
                new,changes=patch_resource(old,tr,VISIBLE_PROPERTIES)
                if changes:replacements[e['path']]=(e,old,new);records.extend([dict(path=e['path'],**r) for r in changes])
    payload={'file_base':START+112,'directory_start':min(e['record'] for e in entries)-512,'directory_end':max(e['record'] for e in entries)+36,'resources':[]}
    for name,(e,old,new) in replacements.items():
        payload['resources'].append(dict(path=name,record=e['record'],source_offset=e['offset'],source_size=e['size'],source_sha256=hashlib.sha256(old).hexdigest(),target_sha256=hashlib.sha256(new).hexdigest(),edits=delta(old,new)))
    (ROOT/'payload.json').write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    test=ROOT/'private/patched.exe'
    if test.exists():
        if not test.resolve().is_relative_to((ROOT/'private').resolve()):raise ValueError('Unsafe test path')
        test.unlink()
    apply_payload(EXE,test,payload)
    manifest={'patch_version':'0.2.0','game_version':'0.11.2 alpha.4','steam_appid':5373510,'steam_buildid':26074343,'engine':'4.7.2.stable.mono.official.ed1daf0bf','original_sha256':baseline,'patched_sha256':sha(test),'payload_sha256':sha(ROOT/'payload.json'),'support_files':{dll_rel:dll_hash}}
    (ROOT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    report={'translated_unique':len(tr),'plural_pairs':len(pairs),'scene_resources_changed':len(replacements)-1,'scene_properties_changed':len(records),'conflicting_translation_keys_resolved_by_merge':len(set(conflicts)),'payload_bytes':(ROOT/'payload.json').stat().st_size,'manifest':manifest}
    (build_dir/'coverage.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'private/scene_changes.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game',required=True,help='Game installation directory')
    build(parser.parse_args().game)
