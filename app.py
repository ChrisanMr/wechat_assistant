# -*- coding: utf-8 -*-
"""
微信聊天模仿助手 - 网页版（Streamlit）
========================================
启动方式（在项目根目录执行）：
    streamlit run app.py

安全说明：本页面只读写你本机的文本文件，不连接微信、不联网、不发送任何消息。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

import main as engine  # noqa: E402  （核心引擎：学习 / 生成回复 / 推荐表情包）

st.set_page_config(page_title="微信聊天模仿助手", page_icon="💬", layout="wide")


# ------------------------------------------------------------------
# 通用小工具
# ------------------------------------------------------------------
def wide(widget) -> dict:
    """
    兼容不同 Streamlit 版本的全宽参数：
    新版用 width="stretch"，老版用 use_container_width=True。
    """
    try:
        import inspect

        if "width" in inspect.signature(widget).parameters:
            return {"width": "stretch"}
    except Exception:
        pass
    return {"use_container_width": True}


def get_cfg() -> dict:
    """每次刷新都重新读 config.yaml，方便你改完配置立刻生效。"""
    return engine.load_config()


def contact_options(cfg: dict) -> list:
    """所有可用联系人 = 有聊天记录的 + 已有人设的。"""
    keys = list(engine.list_contacts(cfg))
    persona_dir = engine.dirs_of(cfg)["persona"]
    for f in sorted(persona_dir.glob("*.yaml")):
        if not f.name.startswith("_") and f.stem not in keys:
            keys.append(f.stem)
    return keys


def show_emoji(row: dict, width: int = 130) -> None:
    """显示一个表情包图片（文件不存在时只显示文件名）。"""
    path = Path(row.get("path", ""))
    if path.exists():
        st.image(str(path), width=width, caption=row.get("filename", ""))
    else:
        st.warning(f"缺少图片文件：{row.get('filename', '')}\n请把图片放进 emoji_lib/ 目录")


# ------------------------------------------------------------------
# 侧边栏：选联系人
# ------------------------------------------------------------------
cfg = get_cfg()
engine.ensure_dirs(cfg)
keys = contact_options(cfg)

with st.sidebar:
    st.title("💬 聊天模仿助手")
    st.caption("本地离线版 · 不接管微信 · 数据只在你电脑上")

    if not keys:
        st.error("还没有任何联系人。\n\n请到「📚 学习/更新」标签页导入聊天记录。")
        contact = None
    else:
        labels = {k: engine.parse_contact_key(k, cfg)["display"] for k in keys}
        contact = st.selectbox(
            "选择联系人（我是怎么跟他说话的）",
            options=keys,
            format_func=lambda k: labels.get(k, k),
        )

    persona = None
    if contact:
        try:
            persona = engine.load_persona(contact, cfg)
            style = persona.get("style", {})
            meta = persona.get("meta", {})
            st.success(f"语气：{style.get('tone', '?')}　平均 {style.get('avg_length', '?')} 字/条")
            st.caption(
                f"素材：{meta.get('my_message_count', 0)} 条我的消息　"
                f"学习时间：{meta.get('learned_at', '?')}"
            )
            if st.button("🔄 重新学习这个联系人", **wide(st.button)):
                with st.spinner("正在学习聊天记录..."):
                    engine.learn_contact(contact, cfg, verbose=False)
                st.success("已更新人设档案")
                st.rerun()
        except FileNotFoundError:
            persona = None
            st.warning("这个人还没有人设档案，请先到「📚 学习/更新」里学习一次。")

    st.divider()
    st.caption("配置：config.yaml　|　人设：persona/　|　表情包：emoji_lib/")


st.title("模仿我本人的微信回复助手")
st.caption(
    "工作流：复制对方的消息 → 在这里生成我的回复 → 手动复制文字 / 手动挑表情包 → 在微信里发送。"
)

tab_reply, tab_persona, tab_emoji, tab_learn, tab_help = st.tabs(
    ["💬 生成回复", "🧑 我的人设档案", "😂 表情包库", "📚 学习/更新", "❓ 使用说明"]
)


# ==================================================================
# 标签页 1：生成回复
# ==================================================================
with tab_reply:
    if not contact:
        st.info("请先在左侧选择联系人（还没有联系人的话，去「📚 学习/更新」导入聊天记录）。")
    elif persona is None:
        st.info("这个人还没有人设档案。请点击左侧「🔄 重新学习这个联系人」，或到「📚 学习/更新」学习一次。")
    else:
        st.subheader(f"对方（{engine.parse_contact_key(contact, cfg)['display']}）发来的消息")
        incoming = st.text_area(
            "把对方的消息粘贴到这里（支持多行）",
            height=110,
            placeholder="例如：周末一起打球不",
            label_visibility="collapsed",
        )

        col_a, col_b, col_c = st.columns([1, 1, 2])
        with col_a:
            n = st.number_input("备选条数", min_value=1, max_value=3, value=int(cfg["generator"].get("candidates", 3)))
        with col_b:
            st.write("")
            generate = st.button("🚀 生成回复", type="primary", **wide(st.button))
        with col_c:
            st.write("")
            if st.button("🎲 换一批（重新随机）", **wide(st.button)):
                st.session_state["seed"] = datetime.now().microsecond
                st.session_state["regen"] = True

        if generate or st.session_state.pop("regen", False):
            if not incoming.strip():
                st.warning("先粘贴对方的消息吧~")
            else:
                st.session_state["result"] = engine.generate_replies(
                    contact, incoming.strip(), cfg, n=int(n),
                    seed=st.session_state.get("seed"),
                )

        result = st.session_state.get("result")
        if result and result["contact"] == contact:
            st.divider()
            st.caption(
                f"识别意图：**{result['intent']}**　|　模仿语气：**{result['tone']}**　|　"
                f"生成引擎：{result['engine']}"
            )
            st.markdown("#### 备选回复（点右上角图标即可复制）")
            for i, reply in enumerate(result["replies"], 1):
                with st.container(border=True):
                    st.caption(f"备选 {i}｜{reply['style']}")
                    st.code(reply["text"], language=None)

            st.markdown("#### 推荐表情包（在微信里手动选同名图片发送）")
            emojis = result["emoji"]
            if not emojis:
                st.info("emoji_lib 里还没有表情包，或这句话不适合配表情包。到「😂 表情包库」里加几个吧。")
            else:
                cols = st.columns(len(emojis))
                for col, emo in zip(cols, emojis):
                    with col:
                        show_emoji(emo)
                        st.caption(f"**{emo['filename']}**")
                        st.caption("标签：" + "/".join(emo["tags"]))
                        st.caption(emo["reason"])

            with st.expander("为什么这样回？（看它参考的人设）"):
                st.markdown(f"**{persona.get('meta', {}).get('contact', '')} 的人设总结：**")
                st.write(persona.get("summary", ""))
                st.markdown("**生成提示：**")
                st.write(persona.get("generation_hint", ""))


# ==================================================================
# 标签页 2：人设档案
# ==================================================================
with tab_persona:
    if not contact or persona is None:
        st.info("请先在左侧选择一个已经学习过的联系人。")
    else:
        meta = persona.get("meta", {})
        style = persona.get("style", {})
        st.subheader(f"{meta.get('contact', '')}（{meta.get('relation', '')}）的人设档案")
        st.info(persona.get("summary", ""))

        col1, col2 = st.columns([3, 2])
        with col1:
            st.markdown("##### 说话风格")
            st.table({
                "项目": ["语气", "语气来源", "平均长度", "常见长度", "表情使用率", "反问率", "分词方式"],
                "值": [
                    style.get("tone", ""),
                    style.get("tone_reason", ""),
                    f"{style.get('avg_length', '')} 字",
                    style.get("length_style", ""),
                    f"{style.get('emoji_rate', 0):.0%}",
                    f"{style.get('question_rate', 0):.0%}",
                    meta.get("word_segment", ""),
                ],
            })
        with col2:
            st.markdown("##### 标点习惯")
            for habit in persona.get("punctuation_habits", []):
                st.write("· " + habit)

        st.markdown("##### 高频词")
        words = persona.get("frequent_words") or []
        if words:
            import pandas as pd

            chart = pd.DataFrame({"词": [w["word"] for w in words[:12]],
                                  "出现次数": [w["count"] for w in words[:12]]}).set_index("词")
            st.bar_chart(chart)
        else:
            st.caption("（素材太少，暂时统计不出高频词）")

        col3, col4 = st.columns(2)
        with col3:
            st.markdown("##### 口头禅 / 习惯用语")
            for item in persona.get("catchphrases") or []:
                st.write(f"· **{item['phrase']}**（{item['count']} 次，{item.get('type', '')}）")
            st.markdown("##### 常用表情")
            emojis = persona.get("common_emoji") or []
            st.write("、".join(f"{e['emoji']}×{e['count']}" for e in emojis) or "基本不用表情")
        with col4:
            st.markdown("##### 禁忌话术（生成时永不出现）")
            st.write("、".join(persona.get("taboo") or []) or "（无）")

        st.markdown("##### 回复示例（真实聊天里「对方说 → 我当时回」）")
        examples = persona.get("reply_examples") or []
        if examples:
            st.dataframe(
                [{"对方说": e.get("场景_对方说", ""), "我当时回": e.get("我当时回", "")} for e in examples],
                **wide(st.dataframe),
                hide_index=True,
            )
        else:
            st.caption("（没有抽到问答配对，可以多导入一些聊天记录）")

        st.markdown("##### 我的真实原话样例（生成时的兜底素材）")
        st.write("　|　".join(persona.get("my_real_templates") or []) or "（无）")

        yaml_path = engine.persona_path(contact, cfg)
        with st.expander("查看 / 下载原始 yaml（可以直接手改，改完刷新页面生效）"):
            st.code(yaml_path.read_text(encoding="utf-8"), language="yaml")
            st.download_button("⬇️ 下载这个 yaml", yaml_path.read_text(encoding="utf-8"),
                               file_name=yaml_path.name)


# ==================================================================
# 标签页 3：表情包库
# ==================================================================
with tab_emoji:
    st.subheader("我的表情包库")
    emoji_dir = engine.dirs_of(cfg)["emoji_lib"]
    rows = engine.load_emoji_rows(cfg)

    st.caption(f"目录：{emoji_dir}　共 {len(rows)} 个表情包")
    if rows:
        cols = st.columns(4)
        for i, row in enumerate(rows):
            with cols[i % 4]:
                with st.container(border=True):
                    show_emoji(row, width=110)
                    st.caption("标签：" + ("/".join(row["tags"]) or "（还没打标签）"))
                    if not row.get("exists"):
                        st.caption("⚠️ 图片文件不存在")

    st.divider()
    col_add, col_edit = st.columns(2)

    with col_add:
        st.markdown("##### ➕ 新增表情包")
        uploaded = st.file_uploader("选择图片（jpg / png / gif / webp）", type=["jpg", "jpeg", "png", "gif", "webp"])
        new_tags = st.text_input("标签（用逗号分隔）", placeholder="搞笑,哈哈,无语")
        if st.button("保存到表情包库", type="primary"):
            if not uploaded:
                st.warning("先选一张图片")
            else:
                target = emoji_dir / uploaded.name
                target.write_bytes(uploaded.getbuffer())
                engine.add_emoji(uploaded.name, new_tags, cfg)
                st.success(f"已保存 {uploaded.name}")
                st.rerun()

    with col_edit:
        st.markdown("##### ✏️ 修改标签")
        if rows:
            pick = st.selectbox("选择表情包", [r["filename"] for r in rows])
            current = next((r for r in rows if r["filename"] == pick), {"tags": []})
            tags_input = st.text_input("新标签（会用逗号分隔，覆盖旧标签）",
                                       value=",".join(current.get("tags") or []))
            if st.button("更新标签"):
                merged = engine.split_tags(tags_input)
                for row in rows:
                    if row["filename"] == pick:
                        row["tags"] = merged
                engine.save_emoji_rows(rows, cfg)
                st.success("标签已更新")
                st.rerun()
        else:
            st.caption("还没有表情包")

    st.divider()
    st.markdown("##### 🔍 试一下推荐效果")
    test_text = st.text_input("输入一句对话，看看推荐哪个表情包", value="笑死我了 太离谱了吧")
    if test_text:
        hits = engine.recommend_emoji(test_text, cfg, persona=persona, n=3)
        if not hits:
            st.info("没有匹配到合适的表情包（可以给表情包多加些标签，或在 config.yaml 的 emoji_tags 里加关键词）")
        for emo in hits:
            st.write(f"**{emo['filename']}**　标签：{'/'.join(emo['tags'])}　{emo['reason']}")


# ==================================================================
# 标签页 4：学习 / 更新
# ==================================================================
with tab_learn:
    st.subheader("学习我的聊天记录（生成 / 更新人设档案）")
    chat_dir = engine.dirs_of(cfg)["chat_records"]
    st.caption(f"聊天记录目录：{chat_dir}")

    record_files = sorted(chat_dir.glob("*.txt"))
    if record_files:
        st.markdown("##### 已导入的聊天记录")
        st.dataframe(
            [
                {
                    "联系人文件": f.name,
                    "行数": len(f.read_text(encoding="utf-8", errors="ignore").splitlines()),
                    "修改时间": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                }
                for f in record_files
            ],
            **wide(st.dataframe),
            hide_index=True,
        )

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("##### 🔄 学习 / 更新")
        incremental = st.checkbox(
            "增量学习（把新粘贴的记录合并进旧档案）", value=bool(cfg["learning"].get("incremental", True))
        )
        if record_files:
            pick = st.selectbox("选择要学习的聊天记录", [f.stem for f in record_files])
            if st.button("学习这个联系人", type="primary"):
                try:
                    result = engine.learn_contact(pick, cfg, incremental=incremental, verbose=False)
                    st.success(
                        f"完成：{pick}（语气 {result['style']['tone']}，"
                        f"我的消息 {result['meta']['my_message_count']} 条）"
                    )
                except Exception as exc:
                    st.error(f"学习失败：{exc}")
        if st.button("学习全部聊天记录"):
            results = engine.learn_all(cfg, verbose=False)
            st.success(f"完成，共更新 {len(results)} 个联系人的人设档案")
        if st.button("查看当前人设列表"):
            for f in sorted(engine.dirs_of(cfg)["persona"].glob("*.yaml")):
                if not f.name.startswith("_"):
                    data = engine.load_yaml(f)
                    st.write(f"· {f.stem}　{data.get('meta', {}).get('my_message_count', '?')} 条　"
                             f"{data.get('style', {}).get('tone', '?')}")

    with col2:
        st.markdown("##### 📥 新增聊天记录")
        st.caption("从微信手动复制出来的文字，粘贴到这里；说话人写成「我」代表自己。")
        relation = st.selectbox("这个联系人属于", ["朋友", "家人", "同事", "同学", "恋人", "客户", "其他"])
        who = st.text_input("联系人名字（例如：小张）")
        pasted = st.text_area(
            "粘贴聊天记录（每行：说话人: 内容，例如 `我: 在呢`）",
            height=200,
            placeholder="我: 在呢\n小张: 周末打球不\n我: 打啊 几点",
        )
        mode = st.radio("保存方式", ["新建文件", "追加到已有文件"], horizontal=True)
        target_stem = st.text_input("追加时填文件名（不带 .txt）", value="", placeholder="留空则用上面「关系_名字」")
        if st.button("保存聊天记录"):
            if not who.strip() or not pasted.strip():
                st.warning("联系人和聊天记录都要填哦")
            else:
                if mode == "追加到已有文件":
                    stem = target_stem.strip() or f"{relation}_{who.strip()}"
                    path = chat_dir / f"{stem}.txt"
                    with path.open("a", encoding="utf-8") as fh:
                        fh.write("\n" + pasted.strip() + "\n")
                else:
                    path = chat_dir / f"{relation}_{who.strip()}.txt"
                    path.write_text(pasted.strip() + "\n", encoding="utf-8")
                st.success(f"已保存到 {path.name}，现在可以点左边「学习这个联系人」了")
                st.rerun()


# ==================================================================
# 标签页 5：使用说明
# ==================================================================
with tab_help:
    st.markdown(
        """
