# stable-panel-layout-optimization

## 为什么
用户反馈当前稳定版右侧策略建议区域存在两个布局问题：
1. 手牌结构区域（组合1/2/3）当组合较多时，内容被截断，高度没有自动撑开
2. 当前状态开始的硬算明细区域文字密集，但垂直空间被手牌结构挤压，导致需要滚动才能看全

用户希望：手牌结构区域高度能根据内容自动撑开；硬算明细区域采用更紧凑的两列布局，为手牌结构腾出空间的同时自身也能展示全部内容。

## 影响面
GitNexus impact:
- `StableBattlePanel`: LOW。仅影响 UI 布局参数和 HTML 格式化，无业务逻辑变更。
- `stable.hand_structure.build_hand_structure_arrangements`: 无影响，只调整展示容器。

## 业务规范关系
- 命中的主 spec: `stable-reader`
- 关系判断: Same Requirement / 追加 Scenario
- 推荐动作: 在右侧面板高度比例调整 Scenario 基础上追加布局优化，不新增独立能力。

## 改动范围
- `ui/stable_battle_panel.py`:
  - `_setup_ui()`: 调整 `_hand_structure_edit` 和 `_hard_calc_edit` 的尺寸策略
  - `_format_strategy_analysis_html()`: 将硬算明细从单列表改为两列布局
  - `_format_hand_structure_arrangements_html()`: 确保组合多时容器自动撑开

## 验收
- [x] 手牌结构区域（组合1/2/3）在组合较多时高度自动撑开，内容不被截断
- [x] 硬算明细区域采用两列布局，在常规窗口大小下无需滚动即可看到全部内容
- [x] 不修改任何业务逻辑、胡牌判定、向听计算
- [x] 已维护本 change 的回归测试用例
- [x] `gitnexus detect-changes --scope all -r mahjong-learning` 无异常范围外变更

## Bug 修复记录
无
