"""Conservative, standalone Godot 4 RSRC visible-property editor.

Format references (independent implementation, no engine code copied):
https://github.com/godotengine/godot/blob/master/core/io/resource_format_binary.cpp
https://github.com/godotengine/godot/blob/master/scene/resources/packed_scene.cpp

patch_resource(data, translations) defaults to FormatString only. Pass an explicit
allowed_properties subset of VISIBLE_PROPERTIES to also edit static UI strings.
PackedScene variants are NEVER overwritten: a fresh string variant is appended,
and only the selected node-property's value reference is changed. Thus a shared
original variant used by scripts, signals, node names, etc. remains untouched.
Unknown formats/types raise ValueError; callers must not silently patch them.
No filesystem writes, resource loading, script execution, or game startup occurs.
"""
from dataclasses import dataclass
from collections import Counter
import struct
import re

VISIBLE_PROPERTIES = frozenset({'FormatString', 'text', 'tooltip_text', 'placeholder_text'})

@dataclass
class Value:
    kind: int
    start: int
    end: int
    value: object

class Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.strings = []
        self.real_size = 4

    def take(self, count):
        if count < 0 or self.pos + count > len(self.data):
            raise ValueError('Resource is truncated or has an invalid count')
        b = self.data[self.pos:self.pos+count]
        self.pos += count
        return b

    def uint(self): return struct.unpack('<I', self.take(4))[0]
    def ulong(self): return struct.unpack('<Q', self.take(8))[0]
    def count(self):
        n = self.uint()
        if n > len(self.data): raise ValueError('Unreasonable resource count')
        return n

    def string(self):
        b = self.take(self.count())
        return b.rstrip(b'\x00').decode('utf-8', errors='strict')

    def name(self):
        n = self.uint()
        if n & 0x80000000:
            return self.take(n & 0x7fffffff).rstrip(b'\x00').decode('utf-8')
        if n >= len(self.strings): raise ValueError('Invalid property-name index')
        return self.strings[n]

    def variant(self, depth=0):
        if depth > 100: raise ValueError('Variant nesting exceeds safe limit')
        start = self.pos
        k = self.uint()
        value = None
        if k in (1, 42, 43): pass
        elif k in (2, 3, 23): value = self.uint()
        elif k in (40,): value = self.ulong()
        elif k in (5, 44): value = self.string()
        elif k == 4: value = self.take(self.real_size)
        elif k == 41: value = self.take(8)
        elif k in (10,11,12,13,14,15,16,17,18,50,52):
            value = self.take({10:2,11:4,12:3,13:4,14:4,15:6,16:9,17:12,18:6,50:4,52:16}[k]*self.real_size)
        elif k in (20,45,46,47,51):
            value = self.take({20:4,45:2,46:4,47:3,51:4}[k]*4)
        elif k == 22:
            n, sub = struct.unpack('<HH', self.take(4))
            value = (sub & 0x8000, [self.name() for _ in range(n+(sub & 0x7fff))])
        elif k == 24:
            objtype = self.uint()
            if objtype == 0: value = (objtype,)
            elif objtype in (2,3): value = (objtype,self.uint())
            elif objtype == 1: value = (objtype,self.string(),self.string())
            else: raise ValueError(f'Unknown object encoding {objtype}')
        elif k in (26,30):
            n = self.uint() & 0x7fffffff
            if n > len(self.data)//4: raise ValueError('Unreasonable container count')
            value = ([(self.variant(depth+1),self.variant(depth+1)) for _ in range(n)] if k==26
                     else [self.variant(depth+1) for _ in range(n)])
        elif k == 31:
            n = self.count();value = self.take(n);self.take((-n)%4)
        elif k == 32:
            n = self.count();value = list(struct.unpack('<'+str(n)+'i',self.take(n*4)))
        elif k == 34:
            value = [self.string() for _ in range(self.count())]
        elif k in (33,35,36,37,48,49,53):
            n = self.count()
            width = {33:4,35:3*self.real_size,36:16,37:2*self.real_size,48:8,49:8,53:4*self.real_size}[k]
            value = self.take(n*width)
        else:
            raise ValueError(f'Unsupported RSRC variant type {k} at {start}')
        return Value(k,start,self.pos,value)

