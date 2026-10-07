# -*- coding: utf-8 -*-
"""
微信聊天模仿助手（本地离线版）
================================
功能：
  1. 学习我导出的聊天记录，按联系人分别生成「我的个人聊天人设档案」(yaml)
  2. 输入「联系人 + 对方发来的消息」，生成 2~3 条模仿我口吻的备选回复
  3. 根据对话语义，从本地表情包库里推荐 1~2 个匹配标签的表情包

安全声明：
  * 不连接微信、不读取微信数据库、不自动发送任何消息
  * 不访问网络（除非你在 config.yaml 里显式把 engine 改成 ollama，且只连本机 127.0.0.1）
  * 聊天记录 / 人设档案 / 表情包 全部保存在本项目目录，不上传云端

命令行用法：
  python main.py learn                      # 学习 chat_records/ 下所有聊天记录
  python main.py learn --contact 朋友_小张   # 只学习某个联系人
  python main.py list                       # 查看已有人设档案
  python main.py reply --contact 朋友_小张 --msg "在吗"
  python main.py emoji --msg "笑死我了"      # 只推荐表情包
  python main.py interactive                # 命令行交互模式
  python main.py gui                        # 提示如何启动网页版
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# ------------------------------------------------------------------
# 0. 依赖检查：只需要 PyYAML 一个第三方库
# ------------------------------------------------------------------
try:
    import yaml
except ImportError:  # pragma: no cover
    print("[错误] 缺少依赖 PyYAML，请先执行：pip install pyyaml")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent

# ------------------------------------------------------------------
# 1. 默认配置（config.yaml 里没写的项会用这里的值兜底）
# ------------------------------------------------------------------
DEFAULT_CONFIG = {
    "identity": {"me_names": ["我"], "self_name": "我"},
    "paths": {
        "chat_records": "chat_records",
        "persona": "persona",
        "emoji_lib": "emoji_lib",
        "emoji_tag_csv": "emoji_lib/emoji_tag.csv",
    },
    "generator": {
        "engine": "local",
        "candidates": 3,
        "max_chars": 60,
        "use_emoji_char": True,
        "ollama": {"host": "http://127.0.0.1:11434", "model": "qwen2.5:7b", "timeout": 120},
    },
    "learning": {
        "top_words": 20,
        "top_phrases": 12,
        "max_examples": 12,
        "incremental": True,
    },
    "contacts": {},
    "relation_tone": {"朋友": "沙雕", "家人": "温和", "同事": "正式", "未知": "中性"},
    "forbidden": {"global": ["作为AI", "作为人工智能", "希望对你有所帮助", "综上所述", "首先，", "其次，"]},
    "intents": {},
    "reply_templates": {},
    "tone_templates": {},
    "tone_flavor": {
        "沙雕": {"head": [], "tail": ["哈哈哈", "笑死", "绝了"]},
        "温和": {"head": [], "tail": ["~", "啦", "呀"]},
        "正式": {"head": ["好的，"], "tail": ["，谢谢"]},
        "中性": {"head": [], "tail": []},
        "简短": {"head": [], "tail": []},
    },
    "tone_emoji_bonus": {
        "沙雕": ["搞笑", "哈哈", "无语"],
        "温和": ["感谢", "安慰", "加油"],
        "正式": ["收到", "OK", "感谢"],
        "中性": ["收到"],
        "简短": ["OK"],
    },
    "emoji_tags": {},
}

# 当 config.yaml 里没有对应意图的模板时，用这份兜底模板
FALLBACK_TEMPLATES = {
    "问候": {"短": ["在呢"], "中": ["在呢，咋啦"], "长": ["在的，刚看到消息"]},
    "提问": {"短": ["我看看"], "中": ["我想想哈"], "长": ["我看看，等下回你"]},
    "邀约": {"短": ["行"], "中": ["行啊，几点"], "长": ["可以啊，你定时间"]},
    "吐槽": {"短": ["确实"], "中": ["确实有点离谱"], "长": ["哎，确实挺难的"]},
    "感谢": {"短": ["客气"], "中": ["客气啥"], "长": ["客气啥，有事说话"]},
    "道歉": {"短": ["没事"], "中": ["没事没事"], "长": ["真没事，别放心上"]},
    "告别": {"短": ["好"], "中": ["好，晚安"], "长": ["好嘞，那你早点休息"]},
    "工作": {"短": ["收到"], "中": ["好的，我看下"], "长": ["好的，我看一下再同步给你"]},
    "分享": {"短": ["不错"], "中": ["哎不错啊"], "长": ["可以啊，看着挺不错的"]},
    "关心": {"短": ["知道啦"], "中": ["知道啦，我会注意的"], "长": ["好的，我记住了，你也注意点"]},
    "安慰": {"短": ["加油"], "中": ["加油，会好的"], "长": ["别急，慢慢来，会好起来"]},
    "日常": {"短": ["嗯嗯"], "中": ["嗯嗯，是这样"], "长": ["嗯嗯，我这边也差不多"]},
    "其他": {"短": ["嗯嗯"], "中": ["嗯嗯，好"], "长": ["嗯嗯，我知道了"]},
}

# 中文停用词（做高频词统计时过滤掉，避免统计出一堆“的了吗”）
STOPWORDS = set(
    """的 了 是 我 你 他 她 它 我们 你们 他们 在 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 会 着
    没有 看 好 自己 这 那 这个 那个 什么 怎么 因为 所以 但是 如果 就是 可以 不是 还是 真的 现在 时候
    一下 有点 还是 已经 应该 知道 觉得 感觉 可能 比较 然后 而且 其实 这样 那样 一样 一直 出来 起来
    过来 下来 们 吧 吗 呢 啊 呀 哦 嗯 哈 呵 唉 哎 咦 诶 嘛 啦 咯 咧 喔 哟 着 过 得 地 把 被 让 给 对 从
    向 于 与 及 或 并 而 则 以 之 其 该 等 各 每 某 些 个 只 条 张 次 点 种 位 名 件 台 部 本 当 又 再 才
    太 更 最 挺 蛮 好 少 多 大 小 新 老 快 慢 早 晚 高 低 长 短 前 后 里 外 中 间 时 分 秒 天 周 月 年""".split()
)

# 常见语气词 / 口头禅候选（用来统计习惯用语）
INTERJECTIONS = [
    "哈哈", "哈哈哈", "哈哈哈哈", "哈哈哈哈哈哈", "hhhh", "emmm", "emmmmm", "嗯嗯", "嗯", "哦哦", "哦",
    "哎呀", "哎", "啊", "呀", "哈", "行吧", "行嘞", "好嘞", "好的", "收到", "在呢", "在的",
    "可以", "没事", "真的", "确实", "离谱", "绝了", "笑死", "卧槽", "牛啊", "6", "？？",
    "。。。", "~", "～", "完了", "算了", "随便", "都行", "再说", "好呀", "好吧", "是呗", "对吧",
]
# 按长度倒序，用于「最长匹配」统计，避免「哈哈」把「哈哈哈哈哈」也数一遍
INTERJECTIONS_SORTED = sorted(INTERJECTIONS, key=len, reverse=True)
INTERJECTION_SET = set(INTERJECTIONS)

# 无 jieba 时的降级分词用：这些字出现在词首/词尾，说明多半是切碎的碎片
NGram_BAD_EDGE = set("的了是在不我你他她它和与还把被给让对从向而又才再太更最挺会去说看有没吗吧呢啊呀哦嗯个这那就都很到过着地得什么怎么因为所以但是如果就是可以")


# 表情符号 / 微信表情 识别正则
EMOJI_CHAR_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U0001F000-\U0001F2FF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "\U0000FE0F"
    "\U0000203C\U00002049"
    "]"
)
WECHAT_EMOJI_RE = re.compile(r"\[[^\[\]\s]{1,8}\]")

# 标点统计用的字符
PUNCT_CHARS = ["。", "！", "？", "～", "~", "…", "，", "、", ",", ".", "!", "?"]

# 判断“书面语 / AI 味”的词
FORMAL_WORDS = ["收到", "好的", "确认", "稍后", "同步", "辛苦", "麻烦", "感谢", "安排", "反馈", "处理", "对齐", "进度"]
BOOKISH_WORDS = ["首先", "其次", "综上", "敬请", "烦请", "望知悉", "特此", "据悉", "予以", "务必"]

# 聊天记录里“我”说的话，按行匹配的两种模式
RE_WITH_TIME = re.compile(
    r"^\[?(?P<time>\d{4}[-/.]\d{1,2}[-/.]\d{1,2}[ T]\d{1,2}:\d{2}(?::\d{2})?)\]?\s*"
    r"(?P<speaker>[^:：]{1,20}?)\s*[:：]\s*(?P<content>.*)$"
)
RE_TIME_ONLY = re.compile(
    r"^\[?(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\]?\s*(?P<speaker>[^:：]{1,20}?)\s*[:：]\s*(?P<content>.*)$"
)
RE_PLAIN = re.compile(r"^(?P<speaker>[^:：]{1,12}?)\s*[:：]\s*(?P<content>.*)$")


# ==================================================================
# 2. 基础工具：配置读写 / 路径 / YAML 兼容
# ==================================================================
def deep_merge(base: dict, override: dict) -> dict:
    """递归合并字典：override 覆盖 base，base 不被修改。"""
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict:
    """读取 config.yaml，并用默认值兜底。"""
    cfg = DEFAULT_CONFIG
    path = BASE_DIR / "config.yaml"
    if path.exists():
        user_cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        cfg = deep_merge(DEFAULT_CONFIG, user_cfg)
    return cfg


def load_yaml(path: Path) -> dict:
    """读取 yaml 文件，不存在则返回空字典。"""
    path = Path(path)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def dump_yaml(obj: dict, path: Path) -> None:
    """把字典写成 yaml（保留中文、保留插入顺序）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, width=120, default_flow_style=False)
    path.write_text(text, encoding="utf-8")


