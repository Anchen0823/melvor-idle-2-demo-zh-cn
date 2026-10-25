"""Isolated Godot resource/translation/font QA, with no game scripts or saves."""
import json, os, subprocess
from pathlib import Path
from inspect_pack import ROOT,inventory
from resource_patch import add_qa_resources,config_binary
from build import load_translations,make_po

SCRIPT=r'''extends Node
func _ready():
    var table = load("res://Locale/en.po")
    if table == null:
        push_error("PO_LOAD_FAILED")
        get_tree().quit(1)
        return
    TranslationServer.add_translation(table)
    TranslationServer.set_locale("en_GB")
    var cases = JSON.parse_string(FileAccess.get_file_as_string("res://qa_cases.json"))
    var failures = []
    var checked = 0
    for source in cases.translations:
        var result = TranslationServer.translate(source)
        if result != cases.translations[source]:
            failures.append(source)
        checked += 1
    for source in cases.plurals:
        if not cases.translations.has(source):
            continue
        var plural = cases.plurals[source]
        var expected = cases.translations.get(plural,cases.translations[source])
        if TranslationServer.translate_plural(source,plural,2) != expected:
            failures.append("PLURAL: " + source)
    print("PO_CHECKED ",checked," FAILURES ",failures.size())
    for item in failures.slice(0,10):print("MISMATCH ",item)
    var ts = TextServerManager.get_primary_interface()
    var missing = 0
    for font_path in cases.fonts:
        var font = load(font_path)
        var line = TextLine.new()
        line.add_string(cases.characters,font,20)
        var glyphs = ts.shaped_text_get_glyphs(line.get_rid())
        var count = 0
        for g in glyphs:
            if g.index == 0 or not g.font_rid.is_valid():count += 1
        print("FONT_CHECK ",font_path," GLYPHS ",glyphs.size()," MISSING ",count)
        missing += count
    print("QA_USER_PATH ",OS.get_user_data_dir())
    print("QA_COMPLETE")
    get_tree().quit(0 if failures.size()==0 and missing==0 else 2)
'''

def main():
    tr,_=load_translations();_,pairs=make_po(tr)
    fonts=['res://'+e['path'] for e in inventory(ROOT/'private/patched.exe')['entries'] if e['path'].endswith('.fontdata') and any(x in e['path'] for x in ('DefaultVariableFont.ttf','Default_Regular.ttf','Inter-VariableFont','Montserrat-VariableFont'))]
    chars=''.join(sorted({c for s in tr.values() for c in s if '\u3400'<=c<='\u9fff'}))
    cases=dict(translations=tr,plurals=pairs,characters=chars,fonts=fonts)
    qa=ROOT/'private/qa';target=qa/'TranslationQA.exe'
    qa.mkdir(parents=True,exist_ok=True)
    if target.exists():target.unlink()
    cfg=config_binary({'application/config/name':'MelvorZhResourceQA','application/run/main_scene':'res://qa.tscn','debug/file_logging/enable':False})
    additions={'project.binary':cfg,'qa_node.gd':SCRIPT.encode(),'qa_cases.json':json.dumps(cases,ensure_ascii=False).encode(),'qa.tscn':b'[gd_scene load_steps=2 format=3]\n[ext_resource type="Script" path="res://qa_node.gd" id="1"]\n[node name="QA" type="Node"]\nscript = ExtResource("1")\n'}
    add_qa_resources(ROOT/'private/patched.exe',target,additions)
    env=os.environ.copy()
    for k in ('APPDATA','LOCALAPPDATA','USERPROFILE','TEMP','TMP'):
        d=qa/k;d.mkdir(exist_ok=True);env[k]=str(d)
    proc=subprocess.run([str(target),'--headless','--log-file',str(qa/'translation.log')],cwd=qa,env=env,capture_output=True,timeout=50,creationflags=subprocess.CREATE_NO_WINDOW)
    result=proc.stdout.decode('utf-8',errors='replace')+proc.stderr.decode('utf-8',errors='replace')
    (ROOT/'build/runtime-validation.txt').write_text(result,encoding='utf-8');print(result)
    print('EXIT',proc.returncode,'UNIQUE_CJK_CHARACTERS',len(chars))
    return proc.returncode

if __name__=='__main__':raise SystemExit(main())
