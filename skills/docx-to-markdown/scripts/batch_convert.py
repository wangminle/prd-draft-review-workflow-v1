#!/usr/bin/env python3
"""
批量将目录下的所有docx文档转换为markdown格式
每个文档生成一个同名文件夹，包含md文件和assets子文件夹
"""

import logging
import os
import signal
import sys
import glob

# 支持从同目录或作为模块导入
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

from convert_docx import (  # noqa: E402
    SENTINEL_FILENAME,
    compute_file_sha256,
    convert_docx_to_markdown,
    read_sentinel_source_sha256,
    sanitize_stem,
)

logger = logging.getLogger(__name__)


class _DocConversionTimeout(Exception):
    """单文档转换超时（signal.alarm 触发）。"""


def _alarm_handler(signum, frame):
    raise _DocConversionTimeout("单文档转换超时")


def batch_convert(source_dir, output_dir, force=False, timeout=300):
    """批量转换目录下的所有docx文件

    Args:
        source_dir: 源文件目录
        output_dir: 输出目录
        force: 为 True 时强制重新转换已存在的输出目录
        timeout: 单文档转换超时秒数（默认 300，<=0 表示不限制）。
            基于 POSIX signal.alarm 实现；Windows 无 SIGALRM 时自动跳过超时保护。
    """
    
    # 合并两种大小写扩展名并去重（macOS 大小写不敏感时 *.docx 已包含 .DOCX）
    seen = set()
    docx_files = []
    for path in glob.glob(os.path.join(source_dir, '*.docx')) + glob.glob(os.path.join(source_dir, '*.DOCX')):
        real = os.path.realpath(path)
        if real not in seen:
            seen.add(real)
            docx_files.append(path)
    
    if not docx_files:
        logger.warning("在 %s 中没有找到docx文件", source_dir)
        return
    
    logger.info("找到 %d 个docx文件待处理%s", len(docx_files),
                "（强制重新转换）" if force else "")
    
    success_count = 0
    fail_count = 0
    skip_count = 0

    os.makedirs(output_dir, exist_ok=True)
    
    for i, docx_path in enumerate(sorted(docx_files), 1):
        # 获取文件名（不含扩展名）作为输出文件夹名
        base_name = os.path.splitext(os.path.basename(docx_path))[0]
        folder_name = sanitize_stem(base_name)
        target_dir = os.path.join(output_dir, folder_name)
        md_file = os.path.join(target_dir, f"{folder_name}.md")
        sentinel = os.path.join(target_dir, SENTINEL_FILENAME)

        logger.info("[%d/%d] 正在处理: %s", i, len(docx_files), base_name)

        # 检查是否已完整转换且源文件未变更：
        # 目录 + md + sentinel 三者齐备，且 sentinel 中记录的源 SHA-256
        # 与当前源文件一致。仅检查文件存在会导致源 DOCX 变更后被误判为
        # "已完整转换"而跳过；旧格式 sentinel（纯文本 folder_name）视为无效，
        # 按半成品清理重转。--force 时跳过此检查。
        if not force and os.path.isdir(target_dir) and os.path.isfile(md_file) and os.path.isfile(sentinel):
            sentinel_hash = read_sentinel_source_sha256(sentinel)
            if sentinel_hash is not None and sentinel_hash == compute_file_sha256(docx_path):
                logger.info("  已完整转换且源文件未变更，跳过（使用 --force 强制重新转换）")
                skip_count += 1
                continue
            logger.info("  sentinel 无效或源文件已变更，重新转换")

        # 单文档超时保护（POSIX signal.alarm；Windows 无 SIGALRM，自动跳过）。
        alarm_installed = False
        old_handler = None
        if timeout and timeout > 0 and hasattr(signal, "SIGALRM"):
            try:
                old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
                signal.alarm(timeout)
                alarm_installed = True
            except (ValueError, OSError):
                # 非主线程等场景无法安装信号处理器，降级为无超时。
                alarm_installed = False
        try:
            # 清理半成品目录（sentinel 缺失/无效/源哈希不匹配）或
            # --force 时清理已有输出（等价 --force 的清理后转换）。
            needs_cleanup = force and os.path.exists(target_dir)
            if not force and os.path.isdir(target_dir):
                # 到达此处说明未被跳过，既有输出不可信，按半成品清理重转。
                needs_cleanup = True
            if needs_cleanup:
                import shutil
                if os.path.isdir(target_dir) and not os.path.islink(target_dir):
                    shutil.rmtree(target_dir)
                elif os.path.exists(target_dir):
                    os.remove(target_dir)

            convert_docx_to_markdown(docx_path, output_dir, create_subfolder=True)
            logger.info("  完成")
            success_count += 1
        except Exception as e:
            logger.error("  失败: %s", e)
            # 转换失败时清理半成品目录，避免下次被误判为已完成。
            try:
                import shutil
                if os.path.isdir(target_dir) and not os.path.islink(target_dir):
                    shutil.rmtree(target_dir)
            except Exception:
                pass
            fail_count += 1
        finally:
            if alarm_installed:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
    
    logger.info("处理完成: 成功 %d 个, 跳过 %d 个, 失败 %d 个",
                success_count, skip_count, fail_count)

if __name__ == '__main__':
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="批量将目录下的所有docx文档转换为Markdown")
    parser.add_argument("source_dir", nargs="?", default="1-Reference", help="源文件目录（默认 1-Reference）")
    parser.add_argument("output_dir", nargs="?", default="2-Temp", help="输出目录（默认 2-Temp）")
    parser.add_argument("--force", action="store_true", help="强制重新转换已存在的输出目录")
    parser.add_argument("--timeout", type=int, default=300,
                        help="单文档转换超时秒数（默认 300，<=0 不限制；仅 POSIX 生效）")
    args = parser.parse_args()

    batch_convert(args.source_dir, args.output_dir, force=args.force, timeout=args.timeout)
