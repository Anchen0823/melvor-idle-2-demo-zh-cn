# 本地构建与验证

环境：Windows、Python 3.10 或更新版本，仅使用 Python 标准库；无需收费 API、注入器、额外 pip 包或修改系统执行策略。

所有涉及游戏输入的命令都要求显式提供你自己的目录。以下尖括号内容是占位符，运行前请替换：

```powershell
python -X utf8 extract.py --game "<原版游戏安装目录>"
python -X utf8 build.py --game "<原版游戏安装目录>"
python -X utf8 verify_runtime.py
python -X utf8 verify_installer.py --game "<原版游戏安装目录>"
python -X utf8 package_release.py
```

`extract.py` 与 `build.py` 只接受已审阅的原始 EXE/DLL 哈希。已安装本补丁的目录不能作为原版构建输入。它们只读输入游戏，提取资料和输出 EXE 保存在本仓库的 `private/` 中；不要提交或分发这个目录。

构建流程：

- `inspect_pack.py` 解析当前限定版本 EXE 内未加密的 Godot PCK v4 目录。
- `translations/*.json` 保存原文到译文映射；`overrides.json` 最后合并，统一重复条目术语。
- `build.py` 校验占位符、标签、资源路径，并生成 GNU MO。原游戏固定使用英语语言槽，因此替换现有 `Locale/en.po` 路径的内容，保留英语复数分支与变量。
- `scene_patch.py` 解析 `.scn/.res`，只修改可见文本属性，并重新解析验证节点、引用、信号等结构不变。
- `payload.json` 保存资源差分；`patch.py` 在本地用用户自己的原文件重建资源，追加至 EXE 末尾，更新对应 PCK 索引。不修改机器代码或游戏 DLL。
- `package_release.py` 只打包固定白名单文件，不收集工作区全部内容。

`verify_runtime.py` 使用已有的 `private/patched.exe` 创建隔离引擎副本，替换测试副本的 `project.binary` 以启动自制测试场景，重定向用户数据目录，检查翻译加载与字体排版。它不启动游戏主流程。交付补丁本身不修改 `project.binary`。

`verify_installer.py` 先校验原版输入，再复制 EXE 与必需 DLL 到 `private/installer-test/`。其所有安装、卸载和损坏文件测试只针对复制件；不会启动游戏。完整本地测试日志可能含操作者路径，默认写入忽略的 `build/`，不要公开上传。

修改译文或补丁实现后必须重新验证并更新版本与校验值。不要修改预期哈希来强行兼容未知 Steam 更新。
