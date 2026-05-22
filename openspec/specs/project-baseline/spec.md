# Project Baseline Spec

## Purpose
定义项目初始化后的全局开发约束、目录约束、编码约束和变更流程约束。

## Requirements

### Requirement: OpenSpec 变更管控
所有代码变更 SHALL 先创建或复用 change，并完成 proposal.md、design.md、specs/<cap>/spec.md、tasks.md。

#### Scenario: 用户请求代码修改
- WHEN 用户请求修复、新增、重构、优化或修改项目文件
- THEN AI SHALL 先完成 OpenSpec 四件套
- AND 等待用户确认后再实施

### Requirement: GitNexus 影响面分析
编辑已有函数、类、接口、模块前 SHALL 使用 GitNexus 进行影响面分析。

#### Scenario: 修改已有 symbol
- WHEN 改动涉及已有函数、类、接口、模块
- THEN AI SHALL 先执行 `gitnexus impact <target> -r <alias> --depth <n>`
- AND 只读取 impact 命中的必要文件

### Requirement: 初始化先于实现
项目初始化时 SHALL 先建立 OpenSpec 基线和 GitNexus 索引，再生成业务代码。

#### Scenario: 新建项目或 AI 初始化项目
- WHEN 用户请求初始化项目、新建项目或生成项目模板
- THEN AI SHALL 先执行 Bootstrap
- AND 初始化 OpenSpec 基线
- AND 初始化 GitNexus 索引
- AND 再创建初始化 change

### Requirement: 回归测试归档门禁
每个 change SHALL 维护对应回归测试用例，归档前 SHALL 调用批量测试接口执行本 change 相关测试。

#### Scenario: 归档 OpenSpec 变更
- WHEN 用户要求归档 change
- THEN AI SHALL 先读取本 change 绑定的回归测试用例
- AND 调用批量测试接口执行这些测试
- AND 记录测试入参、关键出参、断言结果
- AND 只有接口调用成功且返回参数符合期望时才允许归档
- AND 如果测试入参或期望出参不清楚，AI SHALL 暂停咨询用户
