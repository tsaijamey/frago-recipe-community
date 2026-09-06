#!/usr/bin/env python3
# frago-recipe/1
# 能力建在基类 Recipe 上，落点、消息、跨模块调用、页面发布都走基类。
# 规范：frago book recipe-creation / frago book interactive-recipe
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""装完 frago 之后的第一张页面：让这台机器自己证明它已经不一样了。

装完一个东西，人最想知道的是「所以现在有什么不同」。文档回答不了这个问题——
文档讲的是别人的机器。所以这张页面上的每个数字都是运行时从**这台**机器上点的：
装了几个配方、几个知识域、book 有几个主题、路由规则有几条。空的那两格不藏起来，
它们正是接下来一分钟要填上的东西。

页面中间有一处真的写操作：人写一条自己的规矩，按一下按钮，那条规矩就进了知识域
`my-rules`。然后页面请他换个地方——回到终端——去问 agent 同一件事。agent 那边没有
任何人告诉它这件事，它是被 frago 的轻量 ai 按知识域索引路由过去、自己查到的。

这是整张页面唯一值得看的一分钟：**同一条信息，一边写进去，另一边不经过对话就取
得到**。frago 的四根支柱（hook / 系列命令 / def / recipe）在这一下里出现了三根，
而人只做了两个动作。

## 文案为什么不写死在 index.html 里

跟 `frago_home` 同一个理由，也是同一套做法：文案是要改的，骨架是不该动的。改一句
话不该有机会碰坏布局。代价是页面拿不到状态时会没有内容，所以骨架里留了一段兜底
（一句标题加一条重跑命令），状态读不到就只显示那一段。

## 这个模块对外的面

