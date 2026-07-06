# 飞书 API 研究报告：消息卡片、流式更新、表情回复与 lark-oapi SDK

## 1. 消息卡片（Interactive Card Messages）

### 1.1 发送卡片消息

**API 端点**：`POST https://open.feishu.cn/open-apis/im/v1/messages`

关键参数：
- `receive_id_type`（query）：`open_id` / `user_id` / `chat_id`
- `receive_id`：接收者 ID
- `msg_type`：固定为 `"interactive"`
- `content`：卡片 JSON 序列化后的字符串

**频率限制**：1000 次/分钟、50 次/秒

**权限要求**（任一即可）：
- `im:message`（获取与发送单聊、群组消息）
- `im:message:send_as_bot`（以应用身份发消息）
- `im:message:send`（发送消息 V2）

### 1.2 卡片内容格式：模板 vs 内联 JSON

有两种方式传递卡片内容：

**方式一：内联 JSON（推荐用于动态内容）**

```json
{
  "receive_id": "oc_xxx",
  "msg_type": "interactive",
  "content": "{\"schema\":\"2.0\",\"config\":{\"update_multi\":true},\"header\":{\"title\":{\"content\":\"标题\",\"tag\":\"plain_text\"}},\"body\":{\"elements\":[{\"tag\":\"markdown\",\"content\":\"Markdown 内容\",\"element_id\":\"md_1\"}]}}"
}
```

**方式二：引用卡片模板**

```json
{
  "receive_id": "oc_xxx",
  "msg_type": "interactive",
  "content": "{\"type\":\"template\",\"data\":{\"template_id\":\"ctp_AAxxxxxxxxxx\"}}"
}
```

**方式三：引用 CardKit 卡片实体（用于流式更新）**

```json
{
  "receive_id": "oc_xxx",
  "msg_type": "interactive",
  "content": "{\"type\":\"card\",\"data\":{\"card_id\":\"<card_entity_id>\"}}"
}
```

> 注意：发送卡片实体时 content 必须为 `{"type":"card","data":{"card_id":"..."}}` 格式，仅传 `{"card_id":...}` 会触发解析错误（错误码 200621）。

### 1.3 卡片 JSON v1 vs v2 差异

| 特性 | JSON 1.0 | JSON 2.0 |
|------|----------|----------|
| 声明方式 | 默认（无 schema 字段） | `"schema": "2.0"` 必须显式声明 |
| Markdown 语法 | 子集（无标题/引用/表格/数字角标） | 支持除 `SetextHeading`、`HTMLBlock` 外的 CommonMark 标准语法 |
| 代码块 | 飞书 7.6+ 支持 | 完整支持 |
| 流式更新 | 不支持 | 支持 `streaming_mode` |
| 组件 `element_id` | 无 | 新增，用于组件级操作 |
| 共享卡片 | 支持独享/共享 | 仅支持共享（`update_multi` 必须为 `true`） |
| 客户端兼容性 | 全版本 | 飞书 7.20+ |
| 最大组件数 | 无明确限制 | 200 个元素/组件 |
| 差异化跳转语法 | `[差异化跳转]($urlVal)` | 已废弃，改用 `<a>` 标签 |

### 1.4 Markdown 支持详情

卡片中的 Markdown 组件（`tag: "markdown"`）支持：

- **标准语法**：标题（`#` ~ `######`）、粗体（`**bold**`）、斜体（`*italic*`）、删除线（`~~text~~`）、有序/无序列表、链接、图片、分割线、引用、表格
- **代码块**：三个反引号包裹，支持语言高亮（Python、Java、Go、JavaScript、TypeScript、C、C++、Rust、JSON、YAML、SQL、Shell/Bash 等）
- **飞书扩展 HTML 标签**：`<at>`（@人）、`<text_tag>`（标签）、`<local_datetime>`、`<person>`、`<a>`
- **表情**：`:emoji_type:` 语法

**不支持的语法**：
- `HTMLBlock`（通用 HTML div 等）
- `SetextHeading`（Setext 风格标题）

**换行行为差异**：
- 单个 Enter = 软换行（可能被忽略）
- 双 Enter = 硬换行（始终显示新行）

### 1.5 适合展示 LLM 输出的卡片元素

| 组件 | tag | 用途 |
|------|-----|------|
| 富文本（Markdown） | `markdown` | **最推荐**。渲染 LLM 的 Markdown 输出，支持标题、列表、代码块、表格 |
| 普通文本 | `plain_text` | 纯文本展示 |
| 文本块（div） | `div` + `text.tag: "lark_md"` | JSON 1.0 中的 Markdown 文本展示方式 |
| 分栏 | `column_set` | 布局控制 |

