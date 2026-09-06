# frago_welcome 规格

> 这份规格是这个配方的设计记录，`frago recipe create frago_welcome` 也读它。
> **下面几个字段是给机器读的，写什么，模板里就长出什么。**

## 机器读的部分

```yaml
type: atomic
runtime: python

modes:
  welcome:
  stats: export
  remember: action

default_mode: welcome

imports: {}

page: true
```

## 人读的部分

### 它解决什么问题

刚用安装 skill 装完 frago 的人，此刻知道「装完了」，但不知道「所以现在有什么不同」。文档回答不了这个问题——文档讲的是别人的机器。这张页面由 agent 在安装的最后一步跑一次打开，用六屏讲清楚差别，并在中间安排一处**真的写操作**：人写一条自己的规矩，按一下按钮，那条规矩进知识域；然后页面请他回到终端问 agent 同一件事，agent 没有被任何人告知，却答得上来。

**同一条信息，一边写进去，另一边不经过对话就取得到。** 这是整张页面唯一值得看的一分钟，也是这个配方存在的全部理由。

### 每个 mode 做什么

| mode | 输入 | 输出 | 开给谁 |
|---|---|---|---|
| welcome | `default_lang`、`slot`、`open` | `url`、`stats`，`open` 不为 false 时还有 `open_url` | 只有主人。它发布页面状态 |
| stats | — | `stats`：recipes / domains / topics / rules 四个数，读不到的那项是 null | export：页面写完知识后用它刷新数字。只跑 frago 自己的四条 list 命令，不触网、不改状态 |
| remember | `rule` | `domain`、`doc`、`question`（中英各一句）、`recall_command`、刷新后的 `stats` | action：页面上那个按钮。它写东西，写的是按按钮的人自己刚敲进去的那句话 |

### 它不做什么

- **不装配方。** 最后一屏告诉人去哪儿取，命令由人或他的 agent 自己敲。一张欢迎页不该背着人往机器上装东西。
- **不写路由规则。** 知识域是「记住一件事」，路由规则是「改它的行为」。后者该由人明确要求。
- **不重设已存在的知识域用途。** `my-rules` 已经在了就只往里存文档——它的 purpose 可能是用户自己改过的。
- **不联网。** 页面零外部资源；配方本身除了 frago 自己的命令什么都不调。

### 数据

这个配方**不写任何文件**，`self.store` / `self.data_dir` 一次都没用上。它唯一的写操作落在知识域里，而那是走 `self.ask_frago(["def", ...])` 交给平台做的——配方自己不碰 `~/.frago/books`。

页面要的数据来自两处：发布状态里的文案与首次实况（`config.json`），以及导出的 `stats`。状态里**没有一条路径**。

调 frago 命令一律走 `self.ask_frago`（总线），不 shell 出去自己起 frago：隔离下自起的 frago 看不见平台的书目，而那种失败不报错——命令照样 exit 0，只答「什么都没有」，页面上的数字会静默变成错的。

### 出错怎么办

| 情况 | 怎么报 | 数据 |
|---|---|---|
| 平台没交代总线地址 | 基类抛 `BusUnavailable`，**配方不接不兜底** | 不动 |
| 发布页面状态失败 | 致命 | 不动 |
| 规矩太短 / 太长 | 致命，当场说清界限 | 不写 |
| 建知识域失败 | 致命——后面那步存不进去，报成功等于骗人 | 不动 |
| 存知识失败 | 致命 | 不动 |
| 四条实况命令里有一条读不到 | `self.warn`，那一格显示「读不到」 | 不动 |

最后一条是这个配方里唯一不致命的错：一个数字读不到，不该让另外三个和整张页面一起消失。**读不到写成 `null` 不写成 `0`**——0 在这张页面上有含义（还没装配方，是下一步要做的事），两种情况长得一样就没法看了。

### 怎么验

```bash
# 1) 只读口能跑，四个数都是数字或 null
frago recipe run frago_welcome --params '{"mode":"stats"}'
#    依据：stats 是 export，MUST 只读且随时能跑

# 2) 默认 mode 发布状态并给回地址；open=false 时不带 open_url
frago recipe run frago_welcome --params '{"open": false}'
#    依据：「不做什么」里那条——重跑刷新状态不该往人的浏览器里推标签页

# 3) 页面上那个按钮走得通（在页面里点，或直接调）
frago recipe run frago_welcome --params '{"mode":"remember","rule":"我在北京，日期一律写成 2026-09-05"}'
frago my-rules find
#    依据：remember 是 action，写完 my-rules find 必须看得到它

# 4) 规矩太短要被挡住，而不是存一条空的进去
frago recipe run frago_welcome --params '{"mode":"remember","rule":"嗯"}'
#    期望：非零退出，消息说清最少几个字

# 5) 状态里不许有路径
#    依据：基类 publish() 的路径闸。会话工作台那条链接在状态里是空字符串，
#    由页面落回站点根——这是为了过闸，也是因为 origin 本来就该由页面自己知道
```

### 这一版留下的口子

- 演示能不能成，取决于轻量 ai 认不认得那句问话。域名和 `DOMAIN_PURPOSE` 是唯一的着力点（它看得到的只有域名和用途，看不到文档正文）。第四屏那个「没答上来」分支就是为这个准备的，它给的三条都是人自己能跑通的路。
- 配方数为 0 时第三屏是一个 0 加一句「还是空的」。这是实话，而且它把「去社区仓库取配方」这件事变成了页面上看得见的缺口——不是缺陷，是设计。
