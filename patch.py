"""Offline, exact-version resource patch installer. Python 3.10+, stdlib only."""
import argparse, base64, hashlib, json, os, shutil, struct, sys, uuid, stat
from pathlib import Path

HERE=Path(__file__).resolve().parent
BACKUP='.melvor-zh-cn-backup'

def is_reparse(path):
    try:return bool(Path(path).lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except FileNotFoundError:return False

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()


def normalize_game(value):
    value=value.strip()
    if value.casefold() in ('','q','quit','cancel'):
        return None
    if len(value)>=2 and value[0]==value[-1] and value[0] in ('"',"'"):
        value=value[1:-1].strip()
    if not value:
        return None
    path=Path(value)
    if not path.is_absolute():
        raise RuntimeError('Please enter the full absolute path to the game installation folder.')
    return path.resolve()


def preflight(action,game):
    """Read-only checks before showing the target and requesting confirmation."""
    game=Path(game).resolve();exe=game/'Melvor2.exe'
    if not game.is_dir() or not exe.is_file():
        raise RuntimeError('Selected folder must contain Melvor2.exe. Nothing changed.')
    backup_dir=game/BACKUP;backup=backup_dir/'Melvor2.exe'
    if is_reparse(exe) or is_reparse(backup_dir) or is_reparse(backup):
        raise RuntimeError('Symlink/junction target refused')
    manifest=json.loads((HERE/'manifest.json').read_text(encoding='utf-8'))
    current=sha(exe);original=manifest['original_sha256'];patched=manifest['patched_sha256']
    if current not in (original,patched):
        raise RuntimeError('Unsupported EXE version/hash. Requires Melvor Idle 2 Demo build 26074343. Nothing changed.')
    if action in ('install','status'):
        for relative,expected in manifest.get('support_files',{}).items():
            if not (game/relative).is_file() or sha(game/relative)!=expected:
                raise RuntimeError('Game DLL version/hash mismatch. Nothing changed.')
    if action=='install':
        if sha(HERE/'payload.json')!=manifest['payload_sha256']:
            raise RuntimeError('Patch payload damaged. Nothing changed.')
        if backup_dir.exists() and not backup.is_file():
            raise RuntimeError('Existing backup directory is not a valid patch backup')
        if backup.exists() and sha(backup)!=original:
            raise RuntimeError('Existing backup differs; refusing overwrite')
    if current==patched and action in ('install','uninstall'):
        if not backup.is_file() or sha(backup)!=original:
            raise RuntimeError('Original backup missing or damaged. Use Steam Verify integrity.')
    return manifest,('installed' if current==patched else 'original')

def apply_payload(source,target,payload):
    """Build a separate EXE; edits are restricted to known PCK records/resources."""
    if Path(target).exists():raise RuntimeError('Temporary output already exists; refusing overwrite: '+str(target))
    with open(source,'rb') as src, open(target,'xb') as out:
        shutil.copyfileobj(src,out,4*1024*1024)
    with open(source,'rb') as src,open(target,'r+b') as dst:
        for item in payload['resources']:
            src.seek(item['source_offset']);original=src.read(item['source_size'])
            if hashlib.sha256(original).hexdigest()!=item['source_sha256']:
                raise RuntimeError('Resource mismatch: '+item['path'])
            result=bytearray();cursor=0
            for start,end,encoded in item['edits']:
                if not cursor<=start<=end<=len(original):raise RuntimeError('Invalid resource delta')
                result.extend(original[cursor:start]);result.extend(base64.b64decode(encoded,validate=True));cursor=end
            result.extend(original[cursor:]);result=bytes(result)
            if hashlib.sha256(result).hexdigest()!=item['target_sha256']:raise RuntimeError('Invalid resource checksum')
            dst.seek(0,2);dst.write(b'\0'*((-dst.tell())%16));offset=dst.tell();dst.write(result)
            record=item['record']
            if not payload['directory_start']<=record< payload['directory_end']-31:raise RuntimeError('Invalid PCK record')
            dst.seek(record);dst.write(struct.pack('<QQ16s',offset-payload['file_base'],len(result),hashlib.md5(result).digest()))

def perform(action,game):
    game=Path(game).resolve();exe=game/'Melvor2.exe'
    preflight(action,game) # Recheck after confirmation, immediately before any writes.
    manifest=json.loads((HERE/'manifest.json').read_text(encoding='utf-8'))
    current=sha(exe);original=manifest['original_sha256'];patched=manifest['patched_sha256']
    backup_dir=game/BACKUP;backup=backup_dir/'Melvor2.exe'
    if is_reparse(exe) or is_reparse(backup_dir) or is_reparse(backup):raise RuntimeError('Symlink/junction target refused')
    if action in ('install','status'):
        for relative,expected in manifest.get('support_files',{}).items():
            if sha(game/relative)!=expected:raise RuntimeError('Game DLL version/hash mismatch. Nothing changed.')
    if action=='status':
        print('Installed' if current==patched else 'Original / patch not installed' if current==original else 'UNSUPPORTED VERSION');return
    if action=='install':
        if current==patched:
            if not backup.exists() or sha(backup)!=original:raise RuntimeError('Patch present but original backup missing or changed')
            print('Already installed; no changes.');return
        if current!=original:raise RuntimeError('Version/hash mismatch. Nothing changed. Do not install after a Steam update.')
        payload_file=HERE/'payload.json'
        if sha(payload_file)!=manifest['payload_sha256']:raise RuntimeError('Patch payload damaged')
        payload=json.loads(payload_file.read_text(encoding='utf-8'))
        if backup_dir.exists() and not backup.exists():raise RuntimeError('Existing backup directory is not a valid patch backup')
        if backup.exists() and sha(backup)!=original:raise RuntimeError('Existing backup differs; refusing overwrite')
        backup_dir.mkdir(exist_ok=True)
        if not backup.exists():
            with exe.open('rb') as src,backup.open('xb') as dst:shutil.copyfileobj(src,dst,4*1024*1024)
        if sha(backup)!=original:raise RuntimeError('Backup verification failed')
        temp=game/('Melvor2.exe.zh-cn-'+uuid.uuid4().hex+'.tmp')
        try:
            apply_payload(exe,temp,payload)
            if sha(temp)!=patched:raise RuntimeError('Patched output hash mismatch; original remains intact')
            if sha(exe)!=original:raise RuntimeError('Game changed during build; original remains intact')
            os.replace(temp,exe)
        finally:
            if temp.exists():temp.unlink()
        print('Installed. Backup verified. Start the game normally through Steam.')
    elif action=='uninstall':
        if current==original:print('Already original; no changes. Backup retained.');return
        if current!=patched:raise RuntimeError('Game changed after patching. Refusing to overwrite. Use Steam Verify integrity instead.')
        if not backup.exists() or sha(backup)!=original:raise RuntimeError('Original backup missing or damaged. Use Steam Verify integrity.')
        temp=game/('Melvor2.exe.zh-cn-'+uuid.uuid4().hex+'.tmp')
        try:
            with backup.open('rb') as src,temp.open('xb') as dst:shutil.copyfileobj(src,dst,4*1024*1024)
            if sha(temp)!=original:raise RuntimeError('Restore verification failed')
            if sha(exe)!=patched:raise RuntimeError('Game changed during restore')
            os.replace(temp,exe)
        finally:
            if temp.exists():temp.unlink()
        print('Uninstalled. Original restored; verified backup retained. No save data was accessed.')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['install','uninstall','status'])
    parser.add_argument('--game',help='Explicit game installation directory; omitted means prompt. No default.')
    args=parser.parse_args()
    execution_started=False
    try:
        value=args.game
        if value is None:
            print('Enter the folder containing Melvor2.exe. Paste a full path; surrounding quotes are accepted.')
            print('请输入游戏安装目录；空输入、Q、Cancel 或 Ctrl+C 取消。不会自动选择任何目录。')
            value=input('Game directory / 游戏目录: ')
        game=normalize_game(value)
        if game is None:
            print('Cancelled. Nothing changed.');return 0
        manifest,state=preflight(args.action,game)
        print('Verified: Melvor Idle 2 Demo '+manifest['game_version']+' / Steam build '+str(manifest['steam_buildid']))
        print('Target / 目标: '+str(game))
        print('State: '+state+'; action: '+args.action)
        if args.action!='status':
            print('Backup / 备份: '+str(game/BACKUP/'Melvor2.exe'))
            print('请确认游戏已关闭，目标目录正确。')
            if args.action=='install':
                print('Resource changes invalidate the EXE digital signature. Never disable security protections.')
            answer=input('Type '+args.action.upper()+' to confirm, or Enter to cancel: ')
            if answer.strip().casefold()!=args.action:
                print('Cancelled. Nothing changed.');return 0
        execution_started=True
        perform(args.action,game)
        return 0
    except (EOFError,KeyboardInterrupt):
        if execution_started:
            print('\nInterrupted during execution. Check status and the verified backup before retrying.');return 130
        print('\nCancelled. Nothing changed.');return 0
    except Exception as exc:
        print('STOP: '+str(exc),file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())