`mode_stats` 是唯一导出的口：它只读本机已经有什么，页面用它在写完知识之后把数字
刷新一遍。`mode_remember` 标 `@action` ——页面能按，也确实会写东西，但它写的是按
按钮的人自己刚敲进去的那句话，写到他自己的知识域里。`mode_welcome` 谁都不给：它
发布页面状态，那是主人跑一次的事。
"""

from __future__ import annotations

import json
import re
import time

from frago_recipe import BusUnavailable, Recipe, RecipeFailed, action, export

# ---------------------------------------------------------------------------
# 演示落到哪个知识域
#
# 域名和 purpose 不是随便起的，它们是这场演示能不能成的关键。frago 的轻量 ai 在每
# 条 prompt 上做一次判断，它手里能看到的只有**域名 + purpose**（读 ~/.frago/books/
# registry.json，见 frago-core review.rs 的 domain_index）——文档正文它看不到。所以
# purpose 必须写成「什么样的问题该来这里查」，而不是「这里存了什么」。
#
# 写进 registry.json 会让轻量 ai 的提示前缀缓存立刻失效（那个文件在指纹里），所以
# 新建的域不用等下一次会话，当场就参与路由。
# ---------------------------------------------------------------------------

DOMAIN = "my-rules"

DOMAIN_PURPOSE = (
    "用户本人立下的规矩、偏好与个人事实：他的机器、账号、习惯、口味、做事的方式。"
    "凡是问题里出现「我的」「我用的」「我习惯」「按我说的」，或者要按用户既定规矩"
    "行事时，先查这里再开口。"
)

DOMAIN_SCHEMA = {
    "fields": [
        {"name": "name", "type": "string", "required": True, "description": "文档名"},
        {"name": "summary", "type": "string", "required": False,
         "description": "这条规矩的一句话"},
        {"name": "tags", "type": "list", "required": False, "description": "标签"},
    ]
}

#: 一条规矩最多多长。上限不是为了省地方，是为了让人写一条规矩而不是一篇日记——
#: 一句话的规矩才有机会被轻量 ai 在下一次对话里用上。
RULE_MAX = 600
RULE_MIN = 4

#: 会话工作台就是发出这张页面的那个站点的根。这里留空而不是写 "/"：基类的
#: publish() 把「以 / 开头的字符串」一律当成本机路径拦下来，那道闸故意宽，
#: 而这一条本来也不该由后端说了算——页面自己知道它开在哪个 origin 上，
#: 骨架里把空地址落回站点根即可。
WORKBENCH = ""
COMMUNITY = "https://github.com/tsaijamey/frago-recipe-community"
REPO = "https://github.com/tsaijamey/frago"


# ---------------------------------------------------------------------------
# 文案。两门语言各一份完整的，不做「缺了就回落到英文」。
# ---------------------------------------------------------------------------

ZH = {
    "lang": "zh",
    "langName": "English",
    "brand": "frago",
    "nav": {"skip": "跳到最后"},
    "hero": {
        "kicker": "安装完成",
        # 紧跟在绿字下面那一行。它说的是此刻的状态，不是介绍，所以位置在标题
        # 之上而不是之下。
        "note": "frago 已经在这台机器上跑起来了。",
        # 断行是文案的一部分，不交给浏览器去猜：这一句在「得到了」之后落下来，
        # 两行各自成句。骨架里 h1 用 white-space: pre-line 认这个换行。
        "title": "你的Agent得到了\n世界上第一个真正的AgentOS",
        "cta": "快速了解frago",
        "skip": "我赶时间，直接给命令",
        "hint": "翻页",
    },
    "shift": {
        "kicker": "哪些新鲜玩意儿",
        "title": "安装前后的变化",
        "lead": "你所用的命令行Agent确实很能干，但他只相当于钢铁侠本人，"
                "frago给他穿上了钢铁侠战袍。",
        "beforeLabel": "装之前",
        "afterLabel": "装之后",
        "gotIt": "听懂了",
        "notYet": "没听懂",
        "understood": "✓ 听懂了",
        "termTitle": "你的终端",
        "termSkip": "跳过打字",
        "termDone": "懂了，继续",
        "waiting": "[frago] 已交给这台机器上的 {}，等它开口",
        "fallbackNote": "[frago] 这一轮没接上模型，下面是示例回答（不是它答的）",
        "rows": [
            {"before": "browser use 只活在 agent 会话里，脱离会话就用不了。",
             "after": "可编程的 browser use：会话里能用，编排进流程能用，"
                      "凌晨三点的定时任务也能用。",
             "demo": {
                 "topic": "browser",
                 "ask": "frago 的浏览器，跟我现在这套有什么不一样？",
                 "hook": "[frago] 轻量 ai：这句在问浏览器 → 让我先读 book browser-usage",
                 "reply": [
                     "差别不在能不能开，在谁能用它。",
                     "你现在这套，浏览器只在你盯着的这次对话里活着。",
                     "装完之后它是这台机器的一项能力：我能用，配方能用，",
                     "凌晨三点的定时任务也能用——用的都是你已经登录的那个浏览器。",
                     "想试就说：「用我登录的浏览器看看 GitHub 有什么新通知」",
                 ],
             }},
            {"before": "记忆是有，但每次开场无条件全量灌进去，"
                       "还只认这一个仓库、这一台机器。",
             "after": "主动、有选择地把该用的那条知识和规则送到跟前，"
                      "不打断你手上的事。",
             "demo": {
                 "topic": "memory",
                 "ask": "我跟你说过的规矩，下次开新会话你还记得吗？",
                 "hook": "[frago] 轻量 ai：这句在问知识怎么留下来 → 让我先读 book def-knowledge",
                 "reply": [
                     "记得，但不是靠这次对话记着——它在你这台机器上。",
                     "你每说一句话，frago 先替我看一眼该调哪条，",
                     "只把用得上的那条递给我，不会把你所有的规矩堆进开场。",
                     "下一屏你可以亲手写一条，然后回终端考我。",
                 ],
             }},
            {"before": "skill 带脚本，可每跑一次都得 agent 从头读一遍、推一遍，"
                       "token 就这么烧掉——好比运营商盼着你多看视频，"
                       "好卖你更大的流量套餐。",
             "after": "配方让重复的动作不再由 agent 驱动，像软件一样跑；"
                      "中间需要判断的那几步，再局部叫 agent 上。",
             "demo": {
                 "topic": "recipe",
                 "ask": "同一件事我天天要做，能不能别每次都麻烦你？",
                 "hook": "[frago] 轻量 ai：这句在问重复劳动 → 让我先读 book better-recipe-gate",
                 "reply": [
                     "能。跑通一次之后，我把它收成配方。",
                     "配方是一段能重跑的程序，不再由我一句一句推着走，",
                     "所以它便宜、稳定、能定时跑，跑完给的是结构化结果。",
                     "真需要判断的那几步，配方会单独把我叫上来。",
                 ],
             }},
        ],
        "close": "第二条，一分钟之后你会亲眼看见。",
    },
    "ready": {
        "kicker": "装完了",
        "title": "现在你能拿它干什么",
        "lead": "不用配置，不用学命令。下面三句话，随便挑一句说给它听就行。",
        "cards": [
            {"h": "让它替你上网看东西",
             "say": "用我登录着的浏览器打开 GitHub 通知页，看看有什么新东西",
             "why": "它用你已经登录的那个浏览器，不用你再登一次"},
            {"h": "让它记住你的规矩",
             "say": "记住：给我看代码改动时先说结论，别贴整段文件",
             "why": "说一遍就行，往后它自己带着这条规矩"},
            {"h": "把反复要做的活交出去",
             "say": "把刚才这套流程做成配方，下次我一句话就能重放",
             "why": "跑通一次就固化下来，以后不用你盯着"},
        ],
        "note": "它自带一套操作手册和一批规矩，装完这一刻就在管着自己做事——"
                "你不用知道那是些什么，遇到事它自己会去翻。",
        "cta": "看它记住一件事",
        "copy": "复制",
        "copied": "已复制",
    },
    "demo": {
        "kicker": "现场演示",
        "title": "让它记住一件只有你知道的事",
        "lead": "写一条你希望它以后一直守着的规矩。写真的——按下按钮之后，"
                "这句话就真的在你这台机器上了。",
        "placeholder": "例：我的服务器叫 sg，直接 ssh sg 就能上，别再问我 IP。",
        "samples": [
            "我的服务器叫 sg，直接 ssh sg 就能上，别再问我 IP。",
            "给我看代码改动时先说结论，再说改了哪里，别贴整段文件。",
            "我在北京，写日期一律用 2026-09-05 这种写法，别写 09/05。",
        ],
        "sampleHint": "点一条填进去，或者写你自己的",
        "button": "让它记住",
        "busy": "正在写进去…",
        "savedTitle": "写进去了",
        "savedWhere": "落在知识域",
        "savedDoc": "文档",
        "step2Title": "现在换个地方问它",
        "step2Lead": "回到你刚才装 frago 的那个终端，把这句话发给 agent：",
        "step2Hint": "用你自己的话问也行，只要问的是这件事。",
        "pipelineTitle": "你按下回车之后，这一侧会发生的事",
        "pipeline": [
            "你的话先过一遍 frago 的轻量 ai",
            "它认出这问的是「你自己定的规矩」，让 agent 去查 " + DOMAIN,
            "agent 拿着那条规矩才开口 —— 你没有再讲一遍",
        ],
        "askTitle": "它答上来了吗",
        "yes": "答上来了",
        "no": "没答上来",
        "yesTitle": "那你已经见过 frago 最要紧的那一下了",
        "yesBody": "这条规矩没有留在任何一次对话里。它在这台机器上，"
                   "换个会话、换个 agent、明年再问，都还在。",
        "noTitle": "按这三条查",
        "noSteps": [
            "先直接跑 frago " + DOMAIN + " find —— 有东西说明写成功了，"
            "问题只在这次没被路由过去，换句更贴题的话再问一次。",
            "查 frago server 在不在跑：frago status。这张页面就是它发的，"
            "页面开着通常说明它活着。",
            "还是不行就把这句给 agent：读 frago book def-knowledge，"
            "然后查我在 " + DOMAIN + " 里存了什么。",
        ],
        "copy": "复制",
        "copied": "已复制",
        "error": "没写成",
        "empty": "先写一条规矩",
        "cta": "下一步",
    },
    "why": {
        "kicker": "刚才那一下",
        # 标题上方那一行：给这件事一个名字。人得知道刚才替他找方向的东西叫什么，
        # 才有可能在别处再想起它。
        "product": "frago LightAgent",
        "title": "为什么它不用你再讲一遍",
        # 整页的说明小字：讲的是 LightAgent 这一层本身，不专属于下面任何一步。
        "note": "它跑在 flash 级的小模型上（DS V4 Flash 或同等性价比的模型），"
                "开销小到可以不算——主 agent 会话每消费 10 亿 token，它大约多花 2 块钱。",
        "steps": [
            {"h": "写", "p": "你在页面上按的那个按钮，跑的是这个配方的一个 mode。"
                             "它替你调了 frago 的 def 命令，把那句话存进知识域。"},
            {"h": "认", "p": "你在终端发的每一句话，它都先过一遍。手里有这台机器上"
                             "所有知识域的用途清单，认出你这句问的是「你自己的规矩」。"},
            {"h": "取", "p": "agent 收到的不只是你那句话，还有一句「去 "
                             + DOMAIN + " 查」。它查完才开口。"},
        ],
        "close": "知识是这样，路由规则是这样，配方也是这样。"
                 "frago 攒下来的东西不跟着对话消失——这是它和「一个很能干的聊天窗口」"
                 "最实在的差别。",
        "cta": "那我现在能干点什么",
    },
    "next": {
        "kicker": "接下来",
        "title": "说三句话就够了",
        "lead": "frago 的用法不是背命令，是把话说给 agent 听。这三句可以直接抄走。",
        "items": [
            {"say": "用我登录着的浏览器打开 GitHub 通知页，看看有什么新东西",
             "why": "它用你现成的登录态，不必再登一次，也不会被当成机器人拦下"},
            {"say": "把刚才这套流程做成配方，下次我一句话就能重放",
             "why": "跑通的事固化成能重跑的东西，这是 frago 攒家当的方式"},
            {"say": "从 frago 社区配方仓库里挑几个能帮我干活的装上",
             "why": "填上第三屏那个 0；仓库在 " + COMMUNITY},
        ],
        "linksTitle": "常去的地方",
        "links": [
            {"name": "会话工作台", "href": WORKBENCH,
             "desc": "这台机器上所有会话和配方页面的入口"},
            {"name": "社区配方", "href": COMMUNITY, "desc": "现成的配方从这里取"},
            {"name": "源码与文档", "href": REPO, "desc": "frago 本体"},
        ],
        "restart": "从头再看一遍",
    },
    "fallback": {
        "title": "这张页面还没有内容",
        "body": "页面的字来自配方发布的状态。让 agent 跑一次：",
        "command": "frago recipe run frago_welcome",
    },
}

EN = {
    "lang": "en",
    "langName": "中文",
    "brand": "frago",
    "nav": {"skip": "Skip to the end"},
    "hero": {
        "kicker": "Installed",
        "note": "frago is running on this machine now.",
        "title": "Your agent just got\nthe world's first real AgentOS",
        "cta": "A quick tour of frago",
        "skip": "In a hurry — just give me the commands",
        "hint": "to move",
    },
    "shift": {
        "kicker": "What's new here",
        "title": "Before and after the install",
        "lead": "The CLI agent you already use is genuinely capable — but on its own "
                "it is Tony Stark. frago is the suit.",
        "beforeLabel": "Before",
        "afterLabel": "After",
        "gotIt": "Got it",
        "notYet": "Not really",
        "understood": "✓ Got it",
        "termTitle": "your terminal",
        "termSkip": "Skip typing",
        "termDone": "Understood, carry on",
        "waiting": "[frago] handed to {} on this machine, waiting",
        "fallbackNote": "[frago] no model answered this time — the lines below are a sample, not its answer",
        "rows": [
            {"before": "Browser use lives only inside an agent session — leave it "
                       "and it is gone.",
             "after": "Programmable browser use: in a session, wired into a "
                      "workflow, or in a job at three in the morning.",
             "demo": {
                 "topic": "browser",
                 "ask": "How is frago's browser different from what I have now?",
                 "hook": "[frago] LightAgent: this is about the browser "
                         "-> read book browser-usage first",
                 "reply": [
                     "The difference isn't whether it opens. It's who gets to use it.",
                     "Right now the browser is alive only inside the session you watch.",
                     "After frago it is a capability of this machine: I can use it,",
                     "so can a recipe, so can a job at three in the morning —",
                     "all of them in the browser you are already signed into.",
                 ],
             }},
            {"before": "It remembers — but everything is poured into every session, "
                       "and only this repository on this machine counts.",
             "after": "The one rule that matters arrives on its own, picked by what "
                      "you just asked, without interrupting you.",
             "demo": {
                 "topic": "memory",
                 "ask": "The rule I told you — will you still have it in a new session?",
                 "hook": "[frago] LightAgent: this is about how knowledge "
                         "persists -> read book def-knowledge first",
                 "reply": [
                     "Yes, and not because this conversation is holding it.",
                     "It sits on your machine. Every sentence you send, frago looks",
                     "at what it should fetch and hands me only that one rule —",
                     "it does not pile everything you ever said into the opening.",
                     "Write one on the next screen, then come back and test me.",
                 ],
             }},
            {"before": "A skill carries a script, yet every run re-reads and "
                       "re-reasons it — the way a carrier would rather you watched "
                       "more video, so it can sell a bigger data plan.",
             "after": "A recipe runs the repeated part like software, and calls an "
                      "agent only where judgement is needed.",
             "demo": {
                 "topic": "recipe",
                 "ask": "I do the same thing every day. Must I ask you each time?",
                 "hook": "[frago] LightAgent: this is about repeated work "
                         "-> read book better-recipe-gate",
                 "reply": [
                     "No. Once we get it working I freeze it into a recipe.",
                     "A recipe is a program that reruns; I am no longer driving it",
                     "sentence by sentence, so it is cheap, steady and schedulable,",
                     "and it hands back a structured result.",
                     "Where real judgement is needed, it calls me in for that step.",
                 ],
             }},
        ],
        "close": "The second one you'll see for yourself in about a minute.",
    },
    "ready": {
        "kicker": "Installed",
        "title": "What you can do with it now",
        "lead": "Nothing to configure, no commands to learn. Pick one of these and "
                "say it to your agent.",
        "cards": [
            {"h": "Let it go and look at things for you",
             "say": "Open my GitHub notifications in the browser I'm signed into and "
                    "tell me what's new",
             "why": "It uses the browser you are already signed into — no second login"},
            {"h": "Let it keep a rule of yours",
             "say": "Remember this: when you show me a code change, lead with the "
                    "conclusion, don't paste whole files",
             "why": "Say it once; it carries that rule from now on"},
            {"h": "Hand over the work you repeat",
             "say": "Turn what we just did into a recipe so one sentence replays it",
             "why": "Get it working once, then stop supervising it"},
        ],
        "note": "It arrived with its own manual and a set of rules that already govern "
                "how it works — you never need to know what they are; it looks them up "
                "itself.",
        "cta": "Watch it remember something",
        "copy": "Copy",
        "copied": "Copied",
    },
    "demo": {
        "kicker": "Live",
        "title": "Make it remember something only you know",
        "lead": "Write one rule you want it to keep. Write a real one — once you "
                "press the button, that sentence really is on this machine.",
        "placeholder": "e.g. My server is called sg; ssh sg gets in. Stop asking me "
                       "for the IP.",
        "samples": [
            "My server is called sg; ssh sg gets in. Stop asking me for the IP.",
            "When you show me a code change, lead with the conclusion, then what "
            "moved. Don't paste whole files.",
            "I'm in Beijing. Always write dates as 2026-09-05, never 09/05.",
        ],
        "sampleHint": "Click one to fill it in, or write your own",
        "button": "Remember this",
        "busy": "Writing it down…",
        "savedTitle": "Written",
        "savedWhere": "Domain",
        "savedDoc": "Document",
        "step2Title": "Now ask it somewhere else",
        "step2Lead": "Go back to the terminal where you installed frago and send "
                     "the agent this:",
        "step2Hint": "Your own words work too, as long as you're asking about this.",
        "pipelineTitle": "What happens on this side when you hit enter",
        "pipeline": [
            "Your sentence goes through frago LightAgent first",
            "It recognises this as a question about your own rules and tells the "
            "agent to look in " + DOMAIN,
            "The agent reads that rule before it answers — you never repeated it",
        ],
        "askTitle": "Did it answer?",
        "yes": "It did",
        "no": "It didn't",
        "yesTitle": "Then you've seen the part of frago that matters",
        "yesBody": "That rule never lived in a conversation. It's on this machine — "
                   "another session, another agent, a year from now, still there.",
        "noTitle": "Three things to check",
        "noSteps": [
            "Run frago " + DOMAIN + " find directly. If the rule is there, the write "
            "worked and only the routing missed — ask again in words closer to the rule.",
            "Check the server is up: frago status. This page came from it, so an open "
            "page usually means it's alive.",
            "Still nothing? Send the agent this: read frago book def-knowledge, then "
            "tell me what I have stored in " + DOMAIN + ".",
        ],
        "copy": "Copy",
        "copied": "Copied",
        "error": "Not written",
        "empty": "Write a rule first",
        "cta": "Next",
    },
    "why": {
        "kicker": "What just happened",
        "product": "frago LightAgent",
        "title": "Why you didn't have to say it twice",
        "note": "It runs on a flash-tier model — DS V4 Flash or anything of similar "
                "value — small enough not to count: about $0.30 extra for every "
                "billion tokens your main session spends.",
        "steps": [
            {"h": "Write", "p": "That button ran one mode of this recipe. It called "
                                "frago's def commands and stored your sentence in a "
                                "knowledge domain."},
            {"h": "Recognise", "p": "Every sentence you send passes through it first. "
                                    "It knows what each domain on this machine is for, "
                                    "and saw that yours was about your own rules."},
            {"h": "Fetch", "p": "What reached the agent also said: look in " + DOMAIN +
                                ". It looked before it spoke."},
        ],
        "close": "Knowledge works this way; so do routing rules and recipes. What "
                 "frago accumulates doesn't vanish with the conversation — that is the "
                 "difference from a very capable chat window.",
        "cta": "So what can I do now",
    },
    "next": {
        "kicker": "Next",
        "title": "Three sentences is enough",
        "lead": "Using frago isn't memorising commands — it's talking to your "
                "agent. Take these as they are.",
        "items": [
            {"say": "Open my GitHub notifications in the browser I'm signed into",
             "why": "It uses the session you already have — no second login"},
            {"say": "Turn what we just did into a recipe so one sentence replays it",
             "why": "Freezing what worked is how frago accumulates anything"},
            {"say": "Install a few useful recipes from the frago community repo",
             "why": "Fills in that 0 from the third screen — " + COMMUNITY},
        ],
        "linksTitle": "Where things live",
        "links": [
            {"name": "Session workbench", "href": WORKBENCH,
             "desc": "Sessions and recipe pages"},
            {"name": "Community recipes", "href": COMMUNITY,
             "desc": "Ready-made recipes"},
            {"name": "Source and docs", "href": REPO, "desc": "frago itself"},
        ],
        "restart": "Watch it again",
    },
    "fallback": {
        "title": "This page has no content yet",
        "body": "The words come from state the recipe publishes. Have the agent run:",
        "command": "frago recipe run frago_welcome",
    },
}


#: 交给 agent 那一轮的硬约束。
#:
#: 按这个按钮的人是谁：刚装完 frago、正盯着一句他看不懂的话。他要的是「这句话
#: 什么意思、对我有什么用」，不是浏览器怎么驱动、知识怎么存。上一版问的是机制，
#: 于是答回来的是 Edge profile、native messaging、标签组上限——每个字都对，
#: 每个字他都不需要，看完更不懂。所以这里明写读者是谁，并禁掉命令名和参数名。
#:
#: 为什么还要点名读哪一篇：不点名它就只能凭自己那点印象答，而这台机器上装的
#: 那份说法才是准的。点名之后它跑一条本地命令、秒回，仍然是「问一句就答」。
BRIEF = {
    "zh": "\n\n（回答约束：读者是刚装完 frago、没写过代码的人，他正盯着这句话看不懂。"
          "先跑 {} 读完，按里面写的、用大白话讲清这句话是什么意思、对他有什么用。"
          "四行以内，每行一句话；不要出现命令名、参数名、协议名、文件路径；"
          "除这条命令外不要调用任何工具，不要说明你在做什么。）",
    "en": "\n\n(Constraints: the reader has just installed frago, does not write "
          "code, and is staring at this sentence not understanding it. Run {} first, "
          "then explain in plain words what it means and what it gets them. Four "
          "lines at most, one sentence each; no command names, flags, protocol names "
          "or file paths; apart from that command, no tool calls and no narration.)",
}

#: 页面按 topic 点名，问的是那一条对比右边那句话本身——按钮就长在那句话下面，
#: 人按的是「这句我没听懂」。
QUESTIONS = {
    "browser": {
        "zh": "有人跟我说 frago 的浏览器是「可编程的」：会话里能用，"
              "能编排进流程，凌晨三点的定时任务也能用。这句话什么意思，对我有什么用？",
        "en": "Someone told me frago's browser use is \u201cprogrammable\u201d: usable in a "
              "session, wired into a workflow, or in a job at three in the morning. "
              "What does that actually mean, and what does it get me?",
        "read": "frago book browser-usage、frago book recipe-execution "
                "和 frago book schedule-tasks",
        "read_en": "frago book browser-usage, frago book recipe-execution and "
                   "frago book schedule-tasks",
    },
    "memory": {
        "zh": "有人跟我说 frago 会「主动、有选择地把该用的那条知识和规则送到跟前，"
              "不打断我手上的事」。这句话什么意思，对我有什么用？",
        "en": "Someone told me frago \u201cbrings the one rule that matters on its own, "
              "picked by what you just asked, without interrupting you\u201d. What does "
              "that mean, and what does it get me?",
        "read": "frago book def-knowledge 和 frago book context-recall",
        "read_en": "frago book def-knowledge and frago book context-recall",
    },
    "recipe": {
        "zh": "有人跟我说 frago 的配方能让重复的活「不再由 agent 驱动，像软件一样跑，"
              "中间需要判断的那几步再局部叫 agent 上」。这句话什么意思，对我有什么用？",
        "en": "Someone told me a frago recipe \u201cruns the repeated part like software "
              "and calls an agent only where judgement is needed\u201d. What does that "
              "mean, and what does it get me?",
        "read": "frago book better-recipe-gate 和 frago book recipe-execution",
        "read_en": "frago book better-recipe-gate and frago book recipe-execution",
    },
}


class FragoWelcome(Recipe):
    """装完 frago 之后的第一张页面。"""

    name = "frago_welcome"
    version = "1.0.0"

    #: 不带 mode 跑就是「把页面准备好并打开」——安装 skill 那一侧只会这么用。
    default_mode = "welcome"

    imports = {}

    # ── 主人跑一次：备好这张页面 ──────────────────────────────────────────

    def mode_welcome(self) -> dict:
        """点一遍本机实况、组装文案、发布状态，把地址交出去。"""
        params = self.params
        slot = str(params.get("slot") or "default")

        default_lang = str(params.get("default_lang") or "en")
        if default_lang not in ("en", "zh"):
            raise self.fail("default_lang 只能是 en 或 zh")

        self.progress("点一遍这台机器上有什么", step=1, of=2)
        stats = self._survey()
        self.log("[1/2] ✓ " + ", ".join(
            f"{k}={'?' if v is None else v}" for k, v in stats.items()))

        self.progress(f"发布到槽位 {slot}", step=2, of=2)
        state = {
            "public": {
                "defaultLang": default_lang,
                "domain": DOMAIN,
                "agentCore": self._main_core(),
                "stats": stats,
                "content": {"zh": ZH, "en": EN},
            },
        }
        try:
            url = self.publish(state, slot=slot)
        except (RecipeFailed, BusUnavailable) as err:
            raise self.fail(f"发布页面状态失败: {err}") from err
        self.log(f"[2/2] ✓ {url}")

        out = {
            "success": True,
            "url": url,
            "slot": slot,
            "stats": stats,
            "warnings": list(self.warnings),
        }
        # runner 看到 open_url 会用系统默认浏览器打开它。配方自己不再调
        # frago recipe open——两条一起走会开出两个标签页。
        #
        # open=false 是给「只想把状态刷新一遍」的那次重跑留的：改了文案要重跑才
        # 生效，而每重跑一次就往人的浏览器里推一个标签页，收不回来。
        if params.get("open", True) is not False:
            out["open_url"] = url
        return out

    # ── 页面读的口 ────────────────────────────────────────────────────────

    @export
    def mode_stats(self) -> dict:
        """本机现在有多少配方 / 知识域 / 主题 / 路由规则。

        只读：跑的是 frago 自己的四条 list 命令，不触网、不改任何状态。页面在写完
        一条知识之后调它，把「知识域」那一格从 0 刷成 1。
        """
        return {"stats": self._survey()}

    # ── 页面能按的口 ──────────────────────────────────────────────────────

    @action
    def mode_remember(self) -> dict:
        """把页面上写的那条规矩存进知识域，并给回一句该拿去问 agent 的话。

        标 @action 而不是 @export：它写东西。写的是按按钮的人自己刚敲进去的那句
        话，落在他自己的知识域里——这是这张页面存在的理由，不是顺手加的功能。
        """
        rule = str(self.params.get("rule") or "").strip()
        if len(rule) < RULE_MIN:
            raise self.fail(f"规矩太短了，至少 {RULE_MIN} 个字")
        if len(rule) > RULE_MAX:
            raise self.fail(f"一条规矩最多 {RULE_MAX} 个字，写长了下次它反而不好用")

        self.progress("确认知识域", step=1, of=3)
        created = self._ensure_domain()

        self.progress("写进去", step=2, of=3)
        doc = "rule-" + time.strftime("%Y%m%d-%H%M%S")
        # 知识按规范存：每条带关系标记，说明它是「谁约束谁」。一条用户立下的
        # 规矩，关系类型就是 constraint——A 是这条规矩管的那件事，B 是规矩本身。
        # 不带标记的字符串会被归进 misc，等于把知识降级成散记；而这场演示的全部
        # 意义就是「它按规矩把这件事存下来了」，那一步自己不守规矩就没什么可演的。
        entry = f"[[[constraint]]][[{self._topic(rule)}]][[{rule}]]"
        out = self.ask_frago([
            DOMAIN, "save",
            "--name", doc,
            "--data", json.dumps(
                {"summary": rule[:120], "tags": ["用户规矩", "frago_welcome"]},
                ensure_ascii=False),
            "--content", json.dumps([entry], ensure_ascii=False),
        ], timeout=60)
        if out.get("code") != 0:
            raise self.fail(
                f"写知识域失败：{(out.get('stderr') or out.get('stdout') or '').strip()[:300]}")

        self.progress("再点一遍实况", step=3, of=3)
        stats = self._survey()
        self.log(f"✓ {DOMAIN}/{doc}")

        return {
            "success": True,
            "domain": DOMAIN,
            "doc": doc,
            "domain_created": created,
            # 页面把这句话原样交给人去终端问。带上规矩里的词是故意的：轻量 ai 认的
            # 是「这句话在问什么」，问句里没有那几个词，路由就没有着力点。
            "question": {"zh": self._question(rule, "zh"), "en": self._question(rule, "en")},
            "recall_command": f"frago {DOMAIN} find",
            "stats": stats,
            "warnings": list(self.warnings),
        }

    @action
    def mode_ask(self) -> dict:
        """把页面上那句话真的交给这台机器上的 agent，回它答的原话。

        标 @action：它会起一轮真的 agent 会话，花时间也花 token。页面只能按
        topic 点名（browser / memory / recipe），问题文本在这个文件里——页面能按
        的口不该顺带成为「让这台机器跑任意一句 prompt」的入口。

        跑不成不是致命错：页面那一侧有一份写好的示例回答兜着，只是会明说这是
        示例。刚装完的机器多半还没配 profile，这条路本来就该允许走不通。
        """
        topic = str(self.params.get("topic") or "").strip()
        if topic not in QUESTIONS:
            raise self.fail(f"没有这个话题：{topic}")
        lang = str(self.params.get("lang") or "zh")
        lang = lang if lang in ("zh", "en") else "zh"

        core = self._main_core()
        entry = QUESTIONS[topic]
        source = entry["read"] if lang == "zh" else entry["read_en"]
        question = entry[lang] + BRIEF[lang].format(source)

        self.progress(f"交给 {core}", step=1, of=1)
        out = self.ask_frago(
            ["agent", question, "--json", "--agent-type", core, "--timeout", "90"],
            timeout=150)

        if out.get("code") != 0:
            return {"live": False, "core": core,
                    "reason": (out.get("stderr") or "").strip()[:200] or f"退出码 {out.get('code')}"}
        try:
            answer = json.loads(out.get("stdout") or "{}")
        except json.JSONDecodeError:
            return {"live": False, "core": core, "reason": "返回的不是 JSON"}
        text = (answer.get("text") or "").strip()
        if not text:
            return {"live": False, "core": core, "reason": "这一轮没有答案"}

        return {"live": True, "core": core,
                "lines": [one for one in text.splitlines() if one.strip()][:8]}

    # ── 内部 ──────────────────────────────────────────────────────────────

    def _main_core(self) -> str:
        """这个人平时在跟哪个 cli-agent 说话。

        不问他——他此刻正在跟主 agent 说话，会话账本上就写着。取最近这些会话里
        出现最多的那个内核；账本读不到就按 claude，那是 `frago agent` 的默认。
        """
        out = self._frago(["session", "list", "--json", "--limit", "40"])
        if not out:
            return "claude"
        try:
            rows = json.loads(out)
        except json.JSONDecodeError:
            return "claude"
        if isinstance(rows, dict):
            rows = rows.get("sessions") or rows.get("data") or []
        tally: dict[str, int] = {}
        for row in rows if isinstance(rows, list) else []:
            kind = str((row or {}).get("agent_type") or (row or {}).get("type") or "").strip()
            # frago agent 只认这三个，别的（cursor / cline 之类）不是它能起的
            if kind in ("claude", "codex", "opencode"):
                tally[kind] = tally.get(kind, 0) + 1
        return max(tally, key=tally.get) if tally else "claude"


    def _question(self, rule: str, lang: str) -> str:
        """从规矩里挑出话题，拼一句人可以直接发给 agent 的问话。"""
        topic = self._topic(rule)
        if lang == "en":
            return f"What rule did I set about “{topic}”?"
        return f"我定过一条跟「{topic}」有关的规矩，是什么？"

    @staticmethod
    def _topic(rule: str) -> str:
        """规矩的头一小段，去掉标点和收尾的半个词。

        不做语义抽取：这一句是给人看、给人改的，抽错了比截短更难堪。
        """
        head = re.split(r"[，。,.；;：:！!？?\n]", rule.strip(), maxsplit=1)[0].strip()
        return head if len(head) <= 18 else head[:18].rstrip() + "…"

    def _ensure_domain(self) -> bool:
        """域不在就建一个。返回这次是不是新建的。

        先 list 再 add，而不是直接 add 吞掉重复错误：域已经存在时重新 add 会不会
        覆盖 purpose，取决于 def 那一侧的实现，而 purpose 是用户可能改过的东西——
        改过的东西不该被一张欢迎页悄悄改回去。
        """
        listed = self.ask_frago(["def", "list"], timeout=60)
        if listed.get("code") == 0:
            for line in (listed.get("stdout") or "").splitlines():
                if line.strip().split(" ")[0].strip() == DOMAIN:
                    return False

        out = self.ask_frago([
            "def", "add", DOMAIN,
            "--purpose", DOMAIN_PURPOSE,
            "--schema", json.dumps(DOMAIN_SCHEMA, ensure_ascii=False),
        ], timeout=60)
        if out.get("code") != 0:
            raise self.fail(
                f"建知识域 {DOMAIN} 失败："
                f"{(out.get('stderr') or out.get('stdout') or '').strip()[:300]}")
        return True

    def _survey(self) -> dict:
        """这台机器上现在有多少配方 / 知识域 / book 主题 / 路由规则。

        每一格独立取，取不到就是 None——页面把 None 显示成「读不到」而不是 0。
        把读不到写成 0 会让人以为东西丢了，而 0 在这张页面上是有含义的：它是「还
        没装配方」，是下一步要做的事。两种情况长得一样就没法看了。
        """
        return {
            "recipes": self._count_lines(["recipe", "list", "--format", "names"]),
            "domains": self._count_domains(),
            "topics": self._count_topics(),
            "rules": self._count_rules(),
        }

    def _frago(self, argv: list[str]) -> str | None:
        """跑一条 frago 命令，只要 stdout。跑不成返回 None 并记一条 warning。

        走 ask_frago 而不是 subprocess：配方跑在一个只看得见指定目录的视图里，自己
        起 frago 会读不到平台的书目，而那种失败不报错——命令照样 exit 0，只是答
        「什么都没有」。这几个数字一旦这样错了，整张页面就在说谎。
        """
        try:
            out = self.ask_frago(argv, timeout=60)
        except (RecipeFailed, BusUnavailable) as err:
            self.warn(f"frago {' '.join(argv)} 没跑成：{err}")
            return None
        if out.get("code") != 0:
            self.warn(f"frago {' '.join(argv)} 退出码 {out.get('code')}")
            return None
        return out.get("stdout") or ""

    def _count_lines(self, argv: list[str]) -> int | None:
        text = self._frago(argv)
        if text is None:
            return None
        return len([one for one in text.splitlines() if one.strip()])

    def _count_domains(self) -> int | None:
        text = self._frago(["def", "list"])
        if text is None:
            return None
        # 表格：名字 文档数 创建日期 用途。按「第二列是数字、第三列是日期」认行，
        # 比数行数稳——表头、分隔线和结尾的空行都不长这样。
        rows = re.findall(r"^\s*\S+\s+\d+\s+\d{4}-\d{2}-\d{2}\s", text, re.M)
        return len(rows)

    def _count_topics(self) -> int | None:
        text = self._frago(["book", "--brief"])
        if text is None:
            return None
        return len(re.findall(r"^[a-z0-9][a-z0-9-]*:\s", text, re.M))

    def _count_rules(self) -> int | None:
        text = self._frago(["hook-rules", "list"])
        if text is None:
            return None
        hit = re.search(r"\((\d+)\s+rules shown\)", text)
        if hit:
            return int(hit.group(1))
        # 结尾那句话的措辞变了就退回数行：每条规则一行，表头两行、空行不算。
        rows = re.findall(r"^\s{2}\S+\s+(?:builtin|userdir|agent)\s", text, re.M)
        return len(rows) or None


FragoWelcome.main()
