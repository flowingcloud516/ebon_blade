# Ebon Blade AI协作入口

> **文档定位**：仓库级AI协作入口。
>
> **主要作用**：规定AI进入项目后的阅读顺序、代码边界和最低验证要求。
>
> **使用方式**：任何AI开始分析或修改仓库前必须先读本文，再按链接读取系统和局部设计。

本仓库有大量AI参与。开始修改前必须按以下顺序读取设计：

1. [系统设计](design/system_design.md)。
2. 当前代码目录中与模块同名的`*_design.md`。
3. 当前具体实现目录中的`*_driver_design.md`或`*_connector_design.md`。
4. 内网仓库中同目录、同名前缀的`*_internal.md`（如果存在）。

`talk/`保存讨论历史，不是当前实现规范。讨论形成稳定结论后，必须更新对应设计文档；不能让后续实现只依赖聊天记录。

公共文件、协作文件和内部文件的边界见[代码所有权](design/code_ownership.md)及根目录`CODE_OWNERSHIP.toml`。内部敏感实现直接放在对应具体Driver目录，文件名使用`*_internal.py`；内部设计补充使用`*_design_internal.md`，不得把敏感内容写入公共设计。

修改代码后至少执行：

```powershell
.\.venv\Scripts\python.exe -c "import sys, unittest; sys.path.insert(0, 'src'); suite=unittest.defaultTestLoader.discover('tests'); result=unittest.TextTestRunner(verbosity=2).run(suite); raise SystemExit(0 if result.wasSuccessful() else 1)"
```

真实SSH、串口和设备测试是可选Live Test，不得因为本地没有内网设备而伪造成功。
