"""Create a whitelist-only patch ZIP; never package the game or private copies."""
import json,zipfile,hashlib
from pathlib import Path
ROOT=Path(__file__).parent

def public_files():
    files=['README.md','NOTICE.md','DEVELOPMENT.md','VALIDATION.md','Install.cmd','Uninstall.cmd','patch.py','manifest.json','payload.json','extract.py','build.py','inspect_pack.py','scene_patch.py','resource_patch.py','verify_runtime.py','verify_installer.py','package_release.py']
    for directory in ('translations','data'):
        files.extend(str(p.relative_to(ROOT)).replace('\\','/') for p in sorted((ROOT/directory).glob('*.json')) if p.is_file())
    return files

def main():
    version=json.loads((ROOT/'manifest.json').read_text())['patch_version']
    name=f'MelvorIdle2Demo-zh-CN-{version}-build26074343'
    files=public_files()
    assert all(Path(p).suffix in ('.md','.cmd','.py','.json','.txt') for p in files)
    assert all(not p.startswith(('private/','build/')) for p in files)
    dest=ROOT/'dist';dest.mkdir(exist_ok=True);target=dest/(name+'.zip')
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for f in files:z.write(ROOT/f,name+'/'+f)
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        assert len(z.namelist())==len(files)
        for f in files:assert z.read(name+'/'+f)==(ROOT/f).read_bytes()
    checksum=hashlib.sha256(target.read_bytes()).hexdigest()
    (dest/'SHA256SUMS.txt').write_text(checksum+'  '+target.name+'\n',encoding='ascii')
    print(json.dumps(dict(path=str(target),bytes=target.stat().st_size,files=len(files),sha256=checksum,zip_crc_and_member_bytes_verified=True),indent=2))

if __name__=='__main__':main()