### 这个工具能做什么
它是一个**替身写作助手**：学你平时的微信说话方式，在你自己复制粘贴消息后，帮你写出「像你本人会回的话」，
并推荐一个合适的表情包。**它不碰微信，也不会自动发消息。**

### 三步工作流
1. **导入素材**：从微信里手动复制你和一个联系人的聊天记录，粘贴到「📚 学习/更新」，
   说话人写成「我」（代表你）和对方的名字。保存 → 点「学习这个联系人」。
2. **生成回复**：在「💬 生成回复」里粘贴对方刚发来的消息 → 生成 2~3 条备选 → 点右上角图标复制。
3. **手动发送**：回到微信，粘贴文字；需要表情包时，在 `emoji_lib/` 里找到推荐的文件名，手动选择发送。

### 聊天记录格式
```
2024-05-01 20:31:12 小张: 在吗
2024-05-01 20:31:40 我: 在呢
我: 打啊 几点          ← 时间可以省略
小张: 晚上有空吗
```
* 以 `#` 开头的是注释，会被忽略
* 一个人的消息如果换行写，续行会自动接到上一条
* 想追加新记录：直接在文件末尾粘贴，再点一次「学习这个联系人」（勾上增量学习）

### 数据存在哪
| 内容 | 位置 |
| --- | --- |
| 聊天记录 | `chat_records/*.txt` |
| 我的人设档案 | `persona/*.yaml` |
| 表情包图片 | `emoji_lib/*.png` |
| 表情包标签 | `emoji_lib/emoji_tag.csv` |
| 全部规则配置 | `config.yaml` |

**所有数据都在你自己的电脑上，程序不会联网上传。** 只有当你把 `config.yaml` 里的
`generator.engine` 改成 `ollama` 时，才会访问你本机的 `127.0.0.1:11434`（本地大模型，仍然是本地）。

### 想让它更像你
* 多喂素材：同一个联系人 50~200 条你的消息，效果明显变好
* 装 `jieba` 分词，高频词统计会干净很多
* 嫌句子不像，就直接改 `config.yaml` 里的 `reply_templates`（那是回复模板库）
* 嫌语气不对，改 `persona/xxx.yaml` 里的 `style.tone` / `generation_hint`，刷新页面即可生效
* 表情包推荐不准，就在 `config.yaml` 的 `emoji_tags` 里加「关键词 → 标签」的映射

### 命令行等价操作（不想开网页时）
```bash
python main.py learn                                  # 学习全部聊天记录
python main.py learn --contact 朋友_小张               # 只学一个
python main.py reply --contact 朋友_小张 --msg "在吗"   # 生成回复
python main.py interactive                            # 命令行交互模式
```
"""
)
