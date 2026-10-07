# -*- coding: utf-8 -*-
"""
打包一份「可以安全分享给别人 / 上传 GitHub」的干净副本。

用法（在项目根目录执行）：
    python make_share_zip.py              # 干净版：只保留 3 份虚构示例，去掉你的真实数据
    python make_share_zip.py --full       # 完整版：连你的聊天记录和人设一起打包（只适合自己备份／私密仓库）
    python make_share_zip.py --keep-persona   # 干净版，但保留已生成的人设档案（示例人设没隐私）

产物：
    share_output/wechat_assistant/        # 干净的文件夹副本
    wechat_assistant_share.zip            # 可以直接发给别人的压缩包

只用 Python 标准库，不需要装任何依赖。
"""

from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SHARE_DIR = BASE_DIR / "share_output"
ZIP_PATH = BASE_DIR / "wechat_assistant_share.zip"

# 这三份是我编的示例素材，可以公开
SAMPLE_CHAT_FILES = {"朋友_小张.txt", "家人_妈妈.txt", "同事_李工.txt"}

# 这些目录/文件不参与打包
SKIP_NAMES = {
    ".git", ".idea", ".vscode", ".venv", "venv", "env", ".pylibs",
    "__pycache__", ".pytest_cache", ".mypy_cache", "share_output",
}
SKIP_SUFFIX = {".pyc", ".pyo", ".zip", ".log"}


def should_skip_dir(name: str) -> bool:
    """运行产生的垃圾目录 / 临时目录一律跳过。"""
    return name in SKIP_NAMES or name.startswith(".dsh_") or name.startswith(".dsh")


def collect_plan(full: bool, keep_persona: bool) -> tuple:
    """
    返回 (要打包的文件列表, 被跳过的文件列表)。
    干净版规则：
      chat_records/  只留 3 份示例 txt
      persona/       只留 _template.yaml（除非 --keep-persona）
    """
    included, skipped = [], []
    for path in sorted(BASE_DIR.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(BASE_DIR)
        parts = rel.parts

        # 目录级跳过
        if any(should_skip_dir(p) for p in parts[:-1]):
            continue
        # 文件级跳过
        if path.name in SKIP_NAMES or path.suffix.lower() in SKIP_SUFFIX:
            continue
        if path.name == Path(__file__).name:            # 打包脚本本身不进副本
            continue

        # ---- 隐私过滤 ----
        if len(parts) == 2 and parts[0] == "chat_records":
            if not full and path.name not in SAMPLE_CHAT_FILES:
                skipped.append(rel)
                continue
        if len(parts) == 2 and parts[0] == "persona" and path.name != "_template.yaml":
            if not full and not keep_persona:
                skipped.append(rel)
                continue

        included.append(rel)
    return included, skipped


def build(full: bool, keep_persona: bool) -> None:
    included, skipped = collect_plan(full, keep_persona)

    # 1) 清掉上一次的产物，重新复制
    if SHARE_DIR.exists():
        shutil.rmtree(SHARE_DIR)
    target_root = SHARE_DIR / BASE_DIR.name
    target_root.mkdir(parents=True)

    for rel in included:
        dst = target_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BASE_DIR / rel, dst)

    # 2) 打包成 zip
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(target_root.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(SHARE_DIR))

    # 3) 打印结果
    print("=" * 62)
    print(f"模式：{'完整版（含你的真实数据，别公开）' if full else '干净分享版'}")
    print(f"打包了 {len(included)} 个文件 -> {ZIP_PATH}")
    print(f"目录副本 -> {target_root}")
    print("-" * 62)
    print("包含：")
    for rel in included:
        print(f"  + {rel}")
    if skipped:
        print("已剔除（你的私人数据）：")
        for rel in skipped:
            print(f"  - {rel}")
    print("-" * 62)
    print("提示：")
    print("  1. 上传前再确认一遍 config.yaml 的 contacts 段没写真人名字")
    print("  2. 表情包里如果换成了从微信导出的真实图片，考虑删掉再分享")
    print("  3. 别人拿到 zip 后：pip install -r requirements.txt -> python main.py learn -> streamlit run app.py")
    print("=" * 62)


def main() -> None:
    parser = argparse.ArgumentParser(description="打包一份可以安全分享的副本")
    parser.add_argument("--full", action="store_true", help="连私人聊天记录和人设一起打包（自己备份用）")
    parser.add_argument("--keep-persona", action="store_true", help="保留已生成的人设档案")
    args = parser.parse_args()
    build(args.full, args.keep_persona)


if __name__ == "__main__":
    main()
