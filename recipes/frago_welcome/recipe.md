---
name: frago_welcome
type: atomic
runtime: python
version: "1.0.0"
created_at: "2026-09-05T00:00:00+08:00"
updated_at: "2026-09-05T00:00:00+08:00"
description: "装完 frago 之后的第一张页面：六屏引导，中间一处真的写操作，让这台机器自己证明 agent 记住了事"
use_cases:
  - "场景 1: 安装 skill 装完 frago，agent 跑一次这个配方，把欢迎页交到用户面前"
  - "场景 2: 用户想再看一遍这台机器上现在有什么（配方 / 知识域 / 主题 / 路由规则）"
  - "场景 3: 给别人演示 frago 的知识层——写一条规矩，换个终端问，它答得上来"
output_targets:
  - stdout
# 一个 mode 对外开到什么程度写在 recipe.py 的方法上（@export / @action / 不标）。
# 本模块不读任何别的模块的口。
imports: {}
# 不 shell 出去调 frago：本模块调 frago 命令一律走总线（self.ask_frago），
# 隔离下自起的 frago 看不见平台的书目，而那种失败不报错——命令照样 exit 0，
# 只答「什么都没有」，页面上的数字会静默变成错的。
tags:
  - interactive
  - onboarding
  - ui
  - frago
inputs:
  mode:
    type: string
    required: false
    description: "welcome（默认）备好页面并打开；stats 只读地报本机实况；remember 把页面上写的规矩存进知识域；ask 把页面上那句话真的交给本机的 agent"
  rule:
    type: string
    required: false
    description: "mode=remember 时的那条规矩，来自页面上的输入框。4~600 字"
  default_lang:
    type: string
    required: false
    description: "没在语言胶囊上点过的人先看哪门，zh 或 en，默认 en"
  topic:
    type: string
    required: false
    description: "mode=ask 时问哪一条：browser / memory / recipe。问题文本在 recipe.py 里，页面只点名"
  lang:
    type: string
    required: false
    description: "mode=ask 时用哪门语言问，zh 或 en，默认 zh"
  open:
    type: boolean
    required: false
    description: "跑完要不要把页面推到用户的默认浏览器，默认 true。只想刷新状态时给 false，免得每重跑一次就多一个收不回来的标签页"
  slot:
    type: string
    required: false
    description: "发布到哪个槽位，默认 default。改它等于改页面地址后面的 ?key=，一般不用动"
outputs:
  url:
    type: string
    description: "页面地址，形如 http://localhost:8093/app/frago_welcome"
  stats:
    type: object
    description: "本机实况四项：recipes / domains / topics / rules，读不到的那项是 null"
  domain:
    type: string
    description: "mode=remember 时那条规矩落在哪个知识域"
  doc:
    type: string
    description: "mode=remember 时写出来的文档名，形如 rule-20260905-143012"
  question:
    type: object
    description: "mode=remember 时给回的一句话，中英各一份，人拿去终端问 agent"
---

# frago_welcome

## 它解决什么问题

装完一个东西，人最想知道的是「所以现在有什么不同」。文档回答不了这个问题——文档讲的是别人的机器。所以这张页面上每个数字都是运行时从**这台**机器上点的，中间还有一处真的写操作：人写一条自己的规矩，按一下按钮，那条规矩就进了知识域；然后页面请他换个地方——回到终端——去问 agent 同一件事。

agent 那边没有任何人告诉它这件事。它是被 frago 的轻量 ai 按知识域索引路由过去、自己查到的。

**同一条信息，一边写进去，另一边不经过对话就取得到。** 这是这张页面唯一值得看的一分钟。

## 六屏是什么

