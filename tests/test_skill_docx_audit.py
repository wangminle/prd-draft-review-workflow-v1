#!/usr/bin/env python3
"""P1-4.6 测试：docx-to-markdown 资源限制、原子写入与批处理跳过逻辑。

覆盖：
- MAX_IMAGE_COUNT / MAX_XLSX_SIZE 限制
- 原子写入：转换失败时不残留半成品 .md
- .converted sentinel 原子写入
- batch_convert 跳过完整目录、重试半成品目录
"""
from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path
from unittest import mock

import pytest

# 注入 scripts 路径
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "skills" / "docx-to-markdown" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import convert_docx  # noqa: E402
import batch_convert  # noqa: E402


# ───────────────────────── 辅助：构造最小合法 DOCX ─────────────────────────

def _make_minimal_docx(path: Path) -> None:
    """构造一个最小合法 DOCX（仅 word/document.xml）。"""
    document_xml = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<w:body><w:p><w:r><w:t>hello</w:t></w:r></w:p></w:body>'
        b'</w:document>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", document_xml)


def _make_docx_with_media(path: Path, image_count: int, image_size: int = 64) -> None:
    """构造一个含 N 张 media 图片的 DOCX。"""
    document_xml = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<w:body><w:p><w:r><w:t>images</w:t></w:r></w:p></w:body>'
        b'</w:document>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", document_xml)
        for i in range(image_count):
            zf.writestr(f"word/media/image{i}.png", b"\x89PNG" + b"\x00" * image_size)


def _make_docx_with_xlsx(path: Path, xlsx_size: int) -> None:
    """构造一个含超大嵌入 xlsx 的 DOCX。"""
    document_xml = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<w:body><w:p><w:r><w:t>xlsx</w:t></w:r></w:p></w:body>'
        b'</w:document>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", document_xml)
        # 写一个指定大小的假 xlsx
        zf.writestr("word/embeddings/sheet1.xlsx", b"\x00" * xlsx_size)


# ───────────────────────── 资源限制 ─────────────────────────

class TestResourceLimits:
    def test_max_image_count_constant(self):
        assert convert_docx.MAX_IMAGE_COUNT == 500

    def test_max_xlsx_size_constant(self):
        assert convert_docx.MAX_XLSX_SIZE == 50 * 1024 * 1024

    def test_extract_content_skips_oversized_xlsx(self, tmp_path):
        """超大 xlsx 应被跳过，不抛异常。"""
        docx_path = tmp_path / "big.xlsx.docx"
        # xlsx 大小超过 MAX_XLSX_SIZE
        _make_docx_with_xlsx(docx_path, convert_docx.MAX_XLSX_SIZE + 1024)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        # 应正常返回（不抛异常），且 excel_md 为空
        img_by_hash, tbl_queue, tbl_repeat = convert_docx.extract_content_from_docx(
            str(docx_path), str(assets_dir)
        )
        assert len(tbl_queue) == 0
        assert len(tbl_repeat) == 0

    def test_extract_content_image_count_limit(self, tmp_path):
        """图片数量超过 MAX_IMAGE_COUNT 时应停止提取。"""
        # 用 mock 把上限调低以便测试
        with mock.patch.object(convert_docx, "MAX_IMAGE_COUNT", 3):
            docx_path = tmp_path / "many.docx"
            _make_docx_with_media(docx_path, image_count=10)
            assets_dir = tmp_path / "assets"
            assets_dir.mkdir()
            img_by_hash, _, _ = convert_docx.extract_content_from_docx(
                str(docx_path), str(assets_dir)
            )
            # 只能提取前 3 张
            assert len(img_by_hash) <= 3


# ───────────────────────── 原子写入 ─────────────────────────