---

## 2. 卡片流式更新（Card Streaming）

### 2.1 两种方案对比

| 方案 | API | 编辑次数限制 | 适用场景 |
|------|-----|-------------|----------|
| 消息编辑 `PUT im/v1/messages/:id` | 编辑文本/富文本消息 | **最多 20 次** | 少量更新、非流式 |
| 卡片 PATCH `PATCH im/v1/messages/:id` | 更新卡片全量内容 | 无明确次数限制，但单条消息 **5 QPS** | 中频更新 |
| **CardKit 流式 API**（推荐） | 创建卡片实体 + 流式更新文本 | **无明确次数限制**，streaming_mode 下不触发频率限制 | **高频流式输出** |

### 2.2 CardKit 流式更新流程

```
用户发消息 → Bot 创建卡片实体 → 发送卡片消息 → 循环流式更新文本 → 关闭流式模式
```

**步骤一：创建卡片实体**

`POST https://open.feishu.cn/open-apis/cardkit/v1/cards`

```json
{
  "type": "card_json",
  "data": "{\"schema\":\"2.0\",\"config\":{\"streaming_mode\":true,\"update_multi\":true,\"summary\":{\"content\":\"[生成中]\"},\"streaming_config\":{\"print_frequency_ms\":{\"default\":70},\"print_step\":{\"default\":1},\"print_strategy\":\"fast\"}},\"body\":{\"elements\":[{\"tag\":\"markdown\",\"content\":\"\",\"element_id\":\"md_main\"}]}}"
}
```

- 频率限制：1000 次/分钟、50 次/秒
- 权限：`cardkit:card:write`
- 返回：`card_id`
- 有效期：创建后 14 天

**步骤二：发送卡片消息**

`POST https://open.feishu.cn/open-apis/im/v1/messages`

```json
{
  "receive_id": "oc_xxx",
  "msg_type": "interactive",
  "content": "{\"type\":\"card\",\"data\":{\"card_id\":\"<card_id>\"}}"
}
```

**步骤三：流式更新文本**

`PUT https://open.feishu.cn/open-apis/cardkit/v1/cards/:card_id/elements/:element_id/content`

```json
{
  "content": "已累积的全量文本...",
  "sequence": 1
}
```

关键要点：
- `content` 必须是**全量文本**（不是增量 delta）
- `sequence` 必须**严格递增**
- 若旧文本是新文本的前缀，新增部分以打字机效果上屏
- 若前缀不同，全量直接上屏（无打字机效果）
- 频率限制：streaming_mode 开启时，**不触发接口 QPS 限制**；单卡片操作频率上限 10 次/秒
- 仅支持 `plain_text` 和 `markdown` 组件
- 卡片体积限制：**30 KB**

**步骤四：关闭流式模式**

`PATCH https://open.feishu.cn/open-apis/cardkit/v1/cards/:card_id/settings`

```json
{
  "settings": {
    "streaming_mode": false
  },
  "sequence": <最终sequence+1>
}
```

不关闭会导致会话预览持续显示「[生成中...]」。

### 2.3 `streaming_config` 配置

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `print_frequency_ms` | object | 70ms | 两次上屏的间隔（支持按平台配置 default/android/ios/pc） |
| `print_step` | object | 1 | 每次上屏的字符步长 |
| `print_strategy` | string | `"fast"` | `fast`：历史文本未完则立即全部上屏；`delay`：等历史文本输出完再继续 |

> 注意：`streaming_config` 需飞书 7.23+ 版本支持。

### 2.4 旧方案：PATCH 更新消息卡片

`PATCH https://open.feishu.cn/open-apis/im/v1/messages/:message_id`

```json
{
  "content": "{\"schema\":\"2.0\",...全量卡片JSON...}"
}
```

- 频率限制：单条消息 **5 QPS**（1000 次/分钟、50 次/秒全局）
- 无明确编辑次数限制（不同于消息编辑的 20 次上限）
- 仅支持更新 `interactive` 类型消息
- 14 天内可更新
- 卡片体积上限 **30 KB**

---

## 3. 消息表情回复（Message Reaction）

### 3.1 API 端点

`POST https://open.feishu.cn/open-apis/im/v1/messages/:message_id/reactions`

**频率限制**：1000 次/分钟、50 次/秒

**权限要求**（任一即可）：
- `im:message`（获取与发送单聊、群组消息）
- `im:message.reactions:write_only`（发送、删除消息表情回复）

