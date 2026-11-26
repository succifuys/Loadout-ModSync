"""Read the actual GameVersion constructor in Core's static initializer.

No JVM is launched, no class is modified. Unknown bytecode fails closed.
"""
import re
import struct
from .common import SyncError


def versions_from_core(data):
    pos=0
    def take(n):
        nonlocal pos
        if pos+n>len(data):
            raise SyncError('Truncated Java class')
        out=data[pos:pos+n]
        pos+=n
        return out
    def u2():
        return struct.unpack('>H',take(2))[0]
    def u4():
        return struct.unpack('>I',take(4))[0]
    if take(4)!=b'\xca\xfe\xba\xbe':
        raise SyncError('Invalid game Core class')
    take(4)
    count=u2()
    pool={}
    i=1
    sizes={3:4,4:4,5:8,6:8,7:2,8:2,9:4,10:4,11:4,12:4,15:3,16:2,17:4,18:4,19:2,20:2}
    while i<count:
        tag=take(1)[0]
        if tag==1:
            val=take(u2()).decode('utf-8',errors='replace')
        elif tag in sizes:
            val=take(sizes[tag])
        else:
            raise SyncError('Unknown constant pool tag')
        pool[i]=(tag,val)
        i+=2 if tag in (5,6) else 1
    def resolve(i):
        tag,val=pool[i]
        if tag==1:
            return val
        if tag in (7,8):
            return resolve(struct.unpack('>H',val)[0])
        if tag in (9,10,11,12):
            return tuple(resolve(j) for j in struct.unpack('>HH',val))
        if tag==3:
            return struct.unpack('>i',val)[0]
        return None
    def attrs():
        result={}
        for _ in range(u2()):
            name=resolve(u2())
            length=u4()
            result[name]=take(length)
        return result
    take(6)
    interfaces=u2()
    take(2*interfaces)
    build=None
    for _ in range(u2()):
        u2()
        name,descriptor=resolve(u2()),resolve(u2())
        attributes=attrs()
        if name=='buildVersion' and descriptor=='I' and 'ConstantValue' in attributes:
            build=resolve(struct.unpack('>H',attributes['ConstantValue'])[0])
    codes=[]
    for _ in range(u2()):
        u2()
        name,desc=resolve(u2()),resolve(u2())
        attributes=attrs()
        if name=='<clinit>' and 'Code' in attributes:
            raw=attributes['Code']
            codes.append(raw[8:8+struct.unpack_from('>I',raw,4)[0]])
    classes=[i for i,(tag,val) in pool.items() if tag==7 and resolve(i)=='zombie/core/GameVersion']
    constructors=[i for i,(tag,val) in pool.items() if tag==10 and resolve(i)==('zombie/core/GameVersion',('<init>','(IILjava/lang/String;)V'))]
    fields=[i for i,(tag,val) in pool.items() if tag==9 and resolve(i)==('zombie/core/Core',('gameVersion','Lzombie/core/GameVersion;'))]
    def literal(code,pos):
        op=code[pos]
        if 2<=op<=8:
            return op-3,pos+1
        if op==16:
            return struct.unpack_from('>b',code,pos+1)[0],pos+2
        if op==17:
            return struct.unpack_from('>h',code,pos+1)[0],pos+3
        if op==18:
            return resolve(code[pos+1]),pos+2
        if op==19:
            return resolve(struct.unpack_from('>H',code,pos+1)[0]),pos+3
        raise SyncError('Unsupported game version initializer')
    versions=set()
    for code in codes:
        for cls in classes:
            start=0
            marker=b'\xbb'+struct.pack('>H',cls)+b'\x59'
            while (start:=code.find(marker,start))>=0:
                try:
                    major,p=literal(code,start+4)
                    minor,p=literal(code,p)
                    suffix,p=literal(code,p)
                    constructor=struct.unpack_from('>H',code,p+1)[0]
                    field=struct.unpack_from('>H',code,p+4)[0]
                    if code[p]==183 and constructor in constructors and code[p+3]==179 and field in fields:
                        candidate=f'{major}.{minor}{suffix}.{build}'
                        if suffix or type(build) is not int:
                            continue
                        if re.fullmatch(r'42\.\d+\.\d+',candidate):
                            versions.add(candidate)
                except (SyncError,IndexError,struct.error,KeyError):
                    pass
                start+=len(marker)
    return versions

