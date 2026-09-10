# 集成状态与升级

本包给第三方提供可程序读取的 22 条经验、决策记录、A–I 模板、只读上下文导出和 CI。
它不改变当前生成、计费、剪辑、QA 或发布状态机；不升级生产环境依赖。

## 已实际消费

- `tools/knowledge_registry.py` 读取目录、验证唯一 ID、字段、实现状态、相对路径和文件存在性。
- 上下文导出按阶段提供规则、教训、修复路径，始终带 `production_authorization=false` 和 `media_qa_pass=false`。
- `qingshan knowledge` 为公开 CLI 入口（从源码部署）。
- CI 检查目录、链接、示例和回归；测试会调用现有动作因果校验，验证“未接触却标 CONTACT”的反例。

## 不冒充已完成

代码链接存在只证明相关实现存在。22 条不是 22 项已完成端到端验收。
整集有界导演 QA、BGM 自动绑定在本次检出的公共 main 中未核实完整消费链，明确标为 INTEGRATION_PENDING；不从私有工作树搬来未经审查的实现。
其它指导性政策不自动追加生产门禁。纯文档规则不能据此阻塞或放行付费任务。

## 新 Agent / 新部署如何继承

1. 执行 `qingshan knowledge --validate`，读取 README 和完整上下文导出。
2. 读取部署者自己的授权策略与私有 A–I 交接。
3. 为每条记录“已实现 / 缺文档 / 缺实现 / 单集例外 / 未核实”。
4. 复用原证据，核对 SHA 和实际消费者，不为“补交接”重复 POST 或伪造 PASS。
5. 只在授权范围内继续生产；知识读取不是授权。
6. 下载下一版后重新运行本包检查和项目原有 portable CI，不只相信文件名或历史测试数量。

## 不改变生产的回退

停止调用知识导出入口即可；目录与 CLI 没有任何网络或状态副作用。
代码回退用正常版本管理，不清空运行目录、事务锁或消费账单。

## 验证命令

```bash
python3 -m unittest tools.tests.test_knowledge_registry
python3 tools/knowledge_registry.py --validate
python3 tools/run_portable_ci.py
python3 tools/deployment_code_integrity.py
```

此处列命令而不硬编码测试通过数量；发布 CI 是对应提交的证据。无声看片、动态运动能量等检查未执行，不能标为通过。
