"""POC-A 全流程运行器 — 依次执行 POC-A.1~A.6。

使用方式：
  python poc-a/scripts/run_all.py [--skip-install] [--skip-lancedb] [--skip-milvus] [--skip-chroma]
"""

import subprocess
import sys
import time
import json
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
RESULTS_DIR = SCRIPTS_DIR.parent / "results"
REPORTS_DIR = SCRIPTS_DIR.parent / "reports"

POC_DEPS = {
    "lancedb": ["lancedb", "pyarrow"],
    "milvus_lite": ["pymilvus"],
    "chroma": ["chromadb"],
}


def pip_install(package: str):
    """安装 Python 包。"""
    print(f"  安装 {package}...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", package, "--quiet"],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        print(f"  ⚠️ {package} 安装失败: {result.stderr}")
        return False
    print(f"  ✅ {package} 已安装")
    return True


def check_sample_files():
    """检查样例文件是否已生成。"""
    prds = list((SCRIPTS_DIR.parent / "samples" / "prds").glob("*.md"))
    norms = list((SCRIPTS_DIR.parent / "samples" / "norms").glob("*.md"))
    reports = list((SCRIPTS_DIR.parent / "samples" / "reports").glob("*.md"))
    print(f"  PRD: {len(prds)} 份, 规范: {len(norms)} 份, 评审报告: {len(reports)} 份")
    return len(prds) >= 20 and len(norms) >= 5 and len(reports) >= 5


def run_step(name: str, script: str, skip: bool = False) -> bool:
    """运行一个 POC 步骤。"""
    if skip:
        print(f"  ⏭️ 跳过 {name}")
        return True

    print(f"\n{'='*60}")
    print(f"  运行: {name}")
    print(f"{'='*60}")

    script_path = SCRIPTS_DIR / script
    if not script_path.exists():
        print(f"  ⚠️ 脚本不存在: {script_path}")
        return False

    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True, text=True, timeout=300,
    )
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        # 过滤掉 Python 警告
        for line in result.stderr.split('\n'):
            if line and not line.startswith(("UserWarning", "FutureWarning", "DeprecationWarning")):
                print(f"  stderr: {line}")

    if result.returncode != 0:
        print(f"  ❌ {name} 失败 (exit code {result.returncode})")
        return False

    print(f"  ✅ {name} 完成")
    return True


def main():
    args = sys.argv[1:]
    skip_install = "--skip-install" in args
    skip_lancedb = "--skip-lancedb" in args
    skip_milvus = "--skip-milvus" in args
    skip_chroma = "--skip-chroma" in args

    print("POC-A 全流程运行器")
    print("=" * 60)

    # Step 0: 安装依赖
    if not skip_install:
        print("\n[Step 0] 安装 POC 依赖...")
        for poc_name, packages in POC_DEPS.items():
            skip_flag = {
                "lancedb": skip_lancedb,
                "milvus_lite": skip_milvus,
                "chroma": skip_chroma,
            }.get(poc_name, False)
            if skip_flag:
                continue
            for pkg in packages:
                pip_install(pkg)

    # Step 1: 检查样例文件
    print("\n[Step 1] 检查样例文件...")
    if not check_sample_files():
        print("  ⚠️ 样例文件不完整，需要先生成文档")
        print("  请先运行样例生成脚本或手动创建文档")
        return

    # Step 2: FTS5 baseline
    fts5_ok = run_step("POC-A.2: FTS5 baseline", "run_fts5.py")

    # Step 3: LanceDB
    lancedb_ok = run_step("POC-A.3: LanceDB", "run_lancedb.py", skip=skip_lancedb or not fts5_ok)

    # Step 4: Milvus Lite
    milvus_ok = run_step("POC-A.4: Milvus Lite", "run_milvus_lite.py", skip=skip_milvus or not fts5_ok)

    # Step 5: Chroma
    chroma_ok = run_step("POC-A.5: Chroma", "run_chroma.py", skip=skip_chroma or not fts5_ok)

    # Step 6: 对比报告
    run_step("POC-A.6: 对比报告", "run_comparison.py",
             skip=not (lancedb_ok or milvus_ok or chroma_ok))

    print("\n" + "=" * 60)
    print("POC-A 全流程完成")
    print(f"  FTS5: {'✅' if fts5_ok else '❌'}")
    print(f"  LanceDB: {'✅' if lancedb_ok else '⏭️/❌'}")
    print(f"  Milvus Lite: {'✅' if milvus_ok else '⏭️/❌'}")
    print(f"  Chroma: {'✅' if chroma_ok else '⏭️/❌'}")
    print(f"  对比报告: 见 {REPORTS_DIR / 'POC-A-对比报告.md'}")
    print("=" * 60)


if __name__ == "__main__":
    main()