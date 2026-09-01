---
name: bilibili_publish_video
type: atomic
runtime: python
version: "1.1.0"
description: 把本地视频投到 B 站创作中心：上传成片、传封面、填标题/创作声明/话题/标签/简介/粉丝动态，默认存草稿，publish=true 才立即投稿
use_cases:
  - 成片做完后一次性投稿，不用人工点二十几处表单
  - 只填表存草稿，人工过一眼再自己点投稿
  - 浏览器桥中途断线后接回未提交的稿件，不重传几十上百兆的片子
  - 换标题/标签重投同一支片子
output_targets:
  - stdout
uses_frago_cli: true
# 本模块用了谁的哪个口。它谁都不依赖，也不读任何人的文件。
imports: {}
tags:
  - bilibili
  - 投稿
  - 视频发布
  - browser
  - extension后端
  - 文件上传
inputs:
  mode:
    type: string
    required: false
    description: 只有一件事可做，就是 publish（默认）。不导出、也不给页面按——它会以主人的身份往站外发东西
  video_path:
    type: string
    required: false
    description: 成片绝对路径（mp4/mov/mkv 等 B 站允许的格式）。只有 resume_unsubmitted=true 时可以不给
  title:
    type: string
    required: true
    description: 稿件标题，≤80 字。核心关键词前置，带具体数字
  cover_path:
    type: string
    required: false
    description: 封面图绝对路径（png/jpg）
  cover_fit:
    type: string
    required: false
    default: pad
    description: pad=非 4:3 自动补边成 4:3 并把正文压进中间 16:9 带；as_is=原图直传（图已经按 4:3 安全区排过版时用，避免再缩一圈）
  description:
    type: string
    required: false
    description: 简介，≤2000 字。里面写 00:00 形式的时间轴，B 站会渲染成可点击跳转
  tags:
    type: list
    required: false
    description: 标签列表。注意话题会占一个标签位，话题 + 标签合计上限 10
  drop_unlisted_tags:
    type: boolean
    required: false
    default: true
    description: 把不在 tags/topic 里的标签一律摘掉。B 站按标题自动塞的泛标签每次都不一样，只能反着删
  drop_tags:
    type: list
    required: false
    description: 额外要摘掉的标签名。drop_unlisted_tags=false 时才需要自己列
  topic:
    type: string
    required: false
    description: 参与话题名，必须与页面上「参与话题」区或话题搜索里的名字完全一致
  declaration:
    type: string
    required: false
    default: 内容无需标注
    description: 创作声明。可选 内容无需标注 / 含AI生成内容 / 含虚构演绎内容 / 内容含营销信息 / 个人观点，仅供参考 / 内容为转载
  dynamic_text:
    type: string
    required: false
    description: 粉丝动态文案，≤233 字。发布时同步发一条动态
  resume_unsubmitted:
    type: boolean
    required: false
    default: false
    description: true=点投稿页那条「本地浏览器存在N个未提交的视频」的「继续编辑」接着填；false=点「不用了」，从干净的表单开始
  publish:
    type: boolean
    required: false
    default: false
    description: true=点「立即投稿」；false=点「存草稿」，人工复核后自己投
  group:
    type: string
    required: false
    default: bili
    description: frago browser 标签组名
  port:
    type: number
    required: false
    default: 8777
    description: 本地取文件用的临时 HTTP 端口
outputs:
  success:
    type: boolean
    description: 是否走完全程
  submitted:
    type: boolean
    description: 是否点了立即投稿（false 表示只存了草稿）
  form:
    type: object
    description: 提交前抓下来的表单实况（标题/分区/声明/标签/简介字数/封面/分P），用于核对
  steps:
    type: list
    description: 每一步做了什么，失败时也带上，用来定位断在哪
---

# bilibili_publish_video

B 站创作中心的投稿表单，人工点一遍要动二十几个地方。这个配方把整条路走完，
默认停在「存草稿」，要它真投出去得显式传 `publish: true`。

## 为什么要起一个本地 HTTP server

