#!/usr/bin/env python3
"""P1-4.6 测试：docx-to-markdown 资源限制、原子写入与批处理跳过逻辑。

适配 skill 上游 V0.1.7（93afbb1）API：资源上限集中为 DOCX_SECURITY_LIMITS
dict、ZIP 安全校验为 validate_docx_zip_security(zip_ref)（接收已打开的
ZipFile）、sentinel 读写为 write/read_conversion_sentinel、文件哈希为
sha256_file。上游自有测试套件（tests/test_docx_*.py）覆盖 V0.1.7 全量
行为；本文件保留本项目历史回归关注点。

覆盖：
- DOCX_SECURITY_LIMITS 各项阈值
- 原子写入：转换失败时不残留半成品 .md
- .converted sentinel 原子写入（JSON，绑定源文件 SHA-256 与 on_limit）
- batch_convert 跳过完整目录、重试半成品目录
- BUG-160：源哈希不匹配/旧格式 sentinel 重转、ZIP 总压缩比检查、图片像素上限
"""
from __future__ import annotations

import json
import os
import struct
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

def _make_minimal_docx(path: Path, text: bytes = b"hello") -> None:
    """构造一个最小合法 DOCX（仅 word/document.xml）。"""
    document_xml = (
        b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<w:body><w:p><w:r><w:t>' + text + b'</w:t></w:r></w:p></w:body>'
        b'</w:document>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", document_xml)


def _write_valid_sentinel(target: Path, folder: str, docx_path: Path) -> None:
    """写入新格式（JSON + 源哈希 + on_limit）的合法 sentinel。"""
    payload = json.dumps({
        "folder_name": folder,
        "source_sha256": convert_docx.sha256_file(str(docx_path)),
        "on_limit": "reject",
    }, ensure_ascii=False)
    (target / ".converted").write_text(payload, encoding="utf-8")


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
    def test_security_limits_dict(self):
        limits = convert_docx.DOCX_SECURITY_LIMITS
        assert limits["image_count"] == 500
        assert limits["embedded_excel_size"] == 50 * 1024 * 1024
        assert limits["image_file_size"] == 20 * 1024 * 1024
        assert limits["image_pixels"] == 50_000_000
        assert limits["entry_uncompressed"] == 100 * 1024 * 1024
        assert limits["total_uncompressed"] == 500 * 1024 * 1024

    def test_extract_content_skips_oversized_xlsx(self, tmp_path):
        """超大 xlsx 应被跳过，不抛异常。"""
        docx_path = tmp_path / "big.xlsx.docx"
        # xlsx 大小超过 embedded_excel_size
        _make_docx_with_xlsx(docx_path, convert_docx.DOCX_SECURITY_LIMITS["embedded_excel_size"] + 1024)
        assets_dir = tmp_path / "assets"
        assets_dir.mkdir()
        # 应正常返回（不抛异常），且 excel_md 为空
        img_by_hash, tbl_queue, tbl_repeat = convert_docx.extract_content_from_docx(
            str(docx_path), str(assets_dir), on_limit="skip"
        )
        assert len(tbl_queue) == 0
        assert len(tbl_repeat) == 0

    def test_extract_content_image_count_limit(self, tmp_path):
        """图片数量超过 image_count 时应停止提取。"""
        # 用 mock 把上限调低以便测试
        with mock.patch.dict(convert_docx.DOCX_SECURITY_LIMITS, {"image_count": 3}):
            docx_path = tmp_path / "many.docx"
            _make_docx_with_media(docx_path, image_count=10)
            assets_dir = tmp_path / "assets"
            assets_dir.mkdir()
            img_by_hash, _, _ = convert_docx.extract_content_from_docx(
                str(docx_path), str(assets_dir), on_limit="skip"
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
        """完整转换过的目录（md + 有效 sentinel 且源哈希一致）应被跳过。"""
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
        _write_valid_sentinel(target, folder, docx_path)

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

    def test_on_limit_mismatch_reconverts(self, tmp_path):
        """sentinel 记录的 on_limit 与本次请求不一致时应重转。"""
        src = tmp_path / "src"
        src.mkdir()
        docx_path = src / "policy.docx"
        _make_minimal_docx(docx_path)

        out = tmp_path / "out"
        folder = convert_docx.sanitize_stem("policy")
        target = out / folder
        target.mkdir(parents=True)
        (target / f"{folder}.md").write_text("# reject-mode marker")
        # sentinel 哈希一致但 on_limit 为 reject，本次以 skip 运行
        payload = json.dumps({
            "folder_name": folder,
            "source_sha256": convert_docx.sha256_file(str(docx_path)),
            "on_limit": "reject",
        }, ensure_ascii=False)
        (target / ".converted").write_text(payload, encoding="utf-8")

        batch_convert.batch_convert(str(src), str(out), force=False, on_limit="skip")

        # 策略不一致 → 不跳过，重新转换
        md_content = (target / f"{folder}.md").read_text()
        assert md_content != "# reject-mode marker"
        new_sentinel = json.loads((target / ".converted").read_text(encoding="utf-8"))
        assert new_sentinel["on_limit"] == "skip"


# ───────────────────────── BUG-160：sentinel 绑定源哈希 ─────────────────────────

class TestSentinelSourceHash:
    def test_sentinel_records_source_hash(self, tmp_path):
        """转换成功后 sentinel 应为 JSON，且记录源文件 SHA-256。"""
        docx_path = tmp_path / "h.docx"
        _make_minimal_docx(docx_path)
        out_dir = tmp_path / "out"

        convert_docx.convert_docx_to_markdown(str(docx_path), str(out_dir))

        sentinel = Path(out_dir) / "h" / ".converted"
        payload = json.loads(sentinel.read_text(encoding="utf-8"))
        assert payload["folder_name"] == "h"
        assert payload["source_sha256"] == convert_docx.sha256_file(str(docx_path))
        assert payload["on_limit"] == "reject"

    def test_read_sentinel_legacy_returns_none(self, tmp_path):
        """旧格式 sentinel（纯文本 folder_name）应被判定为无效。"""
        sentinel_dir = tmp_path
        (sentinel_dir / ".converted").write_text("legacy-folder", encoding="utf-8")
        assert convert_docx.read_conversion_sentinel(str(sentinel_dir)) is None

    def test_read_sentinel_corrupt_returns_none(self, tmp_path):
        """损坏 JSON 或缺少哈希字段的 sentinel 应被判定为无效。"""
        sentinel_dir = tmp_path
        (sentinel_dir / ".converted").write_text("{not json", encoding="utf-8")
        assert convert_docx.read_conversion_sentinel(str(sentinel_dir)) is None
        (sentinel_dir / ".converted").write_text(json.dumps({"folder_name": "x"}), encoding="utf-8")
        assert convert_docx.read_conversion_sentinel(str(sentinel_dir)) is None

    def test_read_sentinel_invalid_on_limit_returns_none(self, tmp_path):
        """on_limit 非法（不在 reject/skip 枚举内）的 sentinel 应判定无效。"""
        payload = json.dumps({
            "folder_name": "x",
            "source_sha256": "0" * 64,
            "on_limit": "ignore",
        })
        (tmp_path / ".converted").write_text(payload, encoding="utf-8")
        assert convert_docx.read_conversion_sentinel(str(tmp_path)) is None

    def test_read_sentinel_valid_returns_dict(self, tmp_path):
        """合法 sentinel 应返回含三项字段的 dict。"""
        payload = json.dumps({
            "folder_name": "x",
            "source_sha256": "0" * 64,
            "on_limit": "skip",
        })
        (tmp_path / ".converted").write_text(payload, encoding="utf-8")
        result = convert_docx.read_conversion_sentinel(str(tmp_path))
        assert result == {"folder_name": "x", "source_sha256": "0" * 64, "on_limit": "skip"}

    def test_hash_mismatch_reconverts(self, tmp_path):
        """源文件变更导致 sentinel 哈希不匹配时，应清理重转而非跳过。"""
        src = tmp_path / "src"
        src.mkdir()
        docx_path = src / "d.docx"
        _make_minimal_docx(docx_path, text=b"original")

        out = tmp_path / "out"
        batch_convert.batch_convert(str(src), str(out), force=False)

        folder = convert_docx.sanitize_stem("d")
        target = out / folder
        md_file = target / f"{folder}.md"
        first_md = md_file.read_text()

        # 修改源 DOCX 内容（源哈希随之变化）
        _make_minimal_docx(docx_path, text=b"changed content")

        batch_convert.batch_convert(str(src), str(out), force=False)

        # 应重转：md 内容更新，sentinel 中哈希绑定到新源文件
        new_md = md_file.read_text()
        assert new_md != first_md
        assert "changed content" in new_md
        payload = json.loads((target / ".converted").read_text(encoding="utf-8"))
        assert payload["source_sha256"] == convert_docx.sha256_file(str(docx_path))

    def test_unchanged_source_skips_after_real_conversion(self, tmp_path):
        """真实转换后重跑，源未变更应跳过（md 不被重写）。"""
        src = tmp_path / "src"
        src.mkdir()
        docx_path = src / "u.docx"
        _make_minimal_docx(docx_path)

        out = tmp_path / "out"
        batch_convert.batch_convert(str(src), str(out), force=False)

        folder = convert_docx.sanitize_stem("u")
        md_file = out / folder / f"{folder}.md"
        md_file.write_text("# tampered marker")

        batch_convert.batch_convert(str(src), str(out), force=False)
        # 哈希一致 → 跳过，marker 保留
        assert md_file.read_text() == "# tampered marker"

    def test_legacy_sentinel_treated_as_incomplete(self, tmp_path):
        """旧格式 sentinel（纯文本）应按半成品清理并重新转换。"""
        src = tmp_path / "src"
        src.mkdir()
        docx_path = src / "e.docx"
        _make_minimal_docx(docx_path)

        out = tmp_path / "out"
        folder = convert_docx.sanitize_stem("e")
        target = out / folder
        target.mkdir(parents=True)
        (target / f"{folder}.md").write_text("# old-format marker")
        (target / ".converted").write_text(folder)  # 旧格式纯文本

        batch_convert.batch_convert(str(src), str(out), force=False)

        md = (target / f"{folder}.md").read_text()
        assert md != "# old-format marker"
        payload = json.loads((target / ".converted").read_text(encoding="utf-8"))
        assert payload["source_sha256"] == convert_docx.sha256_file(str(docx_path))

    def test_timeout_parameter_accepted(self, tmp_path):
        """timeout 参数应可用且不干扰正常转换（非 POSIX 平台自动跳过）。"""
        src = tmp_path / "src"
        src.mkdir()
        docx_path = src / "t.docx"
        _make_minimal_docx(docx_path)

        out = tmp_path / "out"
        batch_convert.batch_convert(str(src), str(out), force=False, timeout=60)
        assert (out / "t" / ".converted").is_file()


# ───────────────────────── BUG-160：ZIP 总压缩比 ─────────────────────────

class TestTotalCompressionRatio:
    def test_total_compression_ratio_rejected(self, tmp_path):
        """单 entry 均低于阈值但总压缩比超限时，仍应拒绝。"""
        docx_path = tmp_path / "bomb.docx"
        document_xml = (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b'<w:body><w:p><w:r><w:t>' + b"x" * 100_000 + b'</w:t></w:r></w:p></w:body>'
            b'</w:document>'
        )
        with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("word/document.xml", document_xml)
            zf.writestr("word/media/pad.bin", b"\x00" * 100_000)

        # 调高单 entry 阈值以隔离总压缩比检查路径
        with mock.patch.dict(convert_docx.DOCX_SECURITY_LIMITS, {
            "entry_ratio": 10**9,
            "total_ratio_min_compressed": 1,
            "total_ratio": 10,
        }):
            with zipfile.ZipFile(docx_path, "r") as zf:
                with pytest.raises(convert_docx.DocxSecurityError, match="总压缩比"):
                    convert_docx.validate_docx_zip_security(zf)

    def test_total_ratio_check_skips_small_archives(self, tmp_path):
        """总压缩体积低于 1MB 时不触发总压缩比检查（避免小文件误伤）。"""
        docx_path = tmp_path / "small.docx"
        document_xml = (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            b'<w:body><w:p><w:r><w:t>small</w:t></w:r></w:p></w:body>'
            b'</w:document>'
        )
        with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("word/document.xml", document_xml)
            # 高压缩比但体积小的 entry（压缩后远小于 1MB）
            zf.writestr("word/media/pad.bin", b"\x00" * 50_000)

        with mock.patch.dict(convert_docx.DOCX_SECURITY_LIMITS, {"entry_ratio": 10**9}):
            # 不抛异常：总压缩体积未达 1MB 阈值
            with zipfile.ZipFile(docx_path, "r") as zf:
                convert_docx.validate_docx_zip_security(zf)


# ───────────────────────── BUG-160：图片像素上限（decompression bomb）─────────────────────────

class TestImagePixelLimit:
    @staticmethod
    def _png_with_dimensions(width: int, height: int) -> bytes:
        """构造含合法 IHDR 的 PNG 头（不解压像素数据）。"""
        return (
            b"\x89PNG\r\n\x1a\n"        # PNG 签名（bytes 0-7）
            + b"\x00\x00\x00\x0d"       # IHDR chunk 长度（bytes 8-11）
            + b"IHDR"                    # IHDR 类型（bytes 12-15）
            + struct.pack(">II", width, height)  # 宽高（bytes 16-23）
            + b"\x00" * 8
        )

    def test_oversized_pixel_image_rejected(self):
        """声明超大尺寸的图片（解压炸弹型）像素数应超上限。"""
        # 20000x20000 = 4 亿像素 > image_pixels
        png = self._png_with_dimensions(20000, 20000)
        pixels = convert_docx.image_pixel_count(png)
        assert pixels == 20000 * 20000
        assert pixels > convert_docx.DOCX_SECURITY_LIMITS["image_pixels"]

    def test_normal_pixel_image_accepted(self):
        """正常尺寸图片像素数不应超上限。"""
        png = self._png_with_dimensions(100, 100)
        pixels = convert_docx.image_pixel_count(png)
        assert pixels == 100 * 100
        assert pixels <= convert_docx.DOCX_SECURITY_LIMITS["image_pixels"]

    def test_malformed_header_returns_none(self):
        """无法解析头部的图片返回 None（不拦截，交由大小限制兜底）。"""
        assert convert_docx.image_pixel_count(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8) is None
        assert convert_docx.image_pixel_count(b"UNKNOWN FORMAT") is None
