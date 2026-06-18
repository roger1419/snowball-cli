# lessons.md — 经验教训

> 每次被用户纠正后追加一条。规则写给未来的自己，防止同类错误。

## 2026-06-18 · 雪球舆情「返回空」≠「无舆情」

**背景**：分析 SH688110（科创板·东芯股份）舆情时，`snowball kol SH688110` 返回 `[]`。我据此判断「该股无大 V 覆盖、社交讨论少」。

**用户纠正**：「雪球舆论爬取的有问题，帮我定位 snowball cli 是否有问题。」

**根因（定位后）**：空结果是工具/数据源限制，不是真实舆情结论。三层问题：

1. `kol` 底层接口 `/recommend/user/stock_hot_user.json` 对科创板（SH688xxx）及部分次新股**服务端直接返回 `[]`**——已跨多只标的（SH688110/SH688981/SH688256 vs 工作正常的 SH600519/SZ300750）确认，是雪球数据源限制，CLI 解析无误。
2. 个股「讨论」Tab 的正确接口 `/query/v1/symbol/search/status.json` 在 `xueqiu.com` 主站被**阿里云 WAF JS 挑战**拦截（返回 85KB 挑战页，任何 cookie 组合都拦），Bun fetch 无法解。但该接口在 `api.xueqiu.com` 子域**不设 WAF**，可直接取到 JSON。
3. `searchPosts`（`/statuses/search.json`）对所有关键词、所有 host 都返回空 body（HTTP 200、0 字节）——上游已废弃。

**修复**：新增 `stockPosts()`（走 `api.xueqiu.com`）+ `discuss` 命令；`request()` 对 null body 做空安全（`if (data && data.error_code)`）；`searchPosts`/`stockKOLs` 标注废弃/限制说明。已重建 dist 并同步到全局 `snowball` 安装。验证 `snowball discuss SH688110 --count 2` 返回真实讨论贴。

**写给自己的规则**：
- 凡是抓取类工具返回「空」，**先怀疑工具/数据源**，不要直接当结论上报。空数组是最危险的信号——它长得像「无数据」，实则是「没取到」。
- 定位时跨多只同类标的横向对比（工作正常的 vs 异常的），快速区分「数据源限制」与「解析 bug」。
- 同一接口在多个 host/子域上行为可能不同；被 WAF 拦时，优先试 app-API 子域（`api.xueqiu.com` 往往不走主站 WAF）。
- 空响应（`res.json()` → null）会让 `data.xxx` 抛 TypeError，掩盖真正原因——API 客户端对 null body 必须做空安全处理。
- 全局 npm 安装与源码目录是**两份独立副本**：修了源码 ≠ 用户的全局命令已生效，必须把 dist/lib/index 同步过去并端到端验证 `snowball <cmd>`。