extension 后端驱动的是浏览器自己的真实 profile（登录态在这儿），那个实例没开调试端口，
`DOM.setFileInputFiles` 用不了。页面 JS 又读不到 `file://`。

所以走这条路：本地起一个只活几十秒的 HTTP server 托住文件 → 页内 `fetch` 拿回 blob →
`new File()` → `DataTransfer` → `input.files` → 派发 `change`。

两个头必须带对：`Access-Control-Allow-Origin: *`，以及 `Access-Control-Allow-Private-Network: true`
（https 公网页面请求 127.0.0.1 会先发一个 Private Network Access 预检）。
回环地址不算 mixed content，https 页面 fetch http://127.0.0.1 不会被拦。

## 会让你白花一小时的几个坑

**页面里不要写 `await sleep` 循环。** 后台 tab 的定时器被 Chrome 节流，
第一次手工跑的时候，一个 in-page 循环加 9 个标签花了将近 4 分钟。
所有节奏交给 Python 侧，一次 exec-js 只干一件事。

**这一页的真数据源是 Vue 组件，不是 DOM。** 提交时 B 站读的是 `video-basic` 组件里的字段。
认这个组件只能用 `$options._componentTag`——`$options.name` 在这一页是空的。

**简介写进编辑器不等于写进稿件。** 简介和粉丝动态都是 quill，
`__quill.setText()` 只改编辑器；2026-08-31 实测改完组件里的 `desc` 仍是 0 字，
存下去简介是空白，而页面上的字数计数器却是对的，肉眼看不出来。
配方现在写完一定回读组件，没同步就直接补 `desc` / `desc_v2`，对不上直接报错。

**自动塞的泛标签每次都不一样。** 见过「分享/原创」，也见过「学习」「编程/学习/教育」。
固定黑名单挡不住，所以默认 `drop_unlisted_tags: true`——不在 `tags`/`topic` 里的一律摘掉，
而且加完标签之后要再扫一遍（加标签本身会触发 B 站再塞一轮推荐词）。

**标签的关闭按钮不一定带 `.close` 类**，2026-08-31 那一版就没有，得退回 `chip.querySelector('svg')`。
点完 Vue 要一两秒才重渲染，当场回读拿到的还是旧值。

**话题占标签位。** 选中「参与话题」后，话题会作为第一个标签 chip 插进标签区，
和普通标签共用上限 10。先想清楚这一格是给话题还是给标签。

**首页推荐封面是 4:3，不是 16:9。** 封面制作页自己写着「两个比例的封面都会被展示给观众，
请确认 4:3、16:9 比例下的封面效果」。4:3 安全区是 1920 宽画布中间的 1440（x 240~1680），
直接传满宽排版的 1920×1080，靠边的字会缺角。
`cover_fit: pad`（默认）把非 4:3 的图补边成 4:3、正文压进中间 16:9 带；
图本来就按 4:3 安全区排过版的，传 `cover_fit: as_is` 跳过，别让它再缩一圈。

**封面弹窗里有两颗按钮。** 先点「添加封面」开弹窗，弹窗里还要点「上传封面」才会新建 file input，
注入完再点「完成」。少点中间那颗，file input 根本不存在。

## 浏览器桥断了怎么办

`frago browser groups` 变成 `{}`、标签组连同页面一起丢，这事会发生。
片子这时其实已经在 B 站服务端了，重新打开投稿页会看到
「本地浏览器存在1个未提交的视频」，点「继续编辑」就能接回来，**不用重传**。

    frago recipe run bilibili_publish_video --params '{"resume_unsubmitted": true, "title": "...", ...}'

接回来的稿子只保住视频和创作声明，标题/简介/标签/封面会被打回默认，配方会照常重填一遍。

反过来，**正常起跑时那条横幅必须点掉**（默认行为），否则这一次会接着上一轮的残稿填，
最后传上去的是两轮混在一起的东西。

## 前置

- 浏览器已起且已登录 B 站：`frago browser status`
- 走默认 extension 后端，不要传 `-b cdp`（那是另一个实例，没有登录态）