**请求体**：
```json
{
  "reaction_type": {
    "emoji_type": "SMILE"
  }
}
```

**响应**：
```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "reaction_id": "ZCaCIjUBVVWSrm5L-3ZTw****",
    "operator": {
      "operator_id": "ou_ff0b7ba35fb****",
      "operator_type": "user"
    },
    "action_time": "1663054162546",
    "reaction_type": {
      "emoji_type": "SMILE"
    }
  }
}
```

**前提条件**：机器人或用户必须在消息所在的会话内。

### 3.2 常用 emoji_type 列表

| emoji_type | 含义 | emoji_type | 含义 | emoji_type | 含义 |
|-----------|------|-----------|------|-----------|------|
| `OK` | 好的 | `THUMBSUP` | 点赞 | `THANKS` | 感谢 |
| `MUSCLE` | 加油 | `DONE` | 完成 | `SMILE` | 微笑 |
| `HEART` | 爱心 | `FIRE` | 火 | `APPLAUSE` | 鼓掌 |
| `JIAYI` | +1 | `LGTM` | Looks Good | `OnIt` | 马上处理 |
| `THINKING` | 思考 | `CheckMark` | 对勾 | `CrossMark` | 叉号 |
| `Coffee` | 咖啡 | `Trophy` | 奖杯 | `PARTY` | 庆祝 |
| `YES` | 是 | `No` | 否 | `CLAP` | 拍手 |

完整列表参见：https://open.feishu.cn/document/server-docs/im-v1/message-reaction/emojis-introduce

### 3.3 其他表情回复 API

| 操作 | 方法 | 端点 |
|------|------|------|
| 添加 | POST | `/im/v1/messages/:message_id/reactions` |
| 删除 | DELETE | `/im/v1/messages/:message_id/reactions/:reaction_id` |
| 列表 | GET | `/im/v1/messages/:message_id/reactions` |
| 批量查询 | POST | `/im/v1/messages/batch_query_reactions` |

---

## 4. LLM 流式输出的实际考量

### 4.1 未完成 Markdown 的处理

卡片 Markdown 组件渲染**全量传入**的文本。当代码块处于"中间态"时（如只有开头的 ` ``` ` 没有结尾），飞书客户端通常可以容忍——渲染为未闭合的代码区域。但需注意：

- 代码块前后的多余空格可能导致渲染失败
- 未闭合的 Markdown 语法（如 `**粗体` 没有结束）可能导致后续文本样式异常
- **建议**：在服务端做简单的 Markdown 修复（如自动闭合未完成的代码块）

### 4.2 用户阅读时更新卡片

PATCH 更新或 CardKit 流式更新时：
- 卡片内容会**实时刷新**，用户正在阅读的卡片会直接更新
- 在 `streaming_mode` 下，新内容以**打字机效果**追加，视觉上较自然
- 非 streaming_mode 的 PATCH 更新会导致**整体内容闪烁**
- 流式模式期间用户交互（如点击按钮）的回调会被延迟处理

### 4.3 更新频率分析

| 方案 | 可行频率 | 说明 |
|------|---------|------|
| CardKit 流式 API | **10 次/秒**（streaming_mode 下不计入全局 QPS） | 最佳选择 |
| 卡片 PATCH（im/v1） | **5 QPS** 单条消息 | 够用但不如 CardKit |
| 消息编辑（PUT） | 50 次/秒但只能编辑 20 次 | **不可行**，流式输出会超出次数限制 |

**建议频率**：服务端节流 **每 500ms 更新一次**（2 QPS），在 CardKit 和 PATCH 方案下都安全。流式结束后做一次**兜底更新**确保最终内容同步。

### 4.4 最大内容大小

- 卡片 JSON 总体积：**30 KB**
- 单张卡片最多 **200 个元素/组件**
- 卡片实体有效期：**14 天**
- CardKit 创建实体时 `data` 字段长度上限：1 ~ 3,000,000 字符

对于 LLM 输出，30 KB 的 Markdown 文本约为 **15,000 个中文字符** 或 **30,000 个英文字符**，一般足够。超长输出需分多张卡片或截断。

### 4.5 替代方案

| 方案 | 优点 | 缺点 |
|------|------|------|
| CardKit 流式卡片 | 打字机效果、无编辑次数限制、Markdown 支持好 | 需要三步（创建实体→发送→流式更新） |
| PATCH 卡片消息 | 简单直接，一步更新 | 5 QPS 限制，全量替换会闪烁 |
| 编辑文本消息（PUT） | 最简单 | **20 次编辑上限**，不适合流式 |
| 多条独立消息 | 无更新限制 | 消息列表被刷屏，体验差 |

---

## 5. lark-oapi Python SDK 支持情况

本项目使用 `lark-oapi>=1.7.0`（`pyproject.toml` 中声明）。

### 5.1 发送消息卡片

SDK 已支持。使用与发送文本消息相同的 `CreateMessageRequest`，将 `msg_type` 设为 `"interactive"`。

```python
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
)
import json

