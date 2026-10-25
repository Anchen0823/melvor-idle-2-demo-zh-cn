"""Exercise the installer using an isolated EXE copy; never launch the game."""
import hashlib
import json
import shutil
import subprocess
import sys
import argparse
from patch import sha,is_reparse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DLL_REL = Path('data_GamesByMalcs.Melvor2_windows_x86_64') / 'GamesByMalcs.Melvor2.dll'
BASE = (ROOT / 'private' / 'installer-test').resolve()
REPORT = ROOT / 'build' / 'installer-validation.json'


def main(game):
    SOURCE=Path(game).resolve()/'Melvor2.exe'
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    BASE.mkdir(parents=True, exist_ok=True)
    assert BASE == ROOT / 'private' / 'installer-test'
    if is_reparse(BASE):
        raise RuntimeError('Refusing redirected test directory')
    sandbox = BASE / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+' 中文 Game Folder')
    sandbox.mkdir()
    assert sandbox.resolve().is_relative_to(BASE)
    exe = sandbox / 'Melvor2.exe'
    backup = sandbox / '.melvor-zh-cn-backup' / 'Melvor2.exe'
    original = manifest['original_sha256']
    patched = manifest['patched_sha256']
    results = dict(sandbox=str(sandbox), source=str(SOURCE), source_sha256_before=sha(SOURCE),
                   installer_sha256=sha(ROOT / 'patch.py'), manifest_sha256=sha(ROOT / 'manifest.json'),
                   payload_sha256=sha(ROOT / 'payload.json'),
                   game_started=False, steps=[], passed=False)
    assert results['source_sha256_before'] == original
    shutil.copyfile(SOURCE, exe)
    dll = sandbox / DLL_REL
    dll.parent.mkdir()
    shutil.copyfile(SOURCE.parent / DLL_REL, dll)
    results['source_dll_sha256'] = sha(SOURCE.parent / DLL_REL)

    def step(action, code=0, expected=None, label=None):
        before = sha(exe)
        backup_before = sha(backup) if backup.exists() else None
        run = subprocess.run([sys.executable,'-X','utf8', str(ROOT / 'patch.py'), action, '--game', str(sandbox)],
                             cwd=ROOT,input=action.upper()+'\n', capture_output=True, text=True,encoding='utf-8', timeout=180)
        after = sha(exe)
        backup_after = sha(backup) if backup.exists() else None
        item = dict(label=label or action, action=action, exit_code=run.returncode,
                    stdout=run.stdout.strip(), stderr=run.stderr.strip(),
                    before_sha256=before, after_sha256=after,
                    backup_before_sha256=backup_before, backup_after_sha256=backup_after)
        results['steps'].append(item)
        assert run.returncode == code, item
        if expected:
            assert after == expected, item
        if code:
            assert after == before and backup_after == backup_before, item
        elif action in ('install', 'uninstall'):
            assert backup_after == original, item
        return item

    def interactive(label,action,text,code=0,expected=None,no_write=True,explicit=None):
        before=sha(exe);bb=sha(backup) if backup.exists() else None
        command=[sys.executable,'-X','utf8',str(ROOT/'patch.py'),action]
        if explicit is not None:command.extend(['--game',explicit])
        run=subprocess.run(command,cwd=ROOT,input=text,capture_output=True,text=True,encoding='utf-8',timeout=180)
        after=sha(exe);ab=sha(backup) if backup.exists() else None
        item=dict(label=label,exit_code=run.returncode,stdout=run.stdout,stderr=run.stderr)
        results['steps'].append(item)
        assert run.returncode==code,item
        if no_write:assert (before,bb)==(after,ab),item
        if expected:assert after==expected,item
        if 'Type '+action.upper() in run.stdout:
            assert str(sandbox) in run.stdout and '26074343' in run.stdout,item
        return item

    def flip(path):
        assert path.resolve().is_relative_to(sandbox)
        with path.open('r+b') as stream:
            byte = stream.read(1)
            stream.seek(0)
            stream.write(bytes([byte[0] ^ 1]))

    try:
        interactive('blank-path-cancels','install','\n')
        interactive('cancel-word-cancels','install','Cancel\n')
        interactive('q-cancels','uninstall','Q\n')
        interactive('eof-cancels','install','')
        interactive('quoted-empty-path-cancels','install','""\n')
        interactive('explicit-empty-path-cancels','install','',explicit='')
        interactive('relative-path-rejected','install','.\n',code=1)
        interactive('missing-folder-rejected','install',str(sandbox/'missing')+'\n',code=1)
        empty=sandbox/'Empty Folder';empty.mkdir()
        interactive('missing-exe-rejected','install',str(empty)+'\n',code=1)
        interactive('double-quoted-chinese-space-path-cancel-confirm','install','"'+str(sandbox)+'"\n\n')
        interactive('eof-at-confirmation-cancels','install',str(sandbox)+'\n')
        interactive('wrong-confirmation-cancels','install',str(sandbox)+'\nyes\n')
        step('status', expected=original)
        interactive('quoted-chinese-space-path-install','install','"'+str(sandbox)+'"\nINSTALL\n',expected=patched,no_write=False)
        step('install', expected=patched, label='install-idempotency')
        step('status', expected=patched)
        interactive('uninstall-cancel-confirm','uninstall',str(sandbox)+'\n\n',expected=patched)
        interactive('single-quoted-chinese-space-path-uninstall','uninstall',"'"+str(sandbox)+"'\nUNINSTALL\n",expected=original,no_write=False)
        step('uninstall', expected=original, label='uninstall-idempotency')
        flip(dll)
        step('install', code=1, label='reject-one-byte-modified-game-dll')
        flip(dll)
        assert sha(dll) == results['source_dll_sha256']
        flip(exe)
        step('install', code=1, label='reject-one-byte-modified-original')
        flip(exe)
        assert sha(exe) == original
        step('install', expected=patched, label='reinstall-for-safety-tests')
        flip(exe)
        step('uninstall', code=1, label='reject-one-byte-modified-patched-exe')
        flip(exe)
        assert sha(exe) == patched
        flip(backup)
        step('install', code=1, label='reject-corrupted-backup-on-install')
        step('uninstall', code=1, label='reject-corrupted-backup-on-uninstall')
        flip(backup)
        assert sha(backup) == original
        step('uninstall', expected=original, label='restore-after-safety-tests')
        assert not list(sandbox.glob('*.tmp'))
        results['passed'] = True
    except Exception as exc:
        results['error'] = repr(exc)
        raise
    finally:
        results['source_sha256_after'] = sha(SOURCE)
        results['source_unchanged'] = results['source_sha256_before'] == results['source_sha256_after']
        results['source_dll_unchanged'] = results['source_dll_sha256'] == sha(SOURCE.parent / DLL_REL)
        results['installer_unchanged_during_test'] = results['installer_sha256'] == sha(ROOT / 'patch.py')
        results['final_test_exe_sha256'] = sha(exe)
        results['final_backup_sha256'] = sha(backup) if backup.exists() else None
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(dict(passed=results['passed'], steps=len(results['steps']),
                              source_unchanged=results['source_unchanged'], report=str(REPORT))))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game',required=True,help='Original game directory to copy read-only into the test sandbox')
    main(parser.parse_args().game)
