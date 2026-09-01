#!/usr/bin/env python3
# frago-recipe/1
# 本文件由 frago recipe create 生成。能力建在基类 Recipe 上，
# 落点、消息、跨模块调用、页面发布都走基类。规范：frago book recipe-creation
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10.0"]
# ///
"""把本地成片投到 B 站创作中心：传片、传封面、填完整张表，默认停在存草稿。

节奏全部由这边控制：一次 exec-js 只干一件事。页面里写 await sleep 循环会被
Chrome 的后台 tab 定时器节流拖到几分钟，别那么干。

**一个口都不导出，唯一的 mode 也不标 @action。** 导出的承诺是「不触网、不重算、
不改状态、别人每 5 分钟问一次也不会出事」——这个 mode 每一条都占。它还会以主人的
身份往站外发东西，那正是 recipe-creation 里点名 NEVER 标 @action 的那一类。

publish=true 才会点「立即投稿」。默认 false 停在「存草稿」，留给人自己过一眼再投。
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import threading
import time
import urllib.parse

from frago_recipe import Recipe, RecipeFailed

UPLOAD_URL = "https://member.bilibili.com/platform/upload/video/frame"

#: 选择器锚在 placeholder 文案上，比 data-v-* 和 CSS-in-JS 的类名活得久
SEL_TITLE = 'input.input-val[placeholder="请输入稿件标题"]'
SEL_TAGIN = 'input.input-val[placeholder="按回车键Enter创建标签"]'
SEL_DECL = "input.bcc-select-input-inner"
SEL_COVER_SUBMIT = "div.button.submit"

DECLARATIONS = [
    "内容无需标注", "含AI生成内容", "含虚构演绎内容",
    "内容含营销信息", "个人观点，仅供参考", "内容为转载",
]

#: 话题 + 标签共用这一个上限
TAG_LIMIT = 10

#: 页面的 Vue 组件是这一整页的真数据源：提交时读的是它，不是 DOM。
#: 认组件只能用 $options._componentTag——$options.name 在这一页是空的，用它必然找不到。
JS_VB = """
  function vb(){
    var els = document.querySelectorAll('*');
    for (var i = 0; i < els.length; i++) {
      var v = els[i].__vue__;
      if (v && v.$options && v.$options._componentTag === 'video-basic') return v;
    }
    return null;
  }