card_json = {
    "schema": "2.0",
    "config": {"update_multi": True},
    "header": {"title": {"content": "AI 回复", "tag": "plain_text"}},
    "body": {
        "elements": [
            {"tag": "markdown", "content": "回复内容...", "element_id": "md_main"}
        ]
    },
}
body = (
    CreateMessageRequestBody.builder()
    .receive_id(chat_id)
    .msg_type("interactive")
    .content(json.dumps(card_json, ensure_ascii=False))
    .build()
)
request = (
    CreateMessageRequest.builder()
    .receive_id_type("chat_id")
    .request_body(body)
    .build()
)
response = await client.im.v1.message.acreate(request)
```

### 5.2 PATCH 更新消息卡片

SDK 提供 `PatchMessageRequest` / `PatchMessageRequestBody`。

```python
from lark_oapi.api.im.v1 import (
    PatchMessageRequest,
    PatchMessageRequestBody,
)

body = (
    PatchMessageRequestBody.builder()
    .content(json.dumps(updated_card_json, ensure_ascii=False))
    .build()
)
request = (
    PatchMessageRequest.builder()
    .message_id(message_id)
    .request_body(body)
    .build()
)
response = await client.im.v1.message.apatch(request)
```

### 5.3 编辑文本消息（PUT）

```python
from lark_oapi.api.im.v1 import (
    UpdateMessageRequest,
    UpdateMessageRequestBody,
)

body = (
    UpdateMessageRequestBody.builder()
    .msg_type("text")
    .content(json.dumps({"text": "新内容"}, ensure_ascii=False))
    .build()
)
request = (
    UpdateMessageRequest.builder()
    .message_id(message_id)
    .request_body(body)
    .build()
)
response = await client.im.v1.message.aupdate(request)
```

### 5.4 添加消息表情回复

```python
from lark_oapi.api.im.v1 import (
    CreateMessageReactionRequest,
    CreateMessageReactionRequestBody,
    Emoji,
)