class TestAtomicWrite:
    def test_successful_conversion_writes_md_and_sentinel(self, tmp_path):
        docx_path = tmp_path / "ok.docx"
        _make_minimal_docx(docx_path)
        out_dir = tmp_path / "out"

        md_path = convert_docx.convert_docx_to_markdown(str(docx_path), str(out_dir))

        assert os.path.isfile(md_path)
        # 子目录名 = sanitize_stem("ok") = "ok"
        sentinel = Path(out_dir) / "ok" / ".converted"
        assert sentinel.is_file()

    def test_failed_conversion_no_half_md(self, tmp_path):
        """转换中途抛异常时，目标 .md 不应残留半成品。"""
        docx_path = tmp_path / "fail.docx"
        _make_minimal_docx(docx_path)
        out_dir = tmp_path / "out"

        # 模拟 mammoth.convert_to_html 抛异常
        def _raise(*a, **kw):
            raise RuntimeError("simulated mammoth failure")

        with mock.patch("mammoth.convert_to_html", side_effect=_raise):
            with pytest.raises(RuntimeError):
                convert_docx.convert_docx_to_markdown(str(docx_path), str(out_dir))

        folder = convert_docx.sanitize_stem("fail")
        target_dir = Path(out_dir) / folder
        md_file = target_dir / f"{folder}.md"
        sentinel = target_dir / ".converted"

        # 关键断言：md 和 sentinel 都不应存在（原子写入保证）
        assert not md_file.exists()
        assert not sentinel.exists()
        # 也不应残留 .tmp 文件
        tmps = list(target_dir.glob("*.tmp")) if target_dir.exists() else []
        assert len(tmps) == 0

    def test_no_tmp_residual_on_success(self, tmp_path):
        docx_path = tmp_path / "clean.docx"
        _make_minimal_docx(docx_path)
        out_dir = tmp_path / "out"

        convert_docx.convert_docx_to_markdown(str(docx_path), str(out_dir))

        folder = convert_docx.sanitize_stem("clean")
        target_dir = Path(out_dir) / folder
        tmps = list(target_dir.glob("*.tmp"))
        assert len(tmps) == 0


# ───────────────────────── batch_convert 跳过逻辑 ─────────────────────────

class TestBatchConvertSkip:
    def test_skips_complete_output(self, tmp_path):
        """完整转换过的目录（有 md + sentinel）应被跳过。"""
        src = tmp_path / "src"
        src.mkdir()
        docx_path = src / "a.docx"
        _make_minimal_docx(docx_path)

        out = tmp_path / "out"
        # 预先模拟完整转换结果
        folder = convert_docx.sanitize_stem("a")
        target = out / folder
        target.mkdir(parents=True)
        (target / f"{folder}.md").write_text("# existing")
        (target / ".converted").write_text(folder)

        batch_convert.batch_convert(str(src), str(out), force=False)
        # 已存在的 md 不应被覆盖
        assert (target / f"{folder}.md").read_text() == "# existing"

    def test_retries_incomplete_output(self, tmp_path):
        """半成品目录（无 sentinel）应被清理并重新转换。"""
        src = tmp_path / "src"
        src.mkdir()
        docx_path = src / "b.docx"
        _make_minimal_docx(docx_path)

        out = tmp_path / "out"
        folder = convert_docx.sanitize_stem("b")
        target = out / folder
        target.mkdir(parents=True)
        # 写一个半成品 md（无 sentinel）
        (target / f"{folder}.md").write_text("# half-baked incomplete")
        # 不写 .converted

        batch_convert.batch_convert(str(src), str(out), force=False)

        # 应被重新转换：md 内容应不再是半成品
        md_content = (target / f"{folder}.md").read_text()
        assert md_content != "# half-baked incomplete"
        assert (target / ".converted").is_file()

    def test_force_reconverts_complete_output(self, tmp_path):
        """--force 时应重新转换完整目录。"""
        src = tmp_path / "src"
        src.mkdir()
        docx_path = src / "c.docx"
        _make_minimal_docx(docx_path)

        out = tmp_path / "out"
        folder = convert_docx.sanitize_stem("c")
        target = out / folder
        target.mkdir(parents=True)
        (target / f"{folder}.md").write_text("# old")
        (target / ".converted").write_text(folder)

        batch_convert.batch_convert(str(src), str(out), force=True)

        md_content = (target / f"{folder}.md").read_text()
        assert md_content != "# old"

    def test_failed_conversion_cleans_halfproduct(self, tmp_path):
        """转换失败时应清理半成品目录，避免下次误判为已完成。"""
        src = tmp_path / "src"
        src.mkdir()
        docx_path = src / "bad.docx"
        _make_minimal_docx(docx_path)

        out = tmp_path / "out"

        def _raise(*a, **kw):
            raise RuntimeError("simulated failure")

        with mock.patch("mammoth.convert_to_html", side_effect=_raise):
            batch_convert.batch_convert(str(src), str(out), force=False)

        folder = convert_docx.sanitize_stem("bad")
        target = out / folder
        # 失败后目录应被清理
        assert not target.exists() or not (target / ".converted").exists()
