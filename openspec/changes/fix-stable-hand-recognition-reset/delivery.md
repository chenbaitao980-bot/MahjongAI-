# Delivery: fix-stable-hand-recognition-reset

## 完成内容
- 修复稳定版首个可信手牌包不会稳定进入 `playing` 状态的问题。
- 修复等待可信手牌状态下，下一局可信手牌包无法清空旧局弃牌/事件/回合残留的问题。
- 保持 0x0003 untrusted deal 不作为权威手牌，避免假开局手牌回归。

## 修改文件
- `stable/tracker.py`
- `tests/test_stable_reader.py`
- `regression-tests/cases/fix-stable-hand-recognition-reset.md`
- `openspec/changes/fix-stable-hand-recognition-reset/*`

## 验证
- `python -m pytest tests/test_stable_reader.py`
  - 未执行：当前 Python 环境未安装 `pytest`。
- `python -m unittest tests.test_stable_reader`
  - 通过：46 tests。
- `gitnexus detect-changes --scope all -r mahjong-learning`
  - 通过：影响范围集中在稳定版状态机和测试；风险 high，符合预期。

## 残余风险
- `PacketStateTracker._apply_game_event` 是稳定版实时抓包、历史回放、训练样本导出的核心路径，GitNexus 仍评估为 high risk。
- 本次已用稳定版读包单测覆盖关键路径，但未运行完整项目测试集。