def dirs_of(cfg: dict) -> dict:
    """把配置里的相对路径解析成绝对路径。"""
    paths = cfg["paths"]
    return {
        "chat_records": BASE_DIR / paths.get("chat_records", "chat_records"),
        "persona": BASE_DIR / paths.get("persona", "persona"),
        "emoji_lib": BASE_DIR / paths.get("emoji_lib", "emoji_lib"),
        "emoji_tag_csv": BASE_DIR / paths.get("emoji_tag_csv", "emoji_lib/emoji_tag.csv"),
    }


def ensure_dirs(cfg: dict) -> dict:
    """确保 4 个目录都存在（首次运行自动创建）。"""
    dirs = dirs_of(cfg)
    for key in ("chat_records", "persona", "emoji_lib"):
        dirs[key].mkdir(parents=True, exist_ok=True)
    dirs["emoji_tag_csv"].parent.mkdir(parents=True, exist_ok=True)
    if not dirs["emoji_tag_csv"].exists():
        dirs["emoji_tag_csv"].write_text("filename,tags\n", encoding="utf-8")
    return dirs


def parse_contact_key(key: str, cfg: dict = None) -> dict:
    """
    把文件名/联系人标识拆成 关系 + 名字。
    例：'朋友_小张' -> {'key': '朋友_小张', 'relation': '朋友', 'name': '小张'}
    config.yaml 的 contacts 段可以手动指定关系。
    """
    cfg = cfg or load_config()
    name, relation = key, "未知"
    for sep in ("_", "-"):
        if sep in key:
            left, right = key.split(sep, 1)
            if left in cfg.get("relation_tone", {}) or left in ("朋友", "家人", "同事", "同学", "恋人", "客户"):
                relation, name = left, right
            else:
                name = key
            break
    # 配置里的 contacts 映射优先（按名字匹配）
    for cname, crelation in (cfg.get("contacts") or {}).items():
        if cname and cname in name:
            relation, name = crelation, cname
            break
    return {"key": key, "relation": relation, "name": name, "display": f"{name}（{relation}）"}