emoji = Emoji.builder().emoji_type("THUMBSUP").build()
body = (
    CreateMessageReactionRequestBody.builder()
    .reaction_type(emoji)
    .build()
)
request = (
    CreateMessageReactionRequest.builder()
    .message_id(message_id)
    .request_body(body)
    .build()
)
response = await client.im.v1.message_reaction.acreate(request)
```

### 5.5 CardKit 流式更新

SDK 提供完整的 `cardkit.v1` 模块：

```python
from lark_oapi.api.cardkit.v1 import (
    CreateCardRequest,
    CreateCardRequestBody,
    ContentCardElementRequest,
    ContentCardElementRequestBody,
    SettingsCardRequest,
    SettingsCardRequestBody,
    Settings,
)
```

**创建卡片实体**：

```python
body = (
    CreateCardRequestBody.builder()
    .type("card_json")
    .data(json.dumps(card_json_with_streaming, ensure_ascii=False))
    .build()
)
request = CreateCardRequest.builder().request_body(body).build()
response = await client.cardkit.v1.card.acreate(request)
card_id = response.data.card_id
```

**流式更新文本**：

```python
body = (
    ContentCardElementRequestBody.builder()
    .content(accumulated_text)
    .sequence(seq_number)
    .build()
)
request = (
    ContentCardElementRequest.builder()
    .card_id(card_id)
    .element_id("md_main")
    .request_body(body)
    .build()
)
response = await client.cardkit.v1.card_element.acontent(request)
```

**关闭流式模式**：

```python
settings = Settings.builder().streaming_mode(False).build()
body = (
    SettingsCardRequestBody.builder()
    .settings(settings)
    .sequence(final_seq)
    .build()
)
request = (
    SettingsCardRequest.builder()
    .card_id(card_id)
    .request_body(body)
    .build()
)
response = await client.cardkit.v1.card.asettings(request)
```

### 5.6 SDK API 方法总览

| 功能 | SDK 路径 | 异步方法 |
|------|---------|---------|
| 发送消息 | `client.im.v1.message` | `.acreate()` |
| 回复消息 | `client.im.v1.message` | `.areply()` |
| PATCH 卡片 | `client.im.v1.message` | `.apatch()` |
| 编辑消息（PUT） | `client.im.v1.message` | `.aupdate()` |
| 添加表情回复 | `client.im.v1.message_reaction` | `.acreate()` |
| 删除表情回复 | `client.im.v1.message_reaction` | `.adelete()` |
| 列出表情回复 | `client.im.v1.message_reaction` | `.alist()` |
| 创建卡片实体 | `client.cardkit.v1.card` | `.acreate()` |
| 全量更新卡片 | `client.cardkit.v1.card` | `.aupdate()` |
| 更新卡片配置 | `client.cardkit.v1.card` | `.asettings()` |
| 流式更新文本 | `client.cardkit.v1.card_element` | `.acontent()` |
| 创建组件 | `client.cardkit.v1.card_element` | `.acreate()` |
| 更新组件 | `client.cardkit.v1.card_element` | `.aupdate()` |
| 删除组件 | `client.cardkit.v1.card_element` | `.adelete()` |

---

## 6. 限制与建议

### 6.1 关键限制汇总

| 限制项 | 值 |
|--------|-----|
| 卡片 JSON 体积上限 | 30 KB |
| 卡片最大元素数（JSON 2.0） | 200 个 |
| 卡片实体有效期 | 14 天 |
| 消息编辑次数上限（PUT） | 20 次 |
| 卡片 PATCH 单消息频率 | 5 QPS |
| CardKit 单卡片操作频率 | 10 次/秒（streaming_mode 下不计入全局 QPS） |
| 全局 API 频率 | 1000 次/分钟、50 次/秒 |
| JSON 2.0 客户端最低版本 | 飞书 7.20 |
| `streaming_config` 最低版本 | 飞书 7.23 |

### 6.2 LLM 流式输出到卡片的最佳实践建议

1. **使用 CardKit 流式 API**，而非消息编辑或卡片 PATCH
2. **服务端节流**：建议每 300-500ms 更新一次，流式结束后执行兜底更新
3. **全量文本传递**：每次调用 `content` 接口传递累积的全量文本，`sequence` 严格递增
4. **Markdown 修复**：在传递给飞书之前，自动闭合未完成的代码块（在末尾追加 ` ``` `）
5. **流式结束后关闭 streaming_mode**：否则会话预览持续显示"生成中"
6. **30 KB 体积注意**：对于超长 LLM 输出，需要截断或分页
7. **错误处理**：
   - `200850`（streaming timeout）→ 重新开启 streaming_mode
   - `200860`（content exceeds limit）→ 截断内容
   - `300309`（streaming closed）→ 重新开启 streaming_mode
8. **卡片 JSON 结构**：使用 `schema: "2.0"` + `markdown` 组件 + `element_id` 标记

### 6.3 项目当前状态

本项目（`lark_agent`）当前仅实现了文本消息的发送和回复（`sender.py` 中的 `send_text`），尚未实现：
- 卡片消息发送
- 消息更新/PATCH
- CardKit 流式更新
- 表情回复

`lark-oapi>=1.7.0` 版本已包含所有所需的 SDK 类（`im.v1` 和 `cardkit.v1`），无需额外依赖。

### 6.4 参考文档链接

| 文档 | URL |
|------|-----|
| 发送消息 | https://open.feishu.cn/document/server-docs/im-v1/message/create |
| 更新消息卡片（PATCH） | https://open.feishu.cn/document/server-docs/im-v1/message-card/patch |
| 编辑消息（PUT） | https://open.feishu.cn/document/server-docs/im-v1/message/update |
| CardKit 流式更新概览 | https://open.feishu.cn/document/cardkit-v1/streaming-updates-openapi-overview |
| CardKit 创建卡片实体 | https://open.feishu.cn/document/cardkit-v1/card/create |
| CardKit 流式更新文本 | https://open.feishu.cn/document/cardkit-v1/card-element/content |
| 消息表情回复 | https://open.feishu.cn/document/server-docs/im-v1/message-reaction/create |
| 表情文案说明 | https://open.feishu.cn/document/server-docs/im-v1/message-reaction/emojis-introduce |
| 卡片 JSON 2.0 结构 | https://open.feishu.cn/document/feishu-cards/card-json-v2-structure |
| Markdown 组件（2.0） | https://open.feishu.cn/document/feishu-cards/card-json-v2-components/content-components/rich-text |
| Markdown 组件（1.0） | https://open.feishu.cn/document/feishu-cards/card-components/content-components/rich-text |