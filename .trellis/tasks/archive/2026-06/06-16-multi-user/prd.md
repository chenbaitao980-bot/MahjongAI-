 # 多用户场景改造：无配置模式支持多用户管理与手牌展示

 ## Goal

 将无配置模式（noconfig）从单用户单session改为支持多用户场景。后台管理页面可以配置多个用户，支持按用户名称搜索，选中某个用户后展示当前用户手牌。

 ## What I already know

 * 当前 `remote/noconfig/` 目录下是 noconfig 模式的 FastAPI 应用（app.py + main.py）
 * 当前 state_store 只保存单个 snapshot，没有用户维度
 * 前端页面 `remote/relay/static/index.html` 是单用户手牌展示页面
 * core.py 中的 RelayApp 已经支持多模式（hotspot/vpn/noconfig/cloud），每个模式独立端口
 * 无配置模式使用 SRS spectator 直连游戏服务器，通过 srs_sessionid 进行身份验证

 ## Assumptions (temporary)

 * 多用户场景下，每个用户有独立的 srs_sessionid（或类似的唯一标识）
 * 用户数据（手牌等）可以存储在内存中，不需要持久化数据库
 * 后台管理页面是一个独立的 HTML 页面，通过 API 获取用户列表和手牌数据
 * 搜索功能在前端实现，后端返回所有用户数据

 ## Open Questions

 * 用户认证方式：是否需要独立的用户认证系统，还是沿用 api_token？
 * 用户数据来源：多用户的手牌数据从哪里来？是否需要多个 extractor/spectator 实例？
 * 用户标识：使用 userid 还是 srs_sessionid 作为用户唯一标识？

 ## Requirements

 ### 功能需求
 1. **多用户数据模型**：支持存储多个用户的状态（手牌、sessionid、userid 等）
 2. **用户管理 API**：
    - GET `/api/users` - 获取所有用户列表
    - POST `/api/users` - 添加/注册用户
    - DELETE `/api/users/{user_id}` - 删除用户
    - GET `/api/users/{user_id}/hand` - 获取指定用户的手牌
 3. **后台管理页面**：
    - 独立的 `/admin` 路由
    - 展示用户列表表格
    - 支持按用户名称搜索（前端过滤）
    - 点击用户后展示该用户的手牌（复用现有的手牌渲染组件）
 4. **数据推送**：支持多用户的数据推送（extractor 或 spectator 推送数据时带上用户标识）

 ### 非功能需求
 * 保持向后兼容：单用户场景仍然可用
 * 内存存储足够（不需要数据库）
 * 管理页面风格与现有页面一致（暗色主题）

 ## Acceptance Criteria

 * [ ] 可以通过 `/admin` 访问后台管理页面
 * [ ] 管理页面展示多个用户，支持搜索
 * [ ] 点击用户后展示该用户的手牌
 * [ ] 多用户数据可以正常推送和展示
 * [ ] 单用户场景不受影响

 ## Definition of Done

 * 代码通过测试
 * 管理页面在不同屏幕尺寸下正常显示
 * 文档更新（如有必要）

 ## Out of Scope

 * 用户权限管理（RBAC）
 * 数据持久化（数据库）
 * 多用户同时在线的并发优化

 ## Technical Notes

 * 修改文件：
   - `remote/noconfig/app.py` - 添加多用户 API 和管理页面路由
   - `remote/noconfig/main.py` - 可能需要调整启动逻辑
   - `remote/relay/static/index.html` - 作为手牌展示组件复用
 * 新增文件：
   - `remote/noconfig/admin.html` - 后台管理页面
   - `remote/noconfig/user_store.py` - 用户数据存储
 * 参考：
   - `remote/relay/core.py` - RelayApp 的多模式实现
   - `remote/relay/state_store.py` - 状态存储实现