| 屏 | 说什么 |
|---|---|
| 1 | 你的 agent 刚拿到一台机器 |
| 2 | 三件一直很别扭的事，现在换成了什么 |
| 3 | 本机实况：配方 / 知识域 / book 主题 / 路由规则，四个真数字 |
| 4 | 现场演示：写一条规矩 → 存进知识域 → 拿着问句回终端问 agent |
| 5 | 刚才那一下是怎么成的：写 → 认 → 取 |
| 6 | 接下来说三句话就够了 |

第 3 屏那两个可能是 0 的格子（配方、知识域）不藏起来。刚装完的机器上它们本来就是 0，而第 4 屏会把「知识域」那格填成 1——页面上的数字因为人做了一件真事而变了，这比任何一句文案都有说服力。

## 使用方式

```bash
# 安装 skill 装完 frago 之后，agent 跑这一条就够了（页面会自己打开）
frago recipe run frago_welcome

# 先给英文
frago recipe run frago_welcome --params '{"default_lang": "en"}'

# 只想知道这台机器上有什么，不开页面
frago recipe run frago_welcome --params '{"mode": "stats"}'
```

页面上那个「让它记住」按钮走的是 `mode=remember`，由页面发起，人不用手敲。

## 前置条件

1. `frago server` 在跑（页面由它发出，`self.ask_frago` 也走它）。
2. 就这一条。不需要 `frago browser start`——这张页面开在用户自己的默认浏览器里，跟受控浏览器没有关系。

## 预期输出

```json
{
  "success": true,
  "url": "http://localhost:8093/app/frago_welcome",
  "open_url": "http://localhost:8093/app/frago_welcome",
  "slot": "default",
  "stats": {"recipes": 58, "domains": 46, "topics": 43, "rules": 115},
  "warnings": []
}
```

`stats` 里读不到的那一项是 `null`，不是 `0`。0 在这张页面上有含义（还没装配方），把读不到写成 0 会让人以为东西丢了。

## 模块契约

| 项 | 是什么 |
|---|---|
| 契约描述头 | `# frago-recipe/1`，文件头第二行 |
| 基类 | `class FragoWelcome(Recipe)`，文件底部 `FragoWelcome.main()` |
| modes | `welcome`（默认）、`stats`、`remember` |
| exports | `stats` —— 只读地报四个数字，页面写完知识后用它刷新 |
| page_actions | `remember` —— 页面能按，写的是按按钮的人自己刚敲的那句话 |
| imports | 空。不问任何别的模块要东西 |
| 落点 | 不写任何文件，`self.store` / `self.data_dir` 一次都没用上 |
| 页面 | 发布走总线；状态里没有一条路径 |

## 它不做什么

- **不装配方。** 第 6 屏告诉人去哪儿取，命令由人（或他的 agent）自己敲。一张欢迎页不该背着人往机器上装东西。
- **不写路由规则。** 知识域是「记住一件事」，路由规则是「改它的行为」，后者该由人明确要求，不该是欢迎页顺手做的。
- **不碰 `purpose` 已经存在的知识域。** `my-rules` 已经在了就只往里存文档，不重设用途——那可能是用户自己改过的。
- **不联网。** 整张页面零外部资源，没有 CDN、没有网络字体、没有第三方脚本。

## 注意事项
 
- **改了 `recipe.py` 里的文案要重跑。** 状态是快照，不重跑页面上还是旧的那份。
- **改了 `assets/index.html` 不用重跑。** 骨架是静态文件，服务端直接读目录，存盘即生效。
- **这张页面默认只有主人能开。** 它就在本机 `localhost:8093` 上，没有开放给任何人的理由；真要给别人看，`frago recipe expose` 是另一件事，得人明确按下。
- **`my-rules` 这个域名和它的 purpose 是演示能不能成的关键。** 轻量 ai 手里只有域名和 purpose，看不到文档正文；purpose 写成「什么样的问题该来这里查」才路由得过去。改它之前先想清楚这一层。

## 更新历史

- 1.0.0 (2026-09-05): 初版。六屏，中英双语，文案在 `recipe.py` 里，骨架不含一个字。