"""


def q(v):
    """把 Python 值塞进 JS 源码里，走 JSON 而不是拼引号。"""
    return json.dumps(v, ensure_ascii=False)


# ---------------------------------------------------------------- 本地取文件

class _CORS(http.server.SimpleHTTPRequestHandler):
    """https 页面要 fetch 回环地址，缺一个头就整条链路断掉。

    Access-Control-Allow-Private-Network 是 Chrome 的 Private Network Access
    预检要的；回环地址本身不算 mixed content，所以 http 不会被拦。
    """

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,HEAD,OPTIONS")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_a):
        pass


class Browser:
    """驱动 frago browser 的扩展后端——登录态在浏览器自己的 profile 里。"""

    def __init__(self, group):
        self.group = group

    def _run(self, args, timeout=180):
        p = subprocess.run(["frago", "browser"] + args + ["--group", self.group],
                           capture_output=True, text=True, timeout=timeout)
        if p.returncode != 0:
            raise RecipeFailed(
                f"frago browser {' '.join(args[:2])} 失败: {p.stderr.strip()[:300]}")
        return p.stdout

    def navigate(self, url):
        return self._run(["navigate", url])

    def js(self, code):
        """exec-js 把整段代码当一个表达式求值，所以调用方必须自己包成 IIFE。

        另外 CLI 会把「看起来像路径」的参数当成 JS 源码，别传文件路径进来。
        """
        out = self._run(["exec-js", "--return-value", code])
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            raise RecipeFailed(f"exec-js 返回的不是 JSON: {out[:300]}") from None
        if data.get("ok") is False:
            raise RecipeFailed(f"页内报错: {data.get('error')}")
        return data.get("value")


def normalize_cover(src, workdir):
    """首页推荐位是 4:3。非 4:3 的图补边成 4:3，正文压进中间的 16:9 带。

    这样 4:3 那版左右不裁字，16:9 那版上下也不裁字。
    补边色取原图四角的众数，深色卡片接缝看不出来。
    """
    from PIL import Image

    dst = os.path.join(workdir, "_bili_cover_4x3.png")
    img = Image.open(src).convert("RGB")
    w, h = img.size
    if abs(w / h - 4 / 3) < 0.01:
        img.save(dst)
        return dst
    corners = [img.getpixel(p) for p in ((1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2))]
    bg = max(set(corners), key=corners.count)
    band_w, band_h = 1440, 810
    scale = min(band_w / w, band_h / h)
    band = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    canvas = Image.new("RGB", (1440, 1080), bg)
    canvas.paste(band, ((1440 - band.width) // 2, (1080 - band.height) // 2))
    canvas.save(dst)
    return dst


# ---------------------------------------------------------------- 模块

class BilibiliPublishVideo(Recipe):
    """把成片投到 B 站创作中心，默认只存草稿。"""

    name = "bilibili_publish_video"
    version = "1.1.0"

    #: 只有一件事。
    default_mode = "publish"

    #: 不依赖任何模块。
    imports = {}

    # ── 唯一的一件事 ────────────────────────────────────────────────────

    def mode_publish(self) -> dict:
        p = self.params
        resume = bool(p.get("resume_unsubmitted", False))
        video = p.get("video_path")
        title = p.get("title")
        publish = bool(p.get("publish", False))
        tags = list(p.get("tags") or [])
        extra_drop = set(p.get("drop_tags") or [])
        prune = bool(p.get("drop_unlisted_tags", True))
        cover = p.get("cover_path")
        cover_fit = p.get("cover_fit", "pad")
        topic = p.get("topic")
        port = int(p.get("port", 8777))

        if not title:
            raise self.fail("title 必填")
        if not resume and not video:
            raise self.fail("video_path 必填（只有 resume_unsubmitted=true 时可以省）")
        if video and not os.path.isfile(video):
            raise self.fail(f"找不到成片: {video}")
        if cover and not os.path.isfile(cover):
            raise self.fail(f"找不到封面: {cover}")
        if cover_fit not in ("pad", "as_is"):
            raise self.fail("cover_fit 只能是 pad 或 as_is")

        self.br = Browser(p.get("group", "bili"))
        steps: list[str] = []
        httpd = None
        # 暂存目录开在本模块自己的落点里，NEVER 自己往 /tmp 拼路径
        workdir = self.store.path("_staging")
        shutil.rmtree(workdir, ignore_errors=True)
        workdir.mkdir(parents=True, exist_ok=True)

        def note(msg: str) -> None:
            steps.append(msg)
            self.progress(msg)

        try:
            video_name, cover_name = self._stage(video, cover, str(workdir), cover_fit)
            httpd = self._serve(str(workdir), port)
            base = f"http://127.0.0.1:{port}/"

            self.br.navigate(UPLOAD_URL)
            time.sleep(4)

            if self._handle_unsubmitted_banner(resume):
                note("未提交稿件横幅: " + ("接回来了" if resume else "点了不用了"))
            elif resume:
                raise self.fail("要求接回未提交稿件，但页面上没有那条横幅")

            if resume:
                note(f"接回的分P: {self._wait_upload()}")
            else:
                size = self._inject_file(base + urllib.parse.quote(video_name),
                                         video_name, ".mp4", "__fragoUp")
                note(f"成片已注入 {size} 字节")
                note(f"上传完成: {self._wait_upload()}")

            if cover_name:
                got = self._set_cover(base + urllib.parse.quote(cover_name), cover_name)
                if got != "set":
                    raise self.fail(f"封面没挂上（页面状态 {got}）")
                note("封面已上传")

            note("标题: " + self._set_title(title))

            decl = p.get("declaration")
            if decl and decl != "内容无需标注":
                note("创作声明: " + self._set_declaration(decl))

            # 话题必须排在标签前面：它会占掉一个标签位，先占后算剩几格
            if topic:
                note(f"话题({self._set_topic(topic)}): {topic}")

            keep = set(tags) | ({topic} if topic else set())
            if prune:
                gone = self._prune_tags(keep, extra_drop)
                if gone:
                    note("摘掉自动标签: " + "/".join(gone))
            else:
                for name in extra_drop:
                    self._drop_tag(name)

            for tag in tags:
                current = self._read_tags()
                if tag in current:
                    continue
                if len(current) >= TAG_LIMIT:
                    note(f"标签满 {TAG_LIMIT} 个，{tag} 起没加进去")
                    break
                if not self._add_tag(tag):
                    note(f"标签「{tag}」B 站没收，跳过")
            if prune:
                # 加标签会触发 B 站再塞一轮推荐词，所以这里要再扫一遍
                gone = self._prune_tags(keep, extra_drop)
                if gone:
                    note("二次摘掉: " + "/".join(gone))
            note("标签: " + "/".join(self._read_tags()))

            if p.get("description"):
                note(f"简介 {self._set_quill('desc', p['description'])['model']} 字")
            if p.get("dynamic_text"):
                note(f"粉丝动态 {self._set_quill('dyn', p['dynamic_text'])['model']} 字")

            form = self._snapshot()
            page = self._submit(publish)

            return {
                "submitted": publish,
                "form": form,
                "steps": steps,
                "page": page,
                "note": "" if publish else "只存了草稿，去创作中心复核后自己点投稿",
            }
        except RecipeFailed as err:
            raise self.fail(str(err), steps=steps) from None
        finally:
            if httpd:
                httpd.shutdown()
                httpd.server_close()      # shutdown 只停 serve_forever，端口还占着
            shutil.rmtree(workdir, ignore_errors=True)

    # ── 取文件 ──────────────────────────────────────────────────────────

    def _serve(self, directory, port):
        socketserver.TCPServer.allow_reuse_address = True
        httpd = socketserver.TCPServer(
            ("127.0.0.1", port), functools.partial(_CORS, directory=directory))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd

    def _stage(self, video, cover, workdir, cover_fit):
        """成片和封面都软链/落到同一个暂存目录，一个 server 端口托全程。

        成片走软链是为了不复制几十上百 MB；封面按 cover_fit 决定改不改尺寸。
        接回未提交稿件时 video 是 None——那时片子已经在 B 站服务端，本地不用托。
        """
        video_name = None
        if video:
            link = os.path.join(workdir, os.path.basename(video))
            os.symlink(os.path.abspath(video), link)
            video_name = os.path.basename(link)

        cover_name = None
        if cover:
            src = os.path.abspath(cover)
            if cover_fit == "as_is":
                dst = os.path.join(workdir, os.path.basename(src))
                shutil.copyfile(src, dst)
                cover_name = os.path.basename(dst)
            else:
                cover_name = os.path.basename(normalize_cover(src, workdir))
        return video_name, cover_name

    def _inject_file(self, url, filename, accept_hint, flag):
        """页内 fetch 本地文件 → File → DataTransfer → input.files。

        浏览器不让 JS 直接给 file input 赋值，但 DataTransfer 这条路是开的。
        """
        self.br.js(f"""(() => {{
          window.{flag} = {{ state: 'start' }};
          (async () => {{
            try {{
              const input = Array.from(document.querySelectorAll('input[type=file]'))
                .find(i => (i.accept || '').includes({q(accept_hint)}));
              if (!input) {{ window.{flag} = {{ state: 'error', msg: 'no file input' }}; return; }}
              const resp = await fetch({q(url)});
              if (!resp.ok) {{ window.{flag} = {{ state: 'error', msg: 'fetch ' + resp.status }}; return; }}
              const blob = await resp.blob();
              const dt = new DataTransfer();
              dt.items.add(new File([blob], {q(filename)}, {{ type: blob.type }}));
              input.files = dt.files;
              input.dispatchEvent(new Event('change', {{ bubbles: true }}));
              window.{flag} = {{ state: 'dispatched', bytes: blob.size }};
            }} catch (e) {{ window.{flag} = {{ state: 'error', msg: String(e) }}; }}
          }})();
          return 'kicked';
        }})()""")

        for _ in range(120):
            time.sleep(1)
            st = self.br.js(f"(() => JSON.stringify(window.{flag} || null))()")
            st = json.loads(st) if st else None
            if not st:
                continue
            if st["state"] == "error":
                raise self.fail(f"文件注入失败: {st['msg']}")
            if st["state"] == "dispatched":
                return st["bytes"]
        raise self.fail("文件注入超时")

    # ── 表单各处 ────────────────────────────────────────────────────────

    def _handle_unsubmitted_banner(self, resume):
        """投稿页顶部那条「本地浏览器存在N个未提交的视频」。

        它是上一次没走完的残留。默认点「不用了」，否则这一次会接着上一轮的稿子填，
        最后传上去的是两轮混在一起的东西。
        resume=True 才点「继续编辑」——那是浏览器桥中途断线后的救援路径：
        视频已经在 B 站服务端了，接回来就不用再传一遍几十上百兆。
        """
        label = "继续编辑" if resume else "不用了"
        hit = self.br.js(f"""(() => {{
          const b = Array.from(document.querySelectorAll('span,button,div,a'))
            .filter(e => e.children.length === 0
                      && (e.innerText || '').trim() === {q(label)} && e.offsetParent);
          if (!b.length) return false;
          b[0].click();
          return true;
        }})()""")
        if hit:
            time.sleep(6)
        return bool(hit)

    def _wait_upload(self, timeout=1800):
        """等 B 站把片子收完。

        只认组件里的 status/progress，不认页面上那行「上传完成」的字：
        换视频、续传这些情形下那行字会先于真状态出现。
        """
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            raw = self.br.js(f"""(() => {{
              {JS_VB}
              const c = vb();
              if (!c) return null;
              const t = (c.videoTasks || []).map(x => ({{
                cid: x.cid, size: x.size, up: x.uploadedSize,
                st: x.status, pg: x.progress
              }}));
              return JSON.stringify({{ n: t.length, t: t }});
            }})()""")
            if raw:
                last = json.loads(raw)
                done = [x for x in last["t"] if x["st"] == 3 and x["pg"] == 100]
                if last["n"] and len(done) == last["n"]:
                    return last
            time.sleep(3)
        raise self.fail(f"等上传完成超时，最后读到: {last}")

    def _set_title(self, title):
        """先走输入框；输入框没找到就直接写组件。

        两条都要：提交读的是组件，而输入框才会触发 B 站的字数校验与推荐标签。
        """
        got = self.br.js(f"""(() => {{
          {JS_VB}
          const t = document.querySelector({q(SEL_TITLE)});
          if (t) {{
            const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            t.focus(); s.call(t, {q(title)});
            t.dispatchEvent(new Event('input', {{ bubbles: true }}));
            t.dispatchEvent(new Event('change', {{ bubbles: true }}));
            t.blur();
          }}
          const c = vb();
          if (c && c.title !== {q(title)}) c.title = {q(title)};
          return c ? c.title : (t ? t.value : null);
        }})()""")
        if got != title:
            raise self.fail(f"标题没写进去，页面上是: {got!r}")
        return got

    def _set_declaration(self, name):
        self.br.js(f"""(() => {{
          const i = document.querySelector({q(SEL_DECL)});
          i.focus(); i.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true }})); i.click();
          return 'opened';
        }})()""")
        time.sleep(1.5)
        # 下拉项是点开才挂上来的，而且它们自己不带 class——只能按父节点的 bcc-option 认
        hit = self.br.js(f"""(() => {{
          const o = Array.from(document.querySelectorAll('*'))
            .filter(e => e.children.length === 0 && (e.innerText || '').trim() === {q(name)})
            .find(e => e.parentElement
                    && String(e.parentElement.className).includes('bcc-option'));
          if (!o) return false;
          [o, o.parentElement].forEach(n =>
            ['mouseover', 'mousedown', 'mouseup', 'click'].forEach(t =>
              n.dispatchEvent(new MouseEvent(t, {{ bubbles: true, cancelable: true }}))));
          return true;
        }})()""")
        if not hit:
            raise self.fail(f"创作声明里没有「{name}」这一项，可选：{DECLARATIONS}")
        # 点完要等 Vue 把值刷回 input，当场读是空的
        time.sleep(1.5)
        got = self.br.js(f"(() => (document.querySelector({q(SEL_DECL)}) || {{}}).value)()")
        if got != name:
            raise self.fail(f"创作声明没选上，页面上是: {got!r}")
        return got

    def _set_topic(self, topic):
        """话题优先点「参与话题」现成的 chip，没有再走搜索弹窗。

        注意：选中的话题会作为第一个标签 chip 插进标签区，和普通标签共用上限 10。
        """
        hit = self.br.js(f"""(() => {{
          const c = Array.from(document.querySelectorAll('*'))
            .filter(e => e.children.length === 0 && (e.innerText || '').trim() === {q(topic)});
          if (!c.length) return false;
          c[0].click();
          return true;
        }})()""")
        if hit:
            time.sleep(1.5)
            return "chip"

        self.br.js("""(() => {
          const a = Array.from(document.querySelectorAll('*'))
            .find(e => e.children.length === 0 && /搜索更多话题/.test(e.innerText || ''));
          if (!a) return 'no-entry';
          a.click(); return 'opened';
        })()""")
        time.sleep(2)
        self.br.js(f"""(() => {{
          const inp = document.querySelector('input.bcc-search-input');
          const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          inp.focus(); s.call(inp, {q(topic)});
          inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
          inp.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', keyCode: 13, bubbles: true }}));
          return 'searched';
        }})()""")
        time.sleep(2.5)
        ok = self.br.js(f"""(() => {{
          const m = Array.from(document.querySelectorAll('[class*=dialog],[class*=modal]'))
            .find(e => (e.innerText || '').includes('参与话题'));
          if (!m) return false;
          const hit = Array.from(m.querySelectorAll('*'))
            .find(e => e.children.length === 0 && (e.innerText || '').trim() === {q(topic)});
          if (!hit) return false;
          hit.click();
          const ok = Array.from(m.querySelectorAll('button,div,span'))
            .find(e => e.children.length === 0 && (e.innerText || '').trim() === '确定');
          if (ok) ok.click();
          return true;
        }})()""")
        time.sleep(1.5)
        if not ok:
            raise self.fail(f"话题「{topic}」没搜到，名字要和 B 站上完全一致")
        return "search"

    def _read_tags(self):
        return json.loads(self.br.js(
            "(() => JSON.stringify(Array.from("
            "document.querySelectorAll('.label-item-v2-content')).map(e => e.innerText.trim())))()"))

    def _drop_tag(self, name):
        """删一个标签 chip。

        关闭按钮是 chip 里的 svg，**不一定带 .close 类**——2026-08-31 实测这一页没有。
        另外点完 Vue 要一两秒才重渲染，当场回读拿到的还是旧值，所以这里等完再让调用方核。
        """
        gone = self.br.js(f"""(() => {{
          const chip = Array.from(document.querySelectorAll('.label-item-v2-container'))
            .find(c => {{
              const p = c.querySelector('.label-item-v2-content');
              return p && p.innerText.trim() === {q(name)};
            }});
          if (!chip) return false;
          const x = chip.querySelector('svg.close') || chip.querySelector('svg');
          if (!x) return false;
          ['mousedown', 'mouseup', 'click'].forEach(t =>
            x.dispatchEvent(new MouseEvent(t, {{ bubbles: true, cancelable: true }})));
          return true;
        }})()""")
        if gone:
            time.sleep(1.5)
        return bool(gone)

    def _prune_tags(self, keep, extra_drop):
        """把不是我配的标签全摘掉。

        B 站按标题自动塞泛标签，每次塞的还不一样（实测见过「分享/原创」，
        也见过「学习」「编程/学习/教育」），所以不能靠一张固定的黑名单，
        只能反过来：不在 keep 里的一律删。
        """
        dropped = []
        for name in list(self._read_tags()):
            if name in keep and name not in extra_drop:
                continue
            if self._drop_tag(name):
                dropped.append(name)
        return dropped

    def _add_tag(self, tag):
        """一个标签两次 exec-js：先落字，再敲回车。中间的等待放在这边。"""
        self.br.js(f"""(() => {{
          const inp = document.querySelector({q(SEL_TAGIN)});
          const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
          inp.focus(); s.call(inp, {q(tag)});
          inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
          return inp.value;
        }})()""")
        time.sleep(0.8)
        self.br.js(f"""(() => {{
          const inp = document.querySelector({q(SEL_TAGIN)});
          ['keydown', 'keypress', 'keyup'].forEach(t => inp.dispatchEvent(
            new KeyboardEvent(t, {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }})));
          return 'enter';
        }})()""")
        time.sleep(1.2)
        return tag in self._read_tags()

    def _set_quill(self, which, text):
        """简介和粉丝动态都是 quill，实例挂在编辑器父元素的 __quill 上。

        只写编辑器不够：2026-08-31 实测 setText 之后组件里的 desc 仍是空的，
        而提交时 B 站读的是组件——那一版存下去简介是空白，页面上的字数计数器却是对的，
        肉眼看不出来。所以写完必须回读组件，没同步就直接补上，对不上就报错。
        """
        marker = "更全面" if which == "desc" else "动态描述"
        field = "desc" if which == "desc" else "dynamic"
        raw = self.br.js(f"""(() => {{
          {JS_VB}
          let ed = Array.from(document.querySelectorAll('.ql-editor'))
            .find(e => (e.getAttribute('data-placeholder') || '').includes({q(marker)}));
          if (!ed) {{
            // placeholder 变了就退回按可见性认：简介是看得见那个，动态是藏起来那个
            const all = Array.from(document.querySelectorAll('.ql-editor'));
            const wide = all.filter(e => e.getBoundingClientRect().width > 100);
            ed = ({q(which)} === 'desc') ? wide[0] : all.find(e => wide.indexOf(e) < 0);
          }}
          if (!ed || !ed.parentElement.__quill) return JSON.stringify({{ err: 'no-quill' }});
          ed.parentElement.__quill.setText({q(text)}, 'user');
          const c = vb();
          if (c && (c[{q(field)}] || '').length !== {q(text)}.length) {{
            c[{q(field)}] = {q(text)};
            const v2 = {q(field)} + '_v2';
            if (v2 in c) c[v2] = [{{ raw_text: {q(text)}, type: 1, biz_id: '' }}];
          }}
          return JSON.stringify({{
            editor: ed.innerText.length,
            model: c ? (c[{q(field)}] || '').length : null
          }});
        }})()""")
        got = json.loads(raw) if raw else {"err": "no-return"}
        if got.get("err"):
            raise self.fail(f"{which} 写不进去: {got['err']}")
        if got.get("model") != len(text):
            raise self.fail(
                f"{which} 只进了编辑器没进组件"
                f"（编辑器 {got.get('editor')} 字 / 组件 {got.get('model')} 字），"
                "这样提交上去会是空的")
        return got

    def _set_cover(self, cover_url, filename):
        self.br.js("""(() => {
          const b = Array.from(document.querySelectorAll('*'))
            .filter(e => e.children.length === 0
                      && ['添加封面', '封面设置'].includes((e.innerText || '').trim()));
          if (!b.length) return 'none';
          b[0].click(); return 'opened';
        })()""")
        time.sleep(3)
        # 弹窗里还有一颗「上传封面」要点，它才会新建 file input
        self.br.js("""(() => {
          const b = Array.from(document.querySelectorAll('span,button,div,a'))
            .filter(e => e.children.length === 0 && (e.innerText || '').trim() === '上传封面');
          if (!b.length) return 'none';
          b[0].click(); return 'clicked';
        })()""")
        time.sleep(1.5)
        self._inject_file(cover_url, filename, "image/png", "__fragoCov")
        time.sleep(3)

        # 「完成」偶尔第一下点不动（弹窗还在过渡），点到它消失为止
        for _ in range(5):
            left = self.br.js(f"""(() => {{
              const b = Array.from(document.querySelectorAll({q(SEL_COVER_SUBMIT)}))
                .filter(e => e.offsetParent && (e.innerText || '').trim() === '完成');
              if (!b.length) return 0;
              b[0].scrollIntoView({{ block: 'center' }}); b[0].click();
              return b.length;
            }})()""")
            time.sleep(2.5)
            if not left:
                break
        still = self.br.js(f"""(() => Array.from(document.querySelectorAll({q(SEL_COVER_SUBMIT)}))
          .filter(e => e.offsetParent && (e.innerText || '').trim() === '完成').length)()""")
        if still:
            raise self.fail("封面弹窗没关掉，确认一下图是不是被 B 站拒了")

        # 封面成没成，看那颗按钮的文案：没图是「添加封面」，有图变成「封面设置」
        return self.br.js("""(() => {
          const has = t => Array.from(document.querySelectorAll('*'))
            .some(e => e.children.length === 0 && (e.innerText || '').trim() === t);
          return has('封面设置') ? 'set' : (has('添加封面') ? 'empty' : 'unknown');
        })()""")

    def _snapshot(self):
        raw = self.br.js(f"""(() => {{
          {JS_VB}
          const c = vb() || {{}};
          const parts = (c.videoTasks || []).map(x => ({{
            cid: x.cid, filename: x.filename, size: x.size,
            status: x.status, progress: x.progress
          }}));
          const has = t => Array.from(document.querySelectorAll('*'))
            .some(e => e.children.length === 0 && (e.innerText || '').trim() === t);
          return JSON.stringify({{
            title: c.title || null,
            tid: c.tid === undefined ? null : c.tid,
            declaration: (document.querySelector({q(SEL_DECL)}) || {{}}).value || null,
            tags: Array.from(document.querySelectorAll('.label-item-v2-content'))
                    .map(e => e.innerText.trim()),
            desc_len: (c.desc || '').length,
            dynamic_len: (c.dynamic || '').length,
            cover: has('封面设置') ? 'set' : 'empty',
            parts: parts
          }});
        }})()""")
        return json.loads(raw) if raw else {}

    def _submit(self, publish):
        """存草稿点 span.submit-draft，立即投稿点 span.submit-add。

        这两颗按钮挨着，只按文案找容易点错，所以先按 class 收窄再核文案；
        收窄之后还不是唯一一个，就停下不点。
        """
        label, cls = ("立即投稿", "submit-add") if publish else ("存草稿", "submit-draft")
        hit = self.br.js(f"""(() => {{
          let b = Array.from(document.querySelectorAll('span.' + {q(cls)}))
            .filter(e => (e.innerText || '').trim() === {q(label)} && e.offsetParent);
          if (!b.length) {{
            b = Array.from(document.querySelectorAll('span,button,div'))
              .filter(e => e.children.length === 0
                        && (e.innerText || '').trim() === {q(label)} && e.offsetParent);
          }}
          if (b.length !== 1) return b.length;
          b[0].scrollIntoView({{ block: 'center' }}); b[0].click();
          return true;
        }})()""")
        if hit is not True:
            raise self.fail(f"「{label}」按钮找到 {hit} 个，没敢点")
        time.sleep(8)
        raw = self.br.js("(() => JSON.stringify({url: location.href, "
                         "text: document.body.innerText.replace(/\\n{2,}/g, '|').slice(0, 400)}))()")
        return json.loads(raw) if raw else {}


BilibiliPublishVideo.main()
