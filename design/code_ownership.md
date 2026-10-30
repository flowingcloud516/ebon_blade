# 代码所有权与内外协作

> **文档定位**：仓库治理与内外协作设计。
>
> **主要作用**：定义外部专属、内外协作和内部专属文件的边界及Git同步方式。
>
> **使用方式**：决定代码或文档应该放在哪里、是否可以在内网修改时查阅。

状态：当前有效

最后复核：2026-10-28

## 1. 三类文件

### 外部专属

外部GitHub长期维护GUI、Environment Driver Core、Plan/Step/Executor、Connector、公共安全规则、公共测试和跨Driver公共步骤。内部发现不足时，应先提出脱敏需求，避免长期修改公共核心。

### 内外协作

具体Driver的`driver.py`、`plan.py`及公开设计允许内外共同完善。协作文件必须保持薄小，内部不做无关格式化和大范围重命名，把冲突限制在具体实现目录。

### 内部专属

真实芯片与拓扑、文件名和目录映射、命令、模板、Matcher、阈值、设备操作和最终Ready条件使用`*_internal.py`。内部设计差异使用`*_design_internal.md`，真实验证结果使用`*_validation_internal.md`。

## 2. Git同步

内网仓库保存GitHub完整代码并使用自己的Git远端：

- `origin`：内网Git，可拉取和推送；
- `upstream`：外部GitHub，只拉取；
- 周期性将`upstream/main`合并到内网分支；
- 不反复变基已经共享的内部历史；
- 非敏感的通用改进整理后回流GitHub，减少长期内部差异。

## 3. 当前不采用的方案

当前不建立独立`ebon_blade_sdk`，也不建立`internal_extensions/company_plugin`。内部实现与公共实现位于同一个具体Driver目录，通过文件名和所有权规则隔离。未来只有出现第三方插件、独立安装或跨仓库API兼容承诺时，才重新评估SDK。

机器可读的路径规则见根目录`CODE_OWNERSHIP.toml`。