## 用法

    frago recipe run bilibili_publish_video --params '{
      "video_path": "/abs/path/成片.mp4",
      "cover_path": "/abs/path/cover.png",
      "cover_fit": "as_is",
      "title": "核心关键词前置的标题｜带个具体数字",
      "description": "正文……\n\n00:00 开场\n00:20 第二段",
      "tags": ["AI编程", "ClaudeCode", "AI Agent"],
      "topic": "B站AI创造公开赛",
      "declaration": "含AI生成内容",
      "dynamic_text": "同步发一条动态，结尾抛个问题",
      "publish": false
    }'

## 预期输出

    {
      "success": true,
      "submitted": false,
      "form": {
        "title": "...", "tid": 231, "declaration": "含AI生成内容",
        "tags": ["AI编程", "..."], "desc_len": 763, "dynamic_len": 45,
        "cover": "set",
        "parts": [{"cid": 41445359938, "size": 90979657, "status": 3, "progress": 100}]
      },
      "steps": ["成片已注入 90979657 字节", "上传完成: ...", "封面已上传", "..."],
      "note": "只存了草稿，去创作中心复核后自己点投稿"
    }

## 关于 publish=false

`publish: false` 停在「存草稿」，方便人工过一眼。

草稿箱到底丢不丢东西，说法要分开讲：页面上写着**暂不保存 话题、商业声明、联合投稿、
卡片配置、字幕、定时发布**。但 2026-08-31 实测了一次（draftId 3818453）：存完重新载入，
**标题、简介 763 字、7 个标签、封面、创作声明、分区、分P（cid 41445359938）全都回来了，
视频没有重传**。所以「重进要重传视频」这条至少在这次不成立。
没验到的是话题——那一支本来就没挂话题。

结论：**要挂话题就别从草稿箱重进**，在原页面一次做完；不挂话题的话，存草稿再回来是安全的。

实测一次完整跑完（48MB 成片 + 封面 + 10 个标签 + 简介 + 动态）约 108 秒。

## 填什么内容更有用

不是配方的活，但每次都要想一遍，记在这儿：

- 标题：核心关键词前置 + 具体数字。B 站吃「实测」「干货」「保姆级」，
  「震惊」「不看后悔」这类会被算法降权
- 标签：1 个核心词 + 3 个长尾词 + 2 个场景词，聚在一个题上，别撒
- 简介：开头三五个关键词自然带到，末尾放时间轴（B 站渲染成可点击跳转），
  最后抛一个具体问题 —— 提问比「记得三连」有效
- 互动管理：别开「精选评论」，那会压评论量。B 站权重里分享 > 投币 > 收藏 > 评论 > 弹幕 > 点赞 > 播放
- 发布时间：科技/知识类的峰值在晚上 20:00–23:00

## 更新历史

- **1.1.0**（2026-09-01）搬进 frago-recipe-community，同时做两件事。

  **改造到新架构**：能力建到 `Recipe` 基类上，加 `frago-recipe/1` 描述头，
  一个 `mode_publish`，不标 `@export` 也不标 `@action`（它会以主人的身份往站外发东西）；
  暂存目录从 `/tmp` 挪进 `self.store`，不再自己拼路径；补 `uses_frago_cli`
  （脚本要 shell 调 `frago browser`，不写 validate 直接拒）；pillow 从
  `uv run --with` 子进程改成 PEP 723 声明；结果不再自己 print，走基类的消息通道。

  **实跑一次 19 分钟的片子后补的修正**：简介写完回读 Vue 组件、防止只进编辑器不进稿件；
  标签改成「不在名单里的一律摘」；标签关闭按钮不认死 `.close`；封面弹窗补上中间那颗
  「上传封面」；等上传只认组件的 `status/progress` 不认页面文案；提交按钮先按
  `submit-draft` / `submit-add` 收窄再核文案；新增 `resume_unsubmitted` 接回断线残稿、
  `cover_fit: as_is` 跳过补边。
- **1.0.0**（2026-08-15）初版，只活在本地，没进过任何仓库。