# ==================================================================
# 3. 聊天记录解析
# ==================================================================
def parse_chat_text(text: str, me_names=None) -> list:
    """
    解析聊天记录文本，返回 [{'time':..,'speaker':..,'content':..,'is_me':bool}, ...]
    支持格式：
        2024-05-01 20:31:12 小张: 在吗
        [20:31] 小张: 在吗
        小张: 在吗
    也支持消息换行（没有说话人前缀的行会接到上一条消息上）。
    """
    me_names = set(me_names or ["我"])
    raw_lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    # 去掉空行和 # 注释行
    lines = [ln for ln in raw_lines if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return []

    # 先判断这个文件里带时间戳的行多不多，决定用哪套正则
    ts_hits = sum(1 for ln in lines if RE_WITH_TIME.match(ln) or RE_TIME_ONLY.match(ln))
    use_ts = ts_hits >= max(1, len(lines) * 0.5)

    messages = []
    for line in lines:
        match = None
        if use_ts:
            match = RE_WITH_TIME.match(line) or RE_TIME_ONLY.match(line)
        if match is None:
            match = RE_PLAIN.match(line)
            if match:
                speaker = match.group("speaker").strip()
                # 过滤误判：说话人里有空格/斜杠，或太长，说明这行其实是正文
                if " " in speaker or "//" in speaker or len(speaker) > 12 or speaker == "":
                    match = None
        if match is None:
            # 续行：拼到上一条消息后面
            if messages:
                messages[-1]["content"] += "\n" + line.strip()
            continue
        speaker = match.group("speaker").strip()
        content = (match.group("content") or "").strip()
        time_str = match.groupdict().get("time") or ""
        messages.append(
            {
                "time": time_str.strip(),
                "speaker": speaker,
                "content": content,
                "is_me": speaker in me_names,
            }
        )
    return [m for m in messages if m["content"]]


def read_chat_file(path: Path, me_names=None) -> list:
    """读取一个聊天记录 txt 并解析。"""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    return parse_chat_text(text, me_names)


def list_contacts(cfg: dict = None) -> list:
    """列出 chat_records/ 下所有聊天记录对应的联系人（按文件名）。"""
    cfg = cfg or load_config()
    dirs = ensure_dirs(cfg)
    keys = []
    for f in sorted(dirs["chat_records"].glob("*.txt")):
        if f.name.startswith("_"):
            continue
        keys.append(f.stem)
    return keys


# ==================================================================
# 4. 文本统计（学习我的说话风格）
# ==================================================================
def clean_text(text: str) -> str:
    """去掉表情符号和微信表情码，用于统计文字部分。"""
    text = WECHAT_EMOJI_RE.sub(" ", text)
    text = EMOJI_CHAR_RE.sub(" ", text)
    return text.strip()


def has_jieba() -> bool:
    """是否装了 jieba（装了分词质量更好，没装也能跑）。"""
    try:
        import jieba  # noqa: F401

        return True
    except Exception:
        return False


def filter_ngram_noise(counter: Counter) -> Counter:
    """
    只有没装 jieba 时才会用到：把 2~3 字滑窗切出来的碎片清理掉。
    规则：① 首尾是停用字的丢掉；② 3 字碎片至少出现 2 次；③ 被更高频的长词包含的短碎片丢掉。
    """
    step1 = Counter()
    for word, count in counter.items():
        if word in INTERJECTION_SET:
            step1[word] += count
        elif word[0] in NGram_BAD_EDGE or word[-1] in NGram_BAD_EDGE:
            continue
        elif len(word) >= 3 and count < 2:
            continue
        else:
            step1[word] += count

    kept = Counter()
    for word, count in sorted(step1.items(), key=lambda kv: (-kv[1], -len(kv[0]))):
        # 已经留下一个更长、出现次数不比自己少的词，说明自己是拼接碎片
        if word not in INTERJECTION_SET and any(
            len(other) > len(word) and word in other and other_count >= count for other, other_count in kept.items()
        ):
            continue
        kept[word] += count

    # 只出现一次的多半是切碎的碎片，优先保留出现过两次以上的词
    repeated = Counter({w: c for w, c in kept.items() if c >= 2 or w in INTERJECTION_SET})
    return repeated if len(repeated) >= 3 else kept


def count_interjections(text: str) -> Counter:
    """最长匹配统计语气词，避免「哈哈哈哈」被同时算成 4 个「哈」。"""
    counts = Counter()
    i = 0
    while i < len(text):
        for word in INTERJECTIONS_SORTED:
            if text.startswith(word, i):
                counts[word] += 1
                i += len(word)
                break
        else:
            i += 1
    return counts


def segment_words(text: str) -> list:
    """
    分词：优先用 jieba（如果有装）；没装就降级为「英文/数字按词 + 中文 2~3 字滑窗」。
    """
    text = clean_text(text)
    words = []
    try:
        import jieba  # type: ignore

        words = list(jieba.lcut(text))
    except Exception:
        words.extend(re.findall(r"[A-Za-z]{2,}|\d+", text))
        for seg in re.findall(r"[\u4e00-\u9fff]+", text):
            for n in (2, 3):
                for i in range(len(seg) - n + 1):
                    words.append(seg[i : i + n])
    result = []
    for w in words:
        w = w.strip()
        if len(w) < 2:
            continue
        if w in STOPWORDS:
            continue
        if re.fullmatch(r"[\W_]+", w):  # 纯标点
            continue
        result.append(w)
    return result


def extract_stats(messages: list, cfg: dict) -> dict:
    """
    从解析好的消息里提取「原始统计量」（可累加，用于增量学习）。
    """
    me_names = set(cfg["identity"].get("me_names") or ["我"])
    raw = {
        "my_count": 0,
        "other_count": 0,
        "lengths": [],
        "word_counter": Counter(),
        "exact_counter": Counter(),
        "interjection_counter": Counter(),
        "punct_counter": Counter(),
        "emoji_char_counter": Counter(),
        "wechat_emoji_counter": Counter(),
        "emoji_msg_count": 0,
        "punct_msg_count": 0,
        "question_count": 0,
        "exclaim_count": 0,
        "examples": [],
        "pairs": [],
    }

    for idx, msg in enumerate(messages):
        speaker = msg["speaker"]
        content = msg["content"].strip()
        if speaker not in me_names and not msg["is_me"]:
            raw["other_count"] += 1
            # 记录「对方说 -> 我回」的配对，作为回复示例
            for nxt in messages[idx + 1 : idx + 4]:
                if nxt["is_me"]:
                    if len(raw["pairs"]) < 400:
                        raw["pairs"].append({"对方": content[:80], "我": nxt["content"][:80]})
                    break
            continue

        # ---- 以下都是“我”说的话 ----
        raw["my_count"] += 1
        plain = clean_text(content)                    # 去掉表情后的纯文字
        raw["lengths"].append(len(plain))
        raw["examples"].append(content[:100])

        for w in segment_words(content):
            raw["word_counter"][w] += 1
        raw["exact_counter"][content[:60]] += 1

        # 语气词用「最长匹配」统计
        raw["interjection_counter"].update(count_interjections(content))

        msg_punct = False
        for p in PUNCT_CHARS:
            c = content.count(p)
            if c:
                raw["punct_counter"][p] += c
                msg_punct = True
        if msg_punct:
            raw["punct_msg_count"] += 1
        if "？" in content or "?" in content:
            raw["question_count"] += 1
        if "！" in content or "!" in content:
            raw["exclaim_count"] += 1

        emojis = EMOJI_CHAR_RE.findall(content)
        if emojis:
            raw["emoji_msg_count"] += 1
            for e in emojis:
                raw["emoji_char_counter"][e] += 1
        for e in WECHAT_EMOJI_RE.findall(content):
            raw["emoji_msg_count"] += 1
            raw["wechat_emoji_counter"][e] += 1

    # 没装 jieba 时，把滑窗切出来的碎片清理掉
    if not has_jieba():
        raw["word_counter"] = filter_ngram_noise(raw["word_counter"])

    return raw


def merge_stats(old: dict, new: dict) -> dict:
    """增量学习：把两次统计结果合并（计数相加，样本列表截断保留）。"""
    if not old:
        return new
    merged = dict(old)
    for key in ("my_count", "other_count", "emoji_msg_count", "punct_msg_count", "question_count", "exclaim_count"):
        merged[key] = int(old.get(key, 0)) + int(new.get(key, 0))
    for key in ("word_counter", "exact_counter", "interjection_counter", "punct_counter",
                "emoji_char_counter", "wechat_emoji_counter"):
        counter = Counter(old.get(key) or {})
        counter.update(new.get(key) or {})
        merged[key] = counter
    merged["lengths"] = (list(old.get("lengths") or []) + list(new.get("lengths") or []))[-2000:]
    merged["examples"] = (list(old.get("examples") or []) + list(new.get("examples") or []))[-800:]
    merged["pairs"] = (list(old.get("pairs") or []) + list(new.get("pairs") or []))[-400:]
    return merged


def stats_to_dict(raw: dict) -> dict:
    """把 Counter 转成普通 dict，方便存进 yaml（顺便控制文件大小）。"""
    out = {}
    for key, value in raw.items():
        if isinstance(value, Counter):
            out[key] = dict(value.most_common(200))
        elif isinstance(value, list):
            if key == "lengths":
                out[key] = value[-500:]
            elif key == "examples":
                out[key] = value[-400:]
            else:
                out[key] = value[-300:]
        else:
            out[key] = value
    return out


def dict_to_stats(data: dict) -> dict:
    """从 yaml 里读回统计数据，恢复成 Counter。"""
    raw = dict(data or {})
    for key in ("word_counter", "exact_counter", "interjection_counter", "punct_counter",
                "emoji_char_counter", "wechat_emoji_counter"):
        raw[key] = Counter(raw.get(key) or {})
    raw.setdefault("lengths", [])
    raw.setdefault("examples", [])
    raw.setdefault("pairs", [])
    return raw


# ==================================================================
# 5. 生成人设档案
# ==================================================================
def infer_tone(raw: dict, cfg: dict, relation: str) -> tuple:
    """根据数据 + 关系，推断我面对这个联系人时的语气，并给出理由。"""
    my_count = max(1, raw["my_count"])
    lengths = raw["lengths"] or [0]
    avg_len = sum(lengths) / len(lengths)

    laugh_words = ["哈哈", "笑死", "卧槽", "草", "绝了", "离谱", "6", "牛啊", "？？"]
    laugh_hits = sum(sum(1 for w in laugh_words if w in ex) for ex in raw["examples"])
    laugh_rate = laugh_hits / my_count

    formal_hits = sum(sum(1 for w in FORMAL_WORDS if w in ex) for ex in raw["examples"])
    formal_rate = formal_hits / my_count

    base = (cfg.get("relation_tone") or {}).get(relation, "中性")
    if relation != "同事" and laugh_rate >= 0.12:
        return "沙雕", f"调侃/网络用语占比 {laugh_rate:.0%}，对{relation}说话比较放松"
    if formal_rate >= 0.25:
        return "正式", f"“收到/确认/同步”这类词占比 {formal_rate:.0%}，对{relation}偏正式"
    if avg_len <= 6:
        return "简短", f"平均每句只有 {avg_len:.1f} 个字，说话很短"
    return base, f"按关系「{relation}」推定为基础语气，数据上没有明显偏离"


def build_persona(raw: dict, contact_key: str, source_file: str, cfg: dict, learn_runs: int = 1) -> dict:
    """把统计数据加工成一份可读、可编辑、可用于生成的人设档案。"""
    info = parse_contact_key(contact_key, cfg)
    relation, name = info["relation"], info["name"]
    learning = cfg.get("learning") or {}
    top_n_words = int(learning.get("top_words", 20))
    top_n_phrases = int(learning.get("top_phrases", 12))
    max_examples = int(learning.get("max_examples", 12))

    my_count = max(1, raw["my_count"])
    lengths = raw["lengths"] or [0]
    avg_len = sum(lengths) / len(lengths)
    lengths_sorted = sorted(lengths)
    median_len = lengths_sorted[len(lengths_sorted) // 2]

    # ---- 5.1 高频词 ----
    frequent_words = [{"word": w, "count": c} for w, c in raw["word_counter"].most_common(top_n_words)]

    # ---- 5.2 口头禅：整句重复 + 惯用语 + 语气词 ----
    catchphrases = []
    seen = set()
    for text, count in raw["exact_counter"].most_common(40):
        if count >= 2 and len(text) <= 14 and text not in seen:
            catchphrases.append({"phrase": text, "count": count, "type": "常说的整句"})
            seen.add(text)
    for phrase, count in raw["interjection_counter"].most_common(top_n_phrases):
        if count >= 2 and phrase not in seen:
            catchphrases.append({"phrase": phrase, "count": count, "type": "习惯用语"})
            seen.add(phrase)
    catchphrases = sorted(catchphrases, key=lambda x: -x["count"])[:top_n_phrases]

    # ---- 5.3 标点习惯 ----
    punct = raw["punct_counter"]
    def rate(char):
        return punct.get(char, 0) / my_count
    period_rate = rate("。")
    question_rate = rate("？") + rate("?")
    exclaim_rate = rate("！") + rate("!")
    tilde_rate = rate("～") + rate("~")
    ellipsis_rate = rate("…")
    comma_rate = rate("，") + rate(",")
    no_punct_rate = 1 - raw["punct_msg_count"] / my_count

    habits = []
    habits.append("几乎不写句号" if period_rate < 0.15 else ("偶尔写句号" if period_rate < 0.4 else "习惯用句号收尾"))
    if question_rate >= 0.15:
        habits.append("爱用问号，经常反问/追问")
    if exclaim_rate >= 0.15:
        habits.append("情绪上来会用感叹号")
    if tilde_rate >= 0.1:
        habits.append("喜欢用「~」把语气放软")
    if ellipsis_rate >= 0.05:
        habits.append("会用省略号拖长语气")
    if comma_rate >= 0.2:
        habits.append("一句话里会用逗号断开")
    if no_punct_rate >= 0.5:
        habits.append(f"有 {no_punct_rate:.0%} 的消息完全不带标点")
    if not habits:
        habits.append("标点使用比较随意")

    # ---- 5.4 常用表情 ----
    common_emoji = []
    for e, c in raw["emoji_char_counter"].most_common(6):
        common_emoji.append({"emoji": e, "count": c})
    for e, c in raw["wechat_emoji_counter"].most_common(6):
        common_emoji.append({"emoji": e, "count": c})
    emoji_rate = raw["emoji_msg_count"] / my_count

    # ---- 5.5 回复长度习惯 ----
    short = sum(1 for l in lengths if l <= 6) / len(lengths)
    mid = sum(1 for l in lengths if 6 < l <= 20) / len(lengths)
    long_ = sum(1 for l in lengths if l > 20) / len(lengths)
    if short >= 0.55:
        length_style = "短句为主（基本三五个字，不啰嗦）"
    elif long_ >= 0.35:
        length_style = "偏长句（愿意把事情说明白）"
    else:
        length_style = "中等长度（一句话说完，偶尔多打几句）"

    # ---- 5.6 语气 ----
    tone, tone_reason = infer_tone(raw, cfg, relation)

    # ---- 5.7 禁忌话术 ----
    forbidden_cfg = cfg.get("forbidden") or {}
    taboo = list(forbidden_cfg.get("global") or [])
    taboo += list(forbidden_cfg.get(relation) or [])
    for word in BOOKISH_WORDS:
        used = sum(1 for ex in raw["examples"] if word in ex)
        if used == 0:
            taboo.append(word)
    taboo = list(dict.fromkeys(taboo))

    # ---- 5.8 回复示例：真实「对方->我」配对 + 我的原话 ----
    reply_examples = []
    pair_seen = set()
    for pair in raw["pairs"]:
        key = (pair["对方"], pair["我"])
        if key in pair_seen:
            continue
        pair_seen.add(key)
        reply_examples.append({"场景_对方说": pair["对方"], "我当时回": pair["我"]})
        if len(reply_examples) >= max_examples:
            break
    # 补充几条有代表性的“我的原话”（长度接近中位数）
    templates_from_me = []
    for ex in sorted(set(raw["examples"]), key=lambda t: abs(len(t) - median_len)):
        if len(templates_from_me) >= max_examples:
            break
        if len(ex) >= 2:
            templates_from_me.append(ex)

    # ---- 5.9 人设总结（自动生成一段话） ----
    top_phrase_text = "、".join(p["phrase"] for p in catchphrases[:5]) or "（暂无明显口头禅）"
    top_word_text = "、".join(w["word"] for w in frequent_words[:8]) or "（暂无）"
    emoji_text = "、".join(e["emoji"] for e in common_emoji[:5]) or "基本不用表情"
    summary = (
        f"面对「{name}」（{relation}）时，我说话{tone}：{length_style}，平均 {avg_len:.1f} 个字一条。"
        f"常用词有 {top_word_text}；口头禅是 {top_phrase_text}。"
        f"标点方面：{'；'.join(habits)}。"
        f"表情使用率约 {emoji_rate:.0%}，常用：{emoji_text}。"
    )

    persona = {
        "meta": {
            "contact": name,
            "relation": relation,
            "contact_key": contact_key,
            "source_file": source_file,
            "learned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "learn_runs": learn_runs,
            "my_message_count": raw["my_count"],
            "other_message_count": raw["other_count"],
            "word_segment": "jieba 分词" if has_jieba() else "内置降级分词（装 jieba 会更准：pip install jieba）",
        },
        "summary": summary,
        "style": {
            "tone": tone,
            "tone_reason": tone_reason,
            "avg_length": round(avg_len, 1),
            "median_length": median_len,
            "length_style": length_style,
            "length_dist": {"短(<=6字)": round(short, 3), "中(7-20字)": round(mid, 3), "长(>20字)": round(long_, 3)},
            "punctuation": {
                "句号率": round(period_rate, 3),
                "问号率": round(question_rate, 3),
                "感叹号率": round(exclaim_rate, 3),
                "波浪号率": round(tilde_rate, 3),
                "省略号率": round(ellipsis_rate, 3),
                "逗号率": round(comma_rate, 3),
                "无标点率": round(no_punct_rate, 3),
            },
            "emoji_rate": round(emoji_rate, 3),
            "question_rate": round(raw["question_count"] / my_count, 3),
        },
        "frequent_words": frequent_words,
        "catchphrases": catchphrases,
        "punctuation_habits": habits,
        "common_emoji": common_emoji,
        "reply_examples": reply_examples,
        "my_real_templates": templates_from_me,
        "taboo": taboo,
        "generation_hint": (
            f"模仿我发微信：{length_style}；语气{tone}；"
            f"多用 {top_phrase_text}；不要出现书面语和 AI 腔；"
            f"{'不要用句号' if period_rate < 0.15 else '可以用句号'}。"
        ),
        "_raw": stats_to_dict(raw),   # 原始统计，用于增量学习（不影响阅读）
    }
    return persona


# ==================================================================
# 6. 人设档案的读写
# ==================================================================
def persona_path(contact_key: str, cfg: dict = None) -> Path:
    cfg = cfg or load_config()
    return dirs_of(cfg)["persona"] / f"{contact_key}.yaml"


def load_persona(contact_key: str, cfg: dict = None) -> dict:
    """按联系人读取人设档案；找不到时给出明确报错。"""
    cfg = cfg or load_config()
    path = persona_path(contact_key, cfg)
    if not path.exists():
        # 模糊匹配：允许只写名字
        for f in sorted(dirs_of(cfg)["persona"].glob("*.yaml")):
            if f.stem.startswith("_") or f.name.startswith("_"):
                continue
            if contact_key in f.stem or f.stem.endswith(contact_key):
                return load_yaml(f)
        raise FileNotFoundError(
            f"没有找到「{contact_key}」的人设档案。请先运行：python main.py learn --contact {contact_key}"
        )
    return load_yaml(path)


def save_persona(persona: dict, cfg: dict = None) -> Path:
    cfg = cfg or load_config()
    key = persona["meta"]["contact_key"]
    path = persona_path(key, cfg)
    dump_yaml(persona, path)
    return path


def learn_contact(contact_key: str, cfg: dict = None, incremental: bool = None, verbose: bool = True) -> dict:
    """
    学习一个联系人的聊天记录：
      chat_records/<contact_key>.txt  ->  persona/<contact_key>.yaml
    incremental=True 时，会把新记录和旧档案的统计合并（用于追加聊天记录）。
    """
    cfg = cfg or load_config()
    dirs = ensure_dirs(cfg)
    incremental = cfg["learning"].get("incremental", True) if incremental is None else incremental
    chat_file = dirs["chat_records"] / f"{contact_key}.txt"
    if not chat_file.exists():
        raise FileNotFoundError(f"找不到聊天记录文件：{chat_file}")

    messages = read_chat_file(chat_file, cfg["identity"].get("me_names"))
    new_raw = extract_stats(messages, cfg)
    if new_raw["my_count"] == 0:
        raise ValueError(
            f"「{chat_file.name}」里没有识别到“我”说的话。"
            f"请检查格式（说话人: 内容），或在 config.yaml 的 me_names 里加上你的微信昵称。"
        )

    old_persona = load_yaml(persona_path(contact_key, cfg))
    learn_runs = 1
    raw = new_raw
    if incremental and old_persona.get("_raw"):
        old_raw = dict_to_stats(old_persona["_raw"])
        raw = merge_stats(old_raw, new_raw)
        learn_runs = int(old_persona.get("meta", {}).get("learn_runs", 0)) + 1

    persona = build_persona(raw, contact_key, f"chat_records/{chat_file.name}", cfg, learn_runs)
    save_persona(persona, cfg)
    if verbose:
        print(f"[学习完成] {contact_key}：我的消息 {new_raw['my_count']} 条 / 对方 {new_raw['other_count']} 条"
              f" -> {persona_path(contact_key, cfg).name}（语气：{persona['style']['tone']}，累计学习 {learn_runs} 次）")
    return persona


def learn_all(cfg: dict = None, verbose: bool = True) -> list:
    """学习 chat_records/ 下所有聊天记录。"""
    cfg = cfg or load_config()
    results = []
    for key in list_contacts(cfg):
        try:
            results.append(learn_contact(key, cfg, verbose=verbose))
        except Exception as exc:  # 单个文件出错不影响其他
            if verbose:
                print(f"[跳过] {key}：{exc}")
    if verbose and not results:
        print("chat_records/ 里还没有 txt 聊天记录，请先粘贴一份（参考示例文件）。")
    return results


# ==================================================================
# 7. 生成回复
# ==================================================================
def detect_intent(text: str, cfg: dict) -> str:
    """判断对方消息的意图（用于挑模板）。"""
    intents = cfg.get("intents") or {}
    best, best_score = "其他", 0
    for intent, keywords in intents.items():
        score = 0
        for kw in keywords or []:
            if kw and kw in text:
                score += 2 if len(kw) >= 2 else 1
        if score > best_score:
            best, best_score = intent, score
    return best


def pick_keyword(text: str) -> str:
    """从对方消息里抽一个关键词（用在模板里）。"""
    words = segment_words(text)
    if not words:
        return ""
    words.sort(key=lambda w: (-len(w), w))
    return words[0][:8]


def pick_phrase(persona: dict, rng: random.Random, source: str = "catchphrase") -> str:
    """随机取一个口头禅（source="catchphrase"）或高频词（source="word"）。"""
    if source == "word":
        words = persona.get("frequent_words") or []
        if words:
            return rng.choice(words).get("word", "")
    items = persona.get("catchphrases") or []
    if items:
        return rng.choice(items).get("phrase", "")
    words = persona.get("frequent_words") or []
    if words:
        return rng.choice(words).get("word", "")
    return ""


def apply_style(text: str, persona: dict, cfg: dict, rng: random.Random,
                flavor: str = None, add_emoji: bool = False) -> str:
    """
    按人设风格润色：
      flavor="head" 加个语气前缀（比如沙雕语气前加“哈哈哈”）
      flavor="tail" 加个语气后缀（比如温和语气后加“~”）
    """
    style = persona.get("style") or {}
    punct = style.get("punctuation") or {}
    tone = style.get("tone", "中性")
    text = text.strip()

    # 1) 我平时不写句号，就把模板里的句号去掉
    if punct.get("句号率", 0) < 0.15:
        text = text.replace("。", "" if punct.get("无标点率", 0) >= 0.5 else "，").rstrip("，")

    # 2) 按语气加语气词（前缀/后缀各挑一个候选，避免重复叠加）
    flavor_cfg = (cfg.get("tone_flavor") or {}).get(tone) or {}
    if flavor == "head" and flavor_cfg.get("head") and len(text) >= 3:
        head = rng.choice(flavor_cfg["head"])
        if not text.startswith(head.rstrip("，,")):
            text = head + text
    elif flavor == "tail" and flavor_cfg.get("tail") and len(text) <= 10:
        tail = rng.choice(flavor_cfg["tail"])
        if not text.endswith(tail.strip()):
            text = text + tail

    # 3) 有带表情习惯的话，偶尔在文字里带一个常用表情
    if add_emoji and cfg["generator"].get("use_emoji_char", True) and style.get("emoji_rate", 0) >= 0.2:
        emojis = [e.get("emoji", "") for e in (persona.get("common_emoji") or [])]
        emojis = [e for e in emojis if e]
        if emojis:
            text = text + rng.choice(emojis)

    # 4) 长度限制
    max_chars = int(cfg["generator"].get("max_chars", 60))
    if len(text) > max_chars:
        text = text[:max_chars].rstrip("，,、")

    return text


def is_taboo(text: str, persona: dict) -> bool:
    """检查是不是踩了禁忌话术。"""
    return any(word and word in text for word in (persona.get("taboo") or []))


def templates_for(intent: str, cfg: dict, tone: str = None) -> dict:
    """
    取某个意图的模板，优先级：语气专用模板 > 通用模板 > 内置兜底模板。
    这样「对同事说正式一点、对朋友随便一点」就能自动区分开。
    """
    tone_tpl = (((cfg.get("tone_templates") or {}).get(tone)) or {}).get(intent) or {}
    tpl = ((cfg.get("reply_templates") or {}).get(intent)) or {}
    fallback = FALLBACK_TEMPLATES.get(intent) or FALLBACK_TEMPLATES["其他"]
    result = {}
    for size in ("短", "中", "长"):
        options = []
        if isinstance(tone_tpl, dict):
            options = list(tone_tpl.get(size) or [])
        if not options and isinstance(tpl, dict):
            options = list(tpl.get(size) or [])
        if not options:
            options = list(fallback.get(size) or [])
        result[size] = options
    return result


def generate_replies(contact_key: str, incoming: str, cfg: dict = None,
                     n: int = None, persona: dict = None, seed: int = None) -> dict:
    """
    核心：给定「联系人 + 对方消息」，生成 2~3 条仿我口吻的回复 + 推荐表情包。
    返回字典，可直接给命令行或 Streamlit 用。
    """
    cfg = cfg or load_config()
    n = int(n or cfg["generator"].get("candidates", 3))
    persona = persona or load_persona(contact_key, cfg)
    rng = random.Random(seed) if seed is not None else random.Random()

    intent = detect_intent(incoming, cfg)
    keyword = pick_keyword(incoming)
    tone = persona.get("style", {}).get("tone", "中性")
    tpl = templates_for(intent, cfg, tone)
    sizes = ["短", "中", "长"][: max(1, min(3, n))]
    strategy_names = {"短": "简短版（像随手回一句）", "中": "自然版（最像平时的我）", "长": "详细版（愿意多说两句）"}

    engine = cfg["generator"].get("engine", "local")
    engine_used = "local"
    replies = []
    if engine == "ollama":
        try:
            replies = ollama_replies(persona, incoming, keyword, cfg, sizes)
            engine_used = "ollama"
        except Exception as exc:
            print(f"[提示] 本地 Ollama 调用失败（{exc}），自动改用本地规则引擎。")

    flavor_by_size = {"短": None, "中": "head", "长": "tail"}
    if not replies:
        used = set()
        for idx, size in enumerate(sizes):
            options = [t for t in tpl.get(size, []) if t]
            if not options:
                continue
            rng.shuffle(options)
            chosen = None
            for option in options:
                text = (option
                        .replace("{口头禅}", pick_phrase(persona, rng, source="catchphrase"))
                        .replace("{高频词}", pick_phrase(persona, rng, source="word"))
                        .replace("{关键词}", keyword)
                        .replace("{话题}", keyword)
                        .replace("{称呼}", ""))
                text = apply_style(text, persona, cfg, rng,
                                   flavor=flavor_by_size.get(size), add_emoji=(size == "中"))
                if not text or text in used or is_taboo(text, persona):
                    continue
                chosen = text
                break
            if chosen is None:
                # 模板全被过滤掉时，用我的真实原话兜底
                real = persona.get("my_real_templates") or []
                if real:
                    chosen = apply_style(rng.choice(real), persona, cfg, rng, add_emoji=(size == "长"))
            if chosen:
                used.add(chosen)
                replies.append({
                    "size": size,
                    "style": strategy_names.get(size, size),
                    "text": chosen,
                    "note": f"意图：{intent}｜语气：{persona.get('style', {}).get('tone', '中性')}",
                })

    # 万一一条都没生成出来
    if not replies:
        replies = [{"size": "中", "style": "兜底", "text": "嗯嗯", "note": f"意图：{intent}"}]

    # 表情包推荐：用「对方消息 + 我准备回的话」一起判断语义
    joined = incoming + " " + " ".join(r["text"] for r in replies)
    emojis = recommend_emoji(joined, cfg, persona=persona, n=2)

    info = parse_contact_key(contact_key, cfg)
    return {
        "contact": contact_key,
        "display": info["display"],
        "relation": info["relation"],
        "intent": intent,
        "keyword": keyword,
        "engine": engine_used,
        "tone": persona.get("style", {}).get("tone", "中性"),
        "replies": replies,
        "emoji": emojis,
    }


def ollama_replies(persona: dict, incoming: str, keyword: str, cfg: dict, sizes: list) -> list:
    """
    可选功能：调用本机 Ollama（127.0.0.1）生成更自然的回复。
    前提：你自己装了 Ollama 并 pull 了模型；不联网、不上云。
    """
    import urllib.request

    ollama_cfg = cfg["generator"].get("ollama") or {}
    examples = persona.get("reply_examples") or []
    example_text = "\n".join(f"对方：{e.get('场景_对方说','')}\n我：{e.get('我当时回','')}" for e in examples[:6])
    prompt = (
        f"你正在模仿一个真实的人发微信。下面是他的聊天人设档案：\n"
        f"{persona.get('summary','')}\n"
        f"风格要求：{persona.get('generation_hint','')}\n"
        f"绝对不要说的话：{'、'.join(persona.get('taboo') or [])}\n"
        f"他的真实聊天示例：\n{example_text}\n\n"
        f"现在对方（{persona.get('meta',{}).get('relation','')}）发来：{incoming}\n"
        f"请用他的口吻写 {len(sizes)} 条不同的回复，每行一条，不要编号，不要解释，不要书面语。"
    )
    payload = json.dumps({"model": ollama_cfg.get("model"), "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(
        f"{ollama_cfg.get('host', 'http://127.0.0.1:11434')}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=int(ollama_cfg.get("timeout", 120))) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    lines = [ln.strip(" -•\t") for ln in (data.get("response") or "").split("\n") if ln.strip()]
    replies = []
    for i, line in enumerate(lines[: len(sizes)]):
        replies.append({
            "size": sizes[i],
            "style": "本地模型版（Ollama）",
            "text": line,
            "note": "由本机 Ollama 生成",
        })
    return replies


# ==================================================================
# 8. 表情包库
# ==================================================================
def load_emoji_rows(cfg: dict = None) -> list:
    """
    读取 emoji_tag.csv，返回 [{'filename':..,'tags':[..],'path':Path}, ...]
    csv 格式（第一行表头可省略）：filename,tags
        doge.png,搞笑,狗头,无语
    """
    cfg = cfg or load_config()
    dirs = ensure_dirs(cfg)
    csv_path = dirs["emoji_tag_csv"]
    rows = []
    if not csv_path.exists():
        return rows
    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        raw_rows = [r for r in csv.reader(fh) if r and any(c.strip() for c in r)]
    if not raw_rows:
        return rows
    # 跳过表头
    first = raw_rows[0][0].strip().lower()
    if first in ("filename", "file", "文件名", "表情包", "name", "图片"):
        raw_rows = raw_rows[1:]
    for row in raw_rows:
        filename = (row[0] or "").strip()
        if not filename:
            continue
        tags = []
        for cell in row[1:]:
            for tag in split_tags(cell):
                if tag not in tags:
                    tags.append(tag)
        path = dirs["emoji_lib"] / filename
        if not path.exists():  # 兼容没写后缀名的情况
            for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                if (dirs["emoji_lib"] / (filename + ext)).exists():
                    path = dirs["emoji_lib"] / (filename + ext)
                    filename = filename + ext
                    break
        rows.append({"filename": filename, "tags": tags, "path": path, "exists": path.exists()})
    return rows


def save_emoji_rows(rows: list, cfg: dict = None) -> Path:
    """把表情包标签表写回 csv（新增表情包/标签时用）。"""
    cfg = cfg or load_config()
    csv_path = ensure_dirs(cfg)["emoji_tag_csv"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["filename", "tags"])
        for row in rows:
            writer.writerow([row["filename"], ",".join(row.get("tags") or [])])
    return csv_path


def split_tags(text) -> list:
    """把「搞笑,哈哈 无语」这类字符串拆成标签列表（支持中英文逗号、顿号、竖线、斜杠、分号、空格）。"""
    if isinstance(text, (list, tuple)):
        raw = list(text)
    else:
        raw = re.split(r"[,，、|/;；\s]+", str(text or ""))
    tags = []
    for tag in raw:
        tag = str(tag).strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def add_emoji(filename: str, tags, cfg: dict = None) -> list:
    """新增/更新一个表情包的标签。"""
    cfg = cfg or load_config()
    rows = load_emoji_rows(cfg)
    tags = split_tags(tags)
    for row in rows:
        if row["filename"] == filename:
            merged = list(dict.fromkeys(list(row["tags"]) + list(tags)))
            row["tags"] = merged
            break
    else:
        rows.append({"filename": filename, "tags": list(tags)})
    save_emoji_rows(rows, cfg)
    return rows


def recommend_emoji(text: str, cfg: dict = None, persona: dict = None, n: int = 2, min_score: float = 1.0) -> list:
    """
    根据对话语义（对方消息 + 我的回复）推荐表情包。
    打分 = 关键词命中的标签权重 + 语气加成 + 我个人常用表情加成
    """
    cfg = cfg or load_config()
    rows = load_emoji_rows(cfg)
    if not rows:
        return []

    kw_map = cfg.get("emoji_tags") or {}
    tag_scores = defaultdict(float)
    tag_reasons = defaultdict(list)
    for kw, tags in kw_map.items():
        if kw and kw in text:
            weight = 2.0 if len(kw) >= 2 else 1.0
            for tag in tags or []:
                tag_scores[tag] += weight
                if kw not in tag_reasons[tag]:
                    tag_reasons[tag].append(kw)

    # 语气加成
    tone = (persona or {}).get("style", {}).get("tone", "中性")
    for tag in (cfg.get("tone_emoji_bonus") or {}).get(tone, []) or []:
        tag_scores[tag] += 0.8
        if "语气匹配" not in tag_reasons[tag]:
            tag_reasons[tag].append("语气匹配")

    # 我平时爱用的表情/表情包加成
    my_emoji = [e.get("emoji", "") for e in ((persona or {}).get("common_emoji") or [])]

    scored = []
    for row in rows:
        if not row["tags"]:
            continue
        score = 0.0
        hit = []
        for tag in row["tags"]:
            if tag_scores.get(tag):
                score += tag_scores[tag]
                hit.append(tag)
        for me in my_emoji:
            if me and (me in row["filename"] or me in row["tags"] or me in " ".join(row["tags"])):
                score += 0.5
        if score <= 0:
            continue
        reasons = []
        for tag in hit:
            reasons.append(f"{tag}（{'/'.join(tag_reasons[tag][:3])}）")
        scored.append({
            "filename": row["filename"],
            "path": str(row["path"]),
            "tags": row["tags"],
            "score": round(score, 2),
            "reason": "匹配标签：" + "、".join(reasons) if reasons else "按语气推荐",
        })

    scored.sort(key=lambda x: (-x["score"], x["filename"]))
    result = [s for s in scored if s["score"] >= min_score][:n]
    if not result and scored:
        # 语义命中很弱时也推荐一个，但把话说清楚
        best = scored[0]
        best["reason"] = "语义匹配较弱，仅按你的语气习惯推荐（" + best["reason"] + "）"
        result = [best]
    if not result:
        # 语义没命中任何标签：按语气做一个兜底推荐
        for row in rows:
            if set(row["tags"]) & set((cfg.get("tone_emoji_bonus") or {}).get(tone, []) or []):
                return [{
                    "filename": row["filename"],
                    "path": str(row["path"]),
                    "tags": row["tags"],
                    "score": 0.5,
                    "reason": f"语义没有明显匹配，按你的「{tone}」语气兜底推荐",
                }]
    return result


# ==================================================================
# 9. 命令行界面
# ==================================================================
def print_result(result: dict) -> None:
    """在命令行里打印生成结果。"""
    print("=" * 60)
    print(f"联系人：{result['display']}　语气：{result['tone']}　意图：{result['intent']}　引擎：{result['engine']}")
    print("-" * 60)
    for i, reply in enumerate(result["replies"], 1):
        print(f"备选 {i}｜{reply['style']}")
        print(f"    {reply['text']}")
    print("-" * 60)
    if result["emoji"]:
        print("推荐表情包（手动在微信里选同名图片发送）：")
        for emo in result["emoji"]:
            print(f"    {emo['filename']}　标签：{'/'.join(emo['tags'])}　（{emo['reason']}）")
    else:
        print("推荐表情包：无（emoji_lib 里还没有可用的表情包）")
    print("=" * 60)


def cmd_learn(args) -> None:
    cfg = load_config()
    ensure_dirs(cfg)
    print(f"项目目录：{BASE_DIR}")
    if args.contact:
        learn_contact(args.contact, cfg)
    else:
        learn_all(cfg)
    print(f"人设档案目录：{dirs_of(cfg)['persona']}")


def cmd_list(args) -> None:
    cfg = load_config()
    dirs = dirs_of(cfg)
    keys = list_contacts(cfg)
    print(f"聊天记录（{dirs['chat_records']}）：")
    for key in keys:
        print(f"  - {key}.txt")
    print(f"\n已生成的人设档案（{dirs['persona']}）：")
    found = False
    for f in sorted(dirs["persona"].glob("*.yaml")):
        if f.name.startswith("_"):
            continue
        data = load_yaml(f)
        meta = data.get("meta", {})
        print(f"  - {f.stem}：{meta.get('my_message_count', '?')} 条我的消息，语气 {data.get('style', {}).get('tone', '?')}")
        found = True
    if not found:
        print("  （还没有，先运行 python main.py learn）")


def cmd_reply(args) -> None:
    cfg = load_config()
    result = generate_replies(args.contact, args.msg, cfg, n=args.n)
    print_result(result)
    if args.emoji:
        print("表情包库里的候选：")
        for row in load_emoji_rows(cfg):
            print(f"  {row['filename']}  {'/'.join(row['tags'])}")


def cmd_emoji(args) -> None:
    cfg = load_config()
    text = args.msg
    for emo in recommend_emoji(text, cfg, n=args.n):
        print(f"{emo['filename']}　标签：{'/'.join(emo['tags'])}　（{emo['reason']}）")


def cmd_interactive(args) -> None:
    cfg = load_config()
    keys = list_contacts(cfg)
    if not keys:
        print("还没有聊天记录，请先在 chat_records/ 放入 txt 文件。")
        return
    print("可用联系人：")
    for i, key in enumerate(keys, 1):
        print(f"  {i}. {parse_contact_key(key, cfg)['display']}  [{key}]")
    raw = input("请输入联系人编号或名字（直接回车 = 第一个）：").strip()
    if not raw:
        contact = keys[0]
    elif raw.isdigit() and 1 <= int(raw) <= len(keys):
        contact = keys[int(raw) - 1]
    else:
        contact = raw
    print(f"已选择：{parse_contact_key(contact, cfg)['display']}（输入 q 退出）")
    while True:
        msg = input("\n对方发来> ").strip()
        if msg.lower() in ("q", "quit", "exit"):
            break
        if not msg:
            continue
        try:
            print_result(generate_replies(contact, msg, cfg))
        except Exception as exc:
            print(f"[出错] {exc}")


def cmd_gui(args) -> None:
    print("网页版启动方式（在这个目录下执行）：")
    print("    streamlit run app.py")
    print("然后浏览器会自动打开 http://localhost:8501")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="微信聊天模仿助手（本地离线版，不接管微信）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    p_learn = sub.add_parser("learn", help="学习聊天记录，生成/更新人设档案")
    p_learn.add_argument("--contact", help="只学习某个联系人（文件名去掉 .txt）", default=None)
    p_learn.set_defaults(func=cmd_learn)

    p_list = sub.add_parser("list", help="查看聊天记录和人设档案")
    p_list.set_defaults(func=cmd_list)

    p_reply = sub.add_parser("reply", help="生成仿我口吻的回复")
    p_reply.add_argument("--contact", required=True, help="联系人（文件名去掉 .txt）")
    p_reply.add_argument("--msg", required=True, help="对方发来的消息")
    p_reply.add_argument("--n", type=int, default=None, help="生成几条备选（默认取配置）")
    p_reply.add_argument("--emoji", action="store_true", help="同时列出表情包库")
    p_reply.set_defaults(func=cmd_reply)

    p_emoji = sub.add_parser("emoji", help="只推荐表情包")
    p_emoji.add_argument("--msg", required=True, help="对话内容")
    p_emoji.add_argument("--n", type=int, default=2)
    p_emoji.set_defaults(func=cmd_emoji)

    p_inter = sub.add_parser("interactive", help="命令行交互模式")
    p_inter.set_defaults(func=cmd_interactive)

    p_gui = sub.add_parser("gui", help="提示如何启动网页版")
    p_gui.set_defaults(func=cmd_gui)
    return parser


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        print("\n常用命令：")
        print("  python main.py learn                     # 先学习聊天记录")
        print("  python main.py reply --contact 朋友_小张 --msg \"在吗\"")
        print("  streamlit run app.py                     # 打开网页版界面")
        return
    args.func(args)


if __name__ == "__main__":
    main()