class Resource:
    def __init__(self, data):
        r = Reader(data)
        if r.take(4)!=b'RSRC': raise ValueError('Only uncompressed RSRC is supported')
        if r.uint()!=0: raise ValueError('Big-endian resources are not supported')
        r.uint() # Legacy real64 header field, superseded by flags.
        major, minor, fmt = r.uint(),r.uint(),r.uint()
        if major!=4 or not 4<=fmt<=6: raise ValueError('Unsupported Godot resource version')
        self.type = r.string()
        self.metadata_position = r.pos
        metadata_offset = r.ulong()
        if metadata_offset: raise ValueError('Resource with import metadata is unsupported')
        flags = r.uint()
        if flags & ~15: raise ValueError('Unknown resource header flags')
        r.real_size = 8 if flags&4 else 4
        r.ulong() # UID
        if flags&8:r.string()
        r.take(44)
        r.strings = [r.string() for _ in range(r.count())]
        self.externals = []
        for _ in range(r.count()):
            typ,path = r.string(),r.string()
            uid = r.ulong() if flags&2 else None
            self.externals.append((typ,path,uid))
        self.offsets = []
        for _ in range(r.count()):
            name = r.string();position = r.pos;offset = r.ulong()
            self.offsets.append((position,offset,name))
        self.header_end = r.pos
        if not self.offsets: raise ValueError('Missing internal resources')
        ordered = [o for _,o,_ in self.offsets]
        if ordered!=sorted(set(ordered)) or ordered[0]<r.pos:
            raise ValueError('Invalid internal resource offsets')
        self.resources = []
        for i,(_,offset,name) in enumerate(self.offsets):
            r.pos = offset;typ = r.string();props=[]
            for _ in range(r.count()):props.append((r.name(),r.variant()))
            limit = ordered[i+1] if i+1<len(ordered) else len(data)-4
            if r.pos>limit:raise ValueError('Resource overlaps its successor')
            if r.pos!=limit:raise ValueError('Unparsed bytes within resource body')
            self.resources.append((name,typ,props))
        if data[-4:]!=b'RSRC':raise ValueError('Missing RSRC trailer')

def _bundle_properties(v):
    if v.kind!=26:raise ValueError('PackedScene _bundled is not a dictionary')
    d={k.value:item for k,item in v.value if k.kind in (5,44)}
    if len(d)!=len(v.value):raise ValueError('Non-string/duplicate bundled keys')
    names=d['names'];variants=d['variants'];nodes=d['nodes']
    if names.kind!=34 or variants.kind!=30 or nodes.kind!=32:
        raise ValueError('Unexpected PackedScene pool types')
    version=d.get('version')
    if version and version.value not in (2,3):raise ValueError('Unsupported PackedScene version')
    if d['node_count'].kind!=3:raise ValueError('Invalid node count')
    ints=nodes.value;idx=0;properties=[]
    for node in range(d['node_count'].value):
        if idx+6>len(ints):raise ValueError('Truncated node record')
        parent,owner,typ,name,instance,count=ints[idx:idx+6];idx+=6
        node_name_index=name & ((1<<18)-1)
        if node_name_index>=len(names.value) or count<0:raise ValueError('Invalid node record')
        node_name=names.value[node_name_index]
        for _ in range(count):
            if idx+2>len(ints):raise ValueError('Truncated node properties')
            pname,pvalue=ints[idx:idx+2]
            pname &= (1<<30)-1
            if not 0<=pname<len(names.value) or not 0<=pvalue<len(variants.value):
                raise ValueError('Invalid property reference')
            properties.append((node,node_name,names.value[pname],pvalue,nodes.start+8+(idx+1)*4))
            idx+=2
        if idx>=len(ints):raise ValueError('Truncated group count')
        group_count=ints[idx];idx+=1
        if group_count<0 or idx+group_count>len(ints):raise ValueError('Invalid group count')
        idx+=group_count
    if idx!=len(ints):raise ValueError('Unparsed PackedScene node records')
    return d,properties

def visible_properties(data, allowed_properties=VISIBLE_PROPERTIES):
    """Return stable text locations and source strings without changing data."""
    allowed=frozenset(allowed_properties)
    if not allowed<=VISIBLE_PROPERTIES:raise ValueError('Property allowlist is not UI-only')
    r=Resource(data);out=[]
    for ri,(_,typ,props) in enumerate(r.resources):
        for name,v in props:
            if name in allowed and v.kind==5:
                out.append(dict(resource=ri,node=None,node_name=None,property=name,text=v.value))
            if typ=='PackedScene' and name=='_bundled':
                d,ps=_bundle_properties(v)
                for node,node_name,pname,vi,pos in ps:
                    sv=d['variants'].value[vi]
                    if pname in allowed and sv.kind==5:
                        out.append(dict(resource=ri,node=node,node_name=node_name,property=pname,text=sv.value))
    return out

def _string_variant(text):
    raw=text.encode('utf-8')+b'\x00'
    return struct.pack('<II',5,len(raw))+raw

def _compatible(source,target):
    if not isinstance(target,str) or '\x00' in target:raise ValueError('Invalid translation value')
    for pattern in (r'\{[^{}]*\}',r'\[[^\]]*\]'):
        if Counter(re.findall(pattern,source))!=Counter(re.findall(pattern,target)):
            raise ValueError('Translation changes a placeholder or markup token')

