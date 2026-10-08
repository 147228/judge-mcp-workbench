# 实际验收记录

验收日期：2026-10-08。环境：macOS、Python 3.12.14、MCP SDK 1.30.0，云端 `deepseek-flash`。原始 JSON、日志和截图与本文件一并提供。以下是小样例功能验收，不是泛化准确率或性能基准。

## 自动测试与直调

| 项目 | 实际结果 | 证据 |
| --- | --- | --- |
| Python 单元测试 | 24 passed | [`pytest.log`](../artifacts/pytest.log) |
| 依赖一致性 | `pip check` 通过 | `requirements-lock.txt` 记录当时版本 |
| Python / JavaScript 语法检查 | compileall、Node `--check` 通过 | 所有实现代码随仓库提供 |
| 不经 LLM 的直调 MCP | 工具发现、四个 progress、唯一工单、最终维修完成 | [`direct_demo.log`](../artifacts/direct_demo.log) |

单元测试覆盖三类故障、节点顺序、UUID 唯一性、非法输入、取消时状态、工具 schema 转换、调用 ID 回填、同轮重复调用、未知工具、非法参数，以及判断类型和原文引文校验。模型在单元测试中被模拟；这些测试不会消耗云端 token。

## 真实云端 Function Calling

证据：[`live_acceptance.json`](../artifacts/live_acceptance.json)、[`llm_acceptance.log`](../artifacts/llm_acceptance.log)。所有五个轮次通过，共记录 7,657 tokens。

| 场景 / 用户轮次 | 预期实际 MCP 调用数 | 实测 |
| --- | --- | --- |
| 闲聊 | 0 | 0，通过 |
| 明确 ATM-001 吞卡报修 | 1 | 1，收到四节点与最终工单 |
| 手机黑屏，范围外 | 0 | 0，通过 |
| 吞卡但缺设备号 | 0 | 0，追问编号 |
| 下一轮补充 ATM-002 | 1 | 1，沿用故障上下文并返回工单 |

这验证了本次模型与提示词的样例行为，不承诺所有表述永远不会误触发工具。

## 真实快速判断链路

请求经过 `网页 API → MCP quick_judge → 云端模型 → 类型 / 引文校验`，不是前端预置答案。证据：[`judge_acceptance.json`](../artifacts/judge_acceptance.json)。三类均收到 progress 1~4、结构化结果，类型与原文引文检查通过。

| 类型 | 本次结果 | 模型请求耗时 | 后端端到端耗时 | tokens |
| --- | --- | --- | --- | --- |
| Choice：登录验证码问题 | 账号与登录 | 1,209 ms | 1,471 ms | 362 |
| Boolean：无条件效果保证 | true | 734 ms | 754 ms | 338 |
| Score：明确行动步骤 | 5 / 5 | 718 ms | 740 ms | 371 |

这里的耗时是单次真实调用，受模型、请求长度和网络影响；不能用于证明与 Jev 的速度或准确率等价。

## 浏览器验收

在 Codex 内置浏览器操作真实页面，完成默认分类与条件检查；评分结果为 `4 / 5`，恢复历史记录后材料和结果一致。评分标准与上表的另一个 Score 样例不同，因此分数不应直接比较。

报修点击真实示例消息，创建了模拟工单 `ATM-9be93437be9542dfb46a6bc85d929b75`；四节点全部完成，并收到模型最终回复。390 × 844 的手机布局检查中，判断与报修页的文档宽度均为 390，无横向溢出；顶部入口可以切换。临时视口已恢复默认。

证据：[`browser_acceptance.json`](../artifacts/browser_acceptance.json)。截图：

- [分类工作台](../output/playwright/workbench-result.jpg)
- [评分结果](../output/playwright/score-result.jpg)
- [报修完成](../output/playwright/repair-complete.jpg)
- [手机评分](../output/playwright/mobile-score.jpg)
- [手机报修](../output/playwright/mobile-repair.jpg)

本次读取的控制台错误 / 警告为空。切换模板和修改输入会清除旧结果，避免把上一份材料的判断误当作当前结果。

## 未确认项与功能边界

- 没有在 Windows 真机执行；README 提供 Conda / PowerShell 安装与启动命令。
- JSON 导出按钮未取得内置浏览器的下载事件，没有宣称该浏览器下载验收通过；结构化结果显示和恢复已验证。可展开 JSON 复制，或使用 Chrome / Edge。
- 没有接入 Jev API、重现其训练，或提供校准概率。真实判断使用 DeepSeek。
- ATM 工单、派单与维修都是内存中的教学模拟；服务重启即丢失，不连接真实银行系统。
- 公开仓库与 ZIP 不包含 `.env`、模型密钥、虚拟环境、缓存和本机进程文件。重新安装需自备可用的兼容模型配置；无模型的直调可离线运行。

## 如何重新验收

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
# 先在另一终端运行 MCP 服务，或者运行 scripts/start_app.py
python scripts/mcp_direct_demo.py --debug
# 以下命令调用真实模型，会消耗自己的云端 token
python scripts/llm_acceptance.py --debug
```

快速判断可在网页中依次运行三个模板，并在“查看调用过程”核对真实 progress 和最终结果。重要业务场景应额外准备自己的标注数据，验证分类准确率、评分一致性与复核策略。