def patch_resource(data, translations, allowed_properties=('FormatString',)):
    """Return (new_bytes, records). Reparse and validate every applied change.

    records identify only the changed visible property, before and after.
    An empty dictionary yields byte-for-byte identity after full structural checks.
    """
    allowed=frozenset(allowed_properties)
    if not allowed<=VISIBLE_PROPERTIES:raise ValueError('Property allowlist is not UI-only')
    r=Resource(data);edits=[];records=[]
    for ri,(_,typ,props) in enumerate(r.resources):
        for name,v in props:
            if name in allowed and v.kind==5 and v.value in translations and translations[v.value]!=v.value:
                translated=translations[v.value];_compatible(v.value,translated)
                edits.append((v.start,v.end,_string_variant(translated)))
                records.append(dict(resource=ri,node=None,node_name=None,property=name,source=v.value,target=translated))
            if typ!='PackedScene' or name!='_bundled':continue
            d,ps=_bundle_properties(v);variants=d['variants'];new_variants=[];dedup={}
            for node,node_name,pname,vi,pos in ps:
                sv=variants.value[vi]
                if pname not in allowed or sv.kind!=5 or sv.value not in translations:continue
                translated=translations[sv.value]
                if translated==sv.value:continue
                _compatible(sv.value,translated)
                if translated not in dedup:
                    dedup[translated]=len(variants.value)+len(new_variants)
                    new_variants.append(_string_variant(translated))
                edits.append((pos,pos+4,struct.pack('<I',dedup[translated])))
                records.append(dict(resource=ri,node=node,node_name=node_name,property=pname,source=sv.value,target=translated))
            if new_variants:
                old_count=struct.unpack_from('<I',data,variants.start+4)[0]
                edits.append((variants.start+4,variants.start+8,struct.pack('<I',old_count+len(new_variants))))
                edits.append((variants.end,variants.end,b''.join(new_variants)))
    if not edits:return data,[]
    edits.sort(key=lambda e:(e[0],e[1]))
    for previous,current in zip(edits,edits[1:]):
        if previous[1]>current[0]:raise ValueError('Overlapping patch ranges')
    # Relocate internal resource body pointers. The original header remains fixed.
    for pos,offset,_ in r.offsets:
        delta=sum(len(new)-(end-start) for start,end,new in edits if end<=offset)
        if delta:edits.append((pos,pos+8,struct.pack('<Q',offset+delta)))
    edits.sort(key=lambda e:(e[0],e[1]))
    result=bytearray();cursor=0
    for start,end,new in edits:
        if start<cursor:raise ValueError('Overlapping header patch ranges')
        result.extend(data[cursor:start]);result.extend(new);cursor=end
    result.extend(data[cursor:]);result=bytes(result)
    modified=Resource(result)
    # Verify external refs, body identities, every existing Variant, and node stream.
    if r.type!=modified.type or r.externals!=modified.externals:
        raise AssertionError('Non-text resource metadata changed')
    if len(r.resources)!=len(modified.resources):raise AssertionError('Resource count changed')
    expected={(x['resource'],x['node'],x['property']):x['target'] for x in records}
    def plain(v):
        if v.kind==26:return [(plain(k),plain(x)) for k,x in v.value]
        if v.kind==30:return [plain(x) for x in v.value]
        return (v.kind,v.value)
    for ri,(old,new) in enumerate(zip(r.resources,modified.resources)):
        if old[:2]!=new[:2] or len(old[2])!=len(new[2]):raise AssertionError('Resource identity changed')
        for (on,ov),(nn,nv) in zip(old[2],new[2]):
            if on!=nn:raise AssertionError('Property name changed')
            if old[1]=='PackedScene' and on=='_bundled':
                od,op=_bundle_properties(ov);nd,np=_bundle_properties(nv)
                if od.keys()!=nd.keys():raise AssertionError('Bundled keys changed')
                if len(op)!=len(np):raise AssertionError('Node property count changed')
                for (a,an,p,av,apos),(b,bn,q,bv,bpos) in zip(op,np):
                    if (a,an,p)!=(b,bn,q):raise AssertionError('Node/property identity changed')
                    oldv=od['variants'].value[av];newv=nd['variants'].value[bv]
                    if (ri,a,p) in expected:
                        if newv.kind!=5 or newv.value!=expected[ri,a,p]:raise AssertionError('Text patch mismatch')
                    elif plain(oldv)!=plain(newv):raise AssertionError('Unapproved node property changed')
                for index,x in enumerate(od['variants'].value):
                    if plain(x)!=plain(nd['variants'].value[index]):raise AssertionError('Original shared variant changed')
                changed_positions={a[4] for a,b in zip(op,np) if a[3]!=b[3]}
                for index,(a,b) in enumerate(zip(od['nodes'].value,nd['nodes'].value)):
                    if a!=b and od['nodes'].start+8+index*4 not in changed_positions:
                        raise AssertionError('Non-property node data changed')
                for k in od:
                    if k not in ('variants','nodes') and plain(od[k])!=plain(nd[k]):
                        raise AssertionError('Connections or scene logic changed')
            elif (ri,None,on) in expected:
                if nv.kind!=5 or nv.value!=expected[ri,None,on]:raise AssertionError('Direct text patch mismatch')
            elif plain(ov)!=plain(nv):raise AssertionError('Non-text resource value changed')
    return result,records
