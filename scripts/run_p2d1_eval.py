"""P2.D.1 检索评估脚本：用 POC 样例集跑真实 OpenAI embedding 的命中率和拒答率。

验收标准：
- top-5 命中率 ≥ 80%（最低门槛）；使用真实 OpenAI embedding 时预期 ≥ 92%
- no_answer 拒答率 ≥ 50%（校准 P2.E.3 的分数差阈值）
- 无越权召回

用法：
    python scripts/run_p2d1_eval.py [--api-key PATH] [--output-dir DIR]

环境变量：
    OPENAI_API_KEY — OpenAI API Key（优先于 --api-key 参数）
    RUNTIME_ROOT   — 运行时根目录（默认：项目根目录/runtime）

评估数据：
    - 30 份 POC-A 合成样例文档（20 PRD + 5 规范 + 5 报告）
    - 84 个自动生成问题（title_find + section_find）
    - 20 条 POC-C 手写补充问题（8 语义匹配 + 4 跨文档 + 8 无答案）
    - 总计 104 个问题
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── 项目路径 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
POC_SAMPLES_DIR = PROJECT_ROOT / "poc-a" / "samples"
sys.path.insert(0, str(SRC_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("p2d1_eval")


# ── 评估数据模型 ──

@dataclass
class EvalQuestion:
    """评估问题。"""
    qid: str
    query: str
    expect_source_titles: list[str]  # 期望命中的文档标题关键词
    category: str  # title_find / section_find / semantic_match / cross_doc / no_answer
    workspace_id: int = 1  # 默认 workspace


@dataclass
class EvalResult:
    """单条问题的检索结果。"""
    qid: str
    query: str
    category: str
    expect_source_titles: list[str]
    returned_source_ids: list[int]
    returned_source_titles: list[str]
    top1_hit: bool
    top5_hit: bool
    no_answer_correct: bool | None  # None = 非 no_answer 问题
    latency_ms: float
    confidence_top1: str
    rejected_top1: bool
    dist_top1: float
    gap_top1_top2: float | None
    fallback_reason: str | None


@dataclass
class EvalSummary:
    """评估汇总。"""
    total_questions: int
    top5_hit_rate: float
    top1_hit_rate: float
    no_answer_rejection_rate: float
    no_answer_total: int
    no_answer_rejected: int
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    category_rates: dict[str, dict[str, float]]
    permission_violations: int
    passed: bool  # 是否通过验收标准
    pass_reasons: list[str]


# ── 补充问题集（来自 POC-C）──

SUPPLEMENTAL_QUESTIONS = [
    {"qid": "SQ-001", "query": "哪个需求涉及用户权限控制和角色管理",
     "expect_keywords": ["权限", "角色", "认证", "安全"], "category": "semantic_match"},
    {"qid": "SQ-002", "query": "数据导出和报表功能的需求有哪些",
     "expect_keywords": ["数据导出", "报表", "导出"], "category": "semantic_match"},
    {"qid": "SQ-003", "query": "消息通知和提醒机制是怎么设计的",
     "expect_keywords": ["消息", "通知", "提醒"], "category": "semantic_match"},
    {"qid": "SQ-004", "query": "品牌个性化和界面配置能力",
     "expect_keywords": ["品牌", "界面", "配置", "个性化"], "category": "semantic_match"},
    {"qid": "SQ-005", "query": "知识库资料的检索和引用功能",
     "expect_keywords": ["知识库", "检索", "引用", "RAG"], "category": "semantic_match"},
    {"qid": "SQ-006", "query": "审查流程的自动化和 AI 辅助能力",
     "expect_keywords": ["审查", "AI", "自动", "审查模式"], "category": "semantic_match"},
    {"qid": "SQ-007", "query": "团队成员的管理和权限分配方案",
     "expect_keywords": ["团队", "成员", "权限", "角色"], "category": "semantic_match"},
    {"qid": "SQ-008", "query": "模型的思考过程展示和参数配置",
     "expect_keywords": ["模型", "思考", "参数"], "category": "semantic_match"},
    {"qid": "SQ-009", "query": "哪些需求提到了安全认证和鉴权",
     "expect_keywords": ["安全", "认证", "鉴权"], "category": "cross_doc"},
    {"qid": "SQ-010", "query": "哪些功能需要后台管理配置",
     "expect_keywords": ["后台", "管理", "配置"], "category": "cross_doc"},
    {"qid": "SQ-011", "query": "涉及文档解析和处理的需求有哪些",
     "expect_keywords": ["文档", "解析", "处理", "Markdown"], "category": "cross_doc"},
    {"qid": "SQ-012", "query": "哪些需求涉及 Markdown 或图表渲染",
     "expect_keywords": ["Markdown", "图表", "渲染", "Mermaid"], "category": "cross_doc"},
    {"qid": "SQ-013", "query": "区块链积分结算规则是什么", "expect_keywords": [], "category": "no_answer"},
    {"qid": "SQ-014", "query": "海外税务发票自动报销流程是什么", "expect_keywords": [], "category": "no_answer"},
    {"qid": "SQ-015", "query": "员工绩效薪酬审批怎么配置", "expect_keywords": [], "category": "no_answer"},
    {"qid": "SQ-016", "query": "供应链仓储机器人路径规划方案是什么", "expect_keywords": [], "category": "no_answer"},
    {"qid": "SQ-017", "query": "自动驾驶车辆的激光雷达标定流程", "expect_keywords": [], "category": "no_answer"},
    {"qid": "SQ-018", "query": "跨境电商的海外仓库存调拨策略", "expect_keywords": [], "category": "no_answer"},
    {"qid": "SQ-019", "query": "医院 HIS 系统的电子病历互认接口规范", "expect_keywords": [], "category": "no_answer"},
    {"qid": "SQ-020", "query": "新能源汽车充电桩的 OCPP 协议适配方案", "expect_keywords": [], "category": "no_answer"},
]


# ── 文档加载 ──

def load_poc_samples() -> list[dict]:
    """加载 POC-A 合成样例文档。

    Returns:
        [{"filename": str, "title": str, "content": str, "doc_type": str}, ...]
    """
    docs = []
    type_dirs = [
        ("prds", "prd"),
        ("norms", "norm"),
        ("reports", "report"),
    ]
    for subdir, doc_type in type_dirs:
        dir_path = POC_SAMPLES_DIR / subdir
        if not dir_path.exists():
            logger.warning(f"样例目录不存在: {dir_path}")
            continue
        for md_file in sorted(dir_path.glob("*.md")):
            content = md_file.read_text(encoding="utf-8").strip()
            if len(content) < 100:
                continue
            # 从文件名提取标题
            parts = md_file.stem.split("-", 1)
            title = parts[1] if len(parts) > 1 else md_file.stem
            docs.append({
                "filename": md_file.name,
                "title": title,
                "content": content,
                "doc_type": doc_type,
            })
    logger.info(f"加载 {len(docs)} 份样例文档")
    return docs


def generate_auto_questions(docs: list[dict], max_per_doc: int = 2) -> list[EvalQuestion]:
    """为每份文档自动生成 title_find 和 section_find 问题。

    Args:
        docs: 文档列表
        max_per_doc: 每份文档最多生成几个问题

    Returns:
        EvalQuestion 列表
    """
    questions = []
    q_counter = 0

    for doc in docs:
        title = doc["title"]
        q_counter += 1
        questions.append(EvalQuestion(
            qid=f"AQ-{q_counter:03d}",
            query=f"{title} 主要需求是什么",
            expect_source_titles=[title],
            category="title_find",
        ))

        # section_find: 从文档内容提取第一个二级标题
        import re
        headings = re.findall(r"^##\s+(.+)$", doc["content"], re.MULTILINE)
        if headings and max_per_doc >= 2:
            q_counter += 1
            section = headings[0].strip()
            questions.append(EvalQuestion(
                qid=f"AQ-{q_counter:03d}",
                query=f"{title} 的 {section} 包含哪些内容",
                expect_source_titles=[title],
                category="section_find",
            ))

    return questions


def generate_supplemental_questions(docs: list[dict]) -> list[EvalQuestion]:
    """生成 POC-C 手写补充问题，为语义/跨文档问题填充期望文档。

    Args:
        docs: 文档列表（用于关键词匹配填充 expect）

    Returns:
        EvalQuestion 列表
    """
    questions = []
    for sq in SUPPLEMENTAL_QUESTIONS:
        if sq["category"] == "no_answer":
            questions.append(EvalQuestion(
                qid=sq["qid"],
                query=sq["query"],
                expect_source_titles=[],
                category="no_answer",
            ))
            continue

        # 基于关键词匹配文档标题
        keywords = sq["expect_keywords"]
        matched_titles = []
        for doc in docs:
            title_lower = doc["title"].lower()
            if any(kw.lower() in title_lower for kw in keywords):
                matched_titles.append(doc["title"])

        questions.append(EvalQuestion(
            qid=sq["qid"],
            query=sq["query"],
            expect_source_titles=matched_titles,
            category=sq["category"],
        ))

    return questions


# ── 命中判定 ──

def _title_matches(returned_title: str, expected_titles: list[str]) -> bool:
    """判断返回文档标题是否匹配任一期望标题。

    使用 startswith 和关键词包含两种策略。
    """
    returned_lower = returned_title.lower()
    for expected in expected_titles:
        expected_lower = expected.lower()
        # 精确包含
        if expected_lower in returned_lower or returned_lower in expected_lower:
            return True
        # 关键词匹配（取标题中的核心词）
        core_terms = [t for t in expected_lower.split() if len(t) > 1]
        if core_terms and sum(1 for t in core_terms if t in returned_lower) >= len(core_terms) * 0.5:
            return True
    return False


# ── 评估主流程 ──

async def run_evaluation(
    api_key: str,
    output_dir: Path,
    dist_threshold: float = 1.0,
    gap_threshold: float = 0.065,
) -> EvalSummary:
    """执行 P2.D.1 检索评估。

    使用独立的评估数据库和 LanceDB 索引，不影响生产 runtime。

    Args:
        api_key: OpenAI API Key
        output_dir: 评估结果输出目录
        dist_threshold: 拒答绝对距离阈值
        gap_threshold: 拒答分数差阈值

    Returns:
        EvalSummary 评估汇总
    """
    # ── Step 0: 设置独立评估环境 ──
    eval_runtime = output_dir / "runtime"
    eval_runtime.mkdir(parents=True, exist_ok=True)
    eval_db_path = eval_runtime / "data" / "eval.db"
    eval_db_path.parent.mkdir(parents=True, exist_ok=True)
    eval_vector_dir = eval_runtime / "vector" / "lancedb"
    if eval_vector_dir.exists():
        shutil.rmtree(eval_vector_dir)
    eval_vector_dir.mkdir(parents=True, exist_ok=True)

    # 设置运行时路径
    os.environ["RUNTIME_ROOT"] = str(eval_runtime)
    # 重新导入以使用新路径
    import app.runtime_paths
    app.runtime_paths._runtime_root = Path(eval_runtime)

    logger.info(f"评估数据库: {eval_db_path}")
    logger.info(f"评估向量索引: {eval_vector_dir}")

    # ── Step 1: 初始化数据库和服务 ──
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{eval_db_path}",
        echo=False,
    )
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    # 创建表
    from app.models.user import Base
    from app.models.workspace import Workspace, WorkspaceMember, KnowledgeSource, ProjectSourceRef  # noqa: F401
    from app.models.knowledge import KnowledgeDocument, KnowledgeChunk, RetrievalLog, AnswerFeedback  # noqa: F401
    from app.models.user import User, ContextItem, SkillConfig  # noqa: F401
    from app.models.review import ReviewProject, ReviewDocument, ReviewTask, DocAnalysis, SystemReview, ReviewContext, ReviewPrompt  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # ── Step 2: 创建默认 workspace 和测试用户 ──
    async with async_session() as db:
        ws = Workspace(
            name="评估测试空间",
            description="P2.D.1 检索评估专用",
            is_default=True,
            status="active",
        )
        db.add(ws)
        await db.flush()

        test_user = User(
            username="eval_tester",
            password_hash="unused",
            role="admin",
        )
        db.add(test_user)
        await db.flush()

        ws_member = WorkspaceMember(
            workspace_id=ws.id,
            user_id=test_user.id,
            role="owner",
            status="active",
        )
        db.add(ws_member)
        await db.commit()

        workspace_id = ws.id
        user_id = test_user.id

    logger.info(f"创建评估 workspace_id={workspace_id}, user_id={user_id}")

    # ── Step 3: 导入样例文档到数据库 ──
    docs = load_poc_samples()
    if not docs:
        logger.error("未找到样例文档，终止评估")
        sys.exit(1)

    # 创建 KnowledgeSource + 入库
    from app.services.knowledge_ingestion import KnowledgeIngestionService

    source_id_to_title: dict[int, str] = {}  # source_id → title
    title_to_source_id: dict[str, int] = {}  # title → source_id

    async with async_session() as db:
        for doc_data in docs:
            ks = KnowledgeSource(
                workspace_id=workspace_id,
                source_type="upload",
                title=doc_data["title"],
                filename=doc_data["filename"],
                content_hash="",  # 入库时会重新计算
                extracted_text=doc_data["content"],
                version=1,
                owner_id=user_id,
                status="active",
            )
            db.add(ks)
            await db.flush()
            source_id_to_title[ks.id] = doc_data["title"]
            title_to_source_id[doc_data["title"]] = ks.id

        await db.commit()

    logger.info(f"导入 {len(source_id_to_title)} 份 KnowledgeSource")

    # 执行入库（切块 + FTS5 索引）
    total_chunks = 0
    async with async_session() as db:
        ingestion = KnowledgeIngestionService(db)
        for source_id in source_id_to_title:
            kd = await ingestion.ingest_source(source_id)
            if kd:
                from sqlalchemy import select as sa_select
                from app.models.knowledge import KnowledgeChunk
                result = await db.execute(
                    sa_select(KnowledgeChunk).where(KnowledgeChunk.document_id == kd.id)
                )
                chunk_count = len(list(result.scalars().all()))
                total_chunks += chunk_count
                logger.info(f"  source_id={source_id} ({source_id_to_title[source_id]}): {chunk_count} chunks")
        await db.commit()

    logger.info(f"总计 {total_chunks} chunks 已入库并建立 FTS5 索引")

    # ── Step 4: 构建向量索引（LanceDB + OpenAI embedding）──
    from app.services.embedding_service import EmbeddingService
    from app.services.knowledge_vector_service import KnowledgeVectorService, VectorChunk
    from app.services.retrieval_service import RetrievalService

    embed_service = EmbeddingService(api_key=api_key)
    vector_service = KnowledgeVectorService()

    # 覆盖向量目录到评估目录
    vector_service._vector_dir_override = eval_vector_dir

    # 预热 embedding API
    logger.info("预热 EmbeddingService...")
    warmup_ok = await embed_service.warmup()
    if not warmup_ok:
        logger.error("EmbeddingService 预热失败，请检查 API Key")
        sys.exit(1)
    logger.info("预热完成")

    # 获取所有 chunks 并嵌入
    async with async_session() as db:
        from sqlalchemy import select as sa_select
        from app.models.knowledge import KnowledgeChunk, KnowledgeDocument

        result = await db.execute(
            sa_select(KnowledgeChunk).order_by(KnowledgeChunk.id)
        )
        all_chunks = list(result.scalars().all())

        # 获取文档→source 映射
        result = await db.execute(sa_select(KnowledgeDocument))
        all_docs = {d.id: d for d in result.scalars().all()}

    logger.info(f"开始嵌入 {len(all_chunks)} 个 chunks...")

    # 批量嵌入
    chunk_texts = [c.text for c in all_chunks]
    all_vectors = []
    batch_size = 100
    for i in range(0, len(chunk_texts), batch_size):
        batch = chunk_texts[i:i + batch_size]
        batch_vecs = await embed_service.embed_batch(batch)
        all_vectors.extend(batch_vecs)
        logger.info(f"  嵌入进度: {min(i + batch_size, len(chunk_texts))}/{len(chunk_texts)}")

    # 构建 VectorChunk 列表
    vector_chunks = []
    for chunk, vector in zip(all_chunks, all_vectors):
        doc = all_docs[chunk.document_id]
        source_title = source_id_to_title.get(doc.source_id, "unknown")
        vector_chunks.append(VectorChunk(
            chunk_id=chunk.id,
            source_id=doc.source_id,
            workspace_id=workspace_id,
            title=source_title,
            section=chunk.section,
            text=chunk.text,
        ))

    # 写入 LanceDB
    logger.info("写入 LanceDB 向量索引...")
    count = await vector_service.upsert(vector_chunks, all_vectors)
    logger.info(f"LanceDB 索引构建完成: {count} 条记录")

    # 更新 embedding_status
    async with async_session() as db:
        from app.models.knowledge import KnowledgeChunk
        from sqlalchemy import update
        chunk_ids = [c.id for c in all_chunks]
        for start in range(0, len(chunk_ids), 100):
            batch_ids = chunk_ids[start:start + 100]
            await db.execute(
                update(KnowledgeChunk)
                .where(KnowledgeChunk.id.in_(batch_ids))
                .values(embedding_status="done")
            )
        await db.commit()

    # ── Step 5: 创建 RetrievalService ──
    retrieval_service = RetrievalService(
        vector_service=vector_service,
        embedding_service=embed_service,
        dist_threshold=dist_threshold,
        gap_threshold=gap_threshold,
    )

    # ── Step 6: 生成评估问题 ──
    auto_questions = generate_auto_questions(docs)
    supplemental_questions = generate_supplemental_questions(docs)
    all_questions = auto_questions + supplemental_questions

    logger.info(f"评估问题总数: {len(all_questions)}")
    logger.info(f"  title_find: {sum(1 for q in all_questions if q.category == 'title_find')}")
    logger.info(f"  section_find: {sum(1 for q in all_questions if q.category == 'section_find')}")
    logger.info(f"  semantic_match: {sum(1 for q in all_questions if q.category == 'semantic_match')}")
    logger.info(f"  cross_doc: {sum(1 for q in all_questions if q.category == 'cross_doc')}")
    logger.info(f"  no_answer: {sum(1 for q in all_questions if q.category == 'no_answer')}")

    # ── Step 7: 执行检索评估 ──
    results: list[EvalResult] = []
    # 用于延迟统计的多次测量
    latency_rounds = 3

    # 构建源ID到标题映射（用于命中判断）
    source_title_by_id = {sid: title for title, sid in title_to_source_id.items()}

    logger.info("开始检索评估...")
    for qi, question in enumerate(all_questions):
        latencies = []
        last_response = None

        for round_i in range(latency_rounds):
            start = time.monotonic()
            response = await retrieval_service.retrieve(
                query=question.query,
                workspace_id=workspace_id,
                top_k=5,
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            latencies.append(elapsed_ms)
            last_response = response

        # 使用第一次的延迟（包含 embedding 冷启动可能）
        avg_latency = statistics.mean(latencies)

        # 收集返回的 source_id 和 title
        returned_source_ids = []
        returned_titles = []
        for r in last_response.results:
            returned_source_ids.append(r.source_id)
            title = source_title_by_id.get(r.source_id, f"source-{r.source_id}")
            returned_titles.append(title)

        # 命中判定
        if question.category == "no_answer":
            # no_answer: 系统应拒答（top-1 被标记 rejected 或返回空）
            top1_hit = False
            top5_hit = False
            # 拒答 = top-1 被 rejected 或无结果
            no_answer_correct = (
                len(last_response.results) == 0
                or last_response.results[0].rejected
            )
        else:
            # 有答案问题：返回的 source 是否匹配期望
            no_answer_correct = None
            if question.expect_source_titles:
                top5_hit = any(
                    _title_matches(rt, question.expect_source_titles)
                    for rt in returned_titles[:5]
                )
                top1_hit = (
                    len(returned_titles) > 0
                    and _title_matches(returned_titles[0], question.expect_source_titles)
                )
            else:
                # 期望标题为空（补充问题匹配失败），不计入命中率
                top5_hit = True  # 不惩罚
                top1_hit = True

        # 提取距离信息
        confidence_top1 = last_response.results[0].confidence if last_response.results else "none"
        rejected_top1 = last_response.results[0].rejected if last_response.results else True
        dist_top1 = last_response.results[0]._distance if last_response.results else float("inf")
        gap = None
        if len(last_response.results) >= 2:
            gap = last_response.results[1]._distance - last_response.results[0]._distance

        result = EvalResult(
            qid=question.qid,
            query=question.query,
            category=question.category,
            expect_source_titles=question.expect_source_titles,
            returned_source_ids=returned_source_ids,
            returned_source_titles=returned_titles,
            top1_hit=top1_hit,
            top5_hit=top5_hit,
            no_answer_correct=no_answer_correct,
            latency_ms=avg_latency,
            confidence_top1=confidence_top1,
            rejected_top1=rejected_top1,
            dist_top1=dist_top1,
            gap_top1_top2=gap,
            fallback_reason=last_response.fallback_reason,
        )
        results.append(result)

        if (qi + 1) % 10 == 0 or qi == len(all_questions) - 1:
            logger.info(f"  进度: {qi + 1}/{len(all_questions)}")

    # ── Step 8: 权限过滤验证 ──
    permission_violations = 0
    logger.info("验证权限过滤（跨 workspace 检索应返回 0 条）...")
    # 创建另一个 workspace
    async with async_session() as db:
        other_ws = Workspace(
            name="隔离测试空间",
            description="不应返回此空间的文档",
            is_default=False,
            status="active",
        )
        db.add(other_ws)
        await db.flush()
        other_ws_id = other_ws.id
        await db.commit()

    # 向隔离空间检索
    perm_response = await retrieval_service.retrieve(
        query="智能对话系统",
        workspace_id=other_ws_id,
        top_k=5,
    )
    if len(perm_response.results) > 0:
        permission_violations = len(perm_response.results)
        logger.error(f"⚠️ 权限违规: 跨 workspace 检索返回 {permission_violations} 条结果！")
    else:
        logger.info("✅ 权限过滤验证通过: 跨 workspace 返回 0 条")

    # ── Step 9: 计算汇总指标 ──
    # 排除 expect 为空的补充问题（无法判定命中）
    answerable_results = [r for r in results if r.category != "no_answer" and r.no_answer_correct is None]
    no_answer_results = [r for r in results if r.category == "no_answer"]

    # 可回答问题的命中率（排除 expect_source_titles 为空的）
    scorable_answerable = [r for r in answerable_results if r.expect_source_titles]
    top5_hits = sum(1 for r in scorable_answerable if r.top5_hit)
    top1_hits = sum(1 for r in scorable_answerable if r.top1_hit)
    top5_rate = top5_hits / len(scorable_answerable) if scorable_answerable else 0
    top1_rate = top1_hits / len(scorable_answerable) if scorable_answerable else 0

    # no_answer 拒答率
    no_answer_total = len(no_answer_results)
    no_answer_rejected = sum(1 for r in no_answer_results if r.no_answer_correct)
    no_answer_rate = no_answer_rejected / no_answer_total if no_answer_total else 0

    # 延迟统计
    all_latencies = [r.latency_ms for r in results]
    sorted_latencies = sorted(all_latencies)
    avg_latency = statistics.mean(all_latencies)
    p50 = sorted_latencies[int(len(sorted_latencies) * 0.50)] if sorted_latencies else 0
    p95 = sorted_latencies[int(len(sorted_latencies) * 0.95)] if sorted_latencies else 0
    p99 = sorted_latencies[min(int(len(sorted_latencies) * 0.99), len(sorted_latencies) - 1)] if sorted_latencies else 0

    # 分类命中率
    categories = set(r.category for r in results)
    category_rates = {}
    for cat in sorted(categories):
        cat_results = [r for r in results if r.category == cat]
        if cat == "no_answer":
            cat_rejected = sum(1 for r in cat_results if r.no_answer_correct)
            cat_total = len(cat_results)
            category_rates[cat] = {
                "total": cat_total,
                "rejection_rate": cat_rejected / cat_total if cat_total else 0,
            }
        else:
            scorable = [r for r in cat_results if r.expect_source_titles]
            if scorable:
                cat_top5 = sum(1 for r in scorable if r.top5_hit) / len(scorable)
                cat_top1 = sum(1 for r in scorable if r.top1_hit) / len(scorable)
            else:
                cat_top5 = 0
                cat_top1 = 0
            category_rates[cat] = {
                "total": len(cat_results),
                "scorable": len(scorable),
                "top5_rate": cat_top5,
                "top1_rate": cat_top1,
            }

    # 验收判定
    pass_reasons = []
    passed = True

    if top5_rate >= 0.80:
        pass_reasons.append(f"✅ top-5 命中率 {top5_rate:.1%} ≥ 80%（门槛）")
    else:
        passed = False
        pass_reasons.append(f"❌ top-5 命中率 {top5_rate:.1%} < 80%（门槛）")

    if top5_rate >= 0.92:
        pass_reasons.append(f"✅ top-5 命中率 {top5_rate:.1%} ≥ 92%（预期）")

    if no_answer_rate >= 0.50:
        pass_reasons.append(f"✅ no_answer 拒答率 {no_answer_rate:.1%} ≥ 50%")
    else:
        passed = False
        pass_reasons.append(f"❌ no_answer 拒答率 {no_answer_rate:.1%} < 50%")

    if permission_violations == 0:
        pass_reasons.append("✅ 无越权召回")
    else:
        passed = False
        pass_reasons.append(f"❌ 存在 {permission_violations} 条越权召回")

    summary = EvalSummary(
        total_questions=len(all_questions),
        top5_hit_rate=top5_rate,
        top1_hit_rate=top1_rate,
        no_answer_rejection_rate=no_answer_rate,
        no_answer_total=no_answer_total,
        no_answer_rejected=no_answer_rejected,
        avg_latency_ms=round(avg_latency, 1),
        p50_latency_ms=round(p50, 1),
        p95_latency_ms=round(p95, 1),
        p99_latency_ms=round(p99, 1),
        category_rates=category_rates,
        permission_violations=permission_violations,
        passed=passed,
        pass_reasons=pass_reasons,
    )

    # ── Step 10: 输出报告 ──
    _write_report(
        summary=summary,
        results=results,
        output_dir=output_dir,
        total_docs=len(docs),
        total_chunks=total_chunks,
        dist_threshold=dist_threshold,
        gap_threshold=gap_threshold,
    )

    # 保存原始结果 JSON
    results_json = output_dir / "p2d1_results.json"
    with open(results_json, "w", encoding="utf-8") as f:
        json.dump({
            "summary": {
                "total_questions": summary.total_questions,
                "top5_hit_rate": summary.top5_hit_rate,
                "top1_hit_rate": summary.top1_hit_rate,
                "no_answer_rejection_rate": summary.no_answer_rejection_rate,
                "avg_latency_ms": summary.avg_latency_ms,
                "p50_latency_ms": summary.p50_latency_ms,
                "p95_latency_ms": summary.p95_latency_ms,
                "p99_latency_ms": summary.p99_latency_ms,
                "permission_violations": summary.permission_violations,
                "passed": summary.passed,
            },
            "details": [
                {
                    "qid": r.qid,
                    "query": r.query,
                    "category": r.category,
                    "top1_hit": r.top1_hit,
                    "top5_hit": r.top5_hit,
                    "no_answer_correct": r.no_answer_correct,
                    "latency_ms": r.latency_ms,
                    "confidence_top1": r.confidence_top1,
                    "rejected_top1": r.rejected_top1,
                    "dist_top1": r.dist_top1,
                    "gap_top1_top2": r.gap_top1_top2,
                    "returned_source_ids": r.returned_source_ids,
                    "returned_source_titles": r.returned_source_titles[:3],
                }
                for r in results
            ],
        }, f, ensure_ascii=False, indent=2)

    logger.info(f"原始结果已保存: {results_json}")

    # 清理
    await engine.dispose()

    return summary


def _write_report(
    summary: EvalSummary,
    results: list[EvalResult],
    output_dir: Path,
    total_docs: int,
    total_chunks: int,
    dist_threshold: float,
    gap_threshold: float,
) -> None:
    """生成 Markdown 评估报告。"""
    report_path = output_dir / "P2D1-检索评估报告.md"

    lines = []
    lines.append("# P2.D.1 检索评估报告")
    lines.append("")
    lines.append(f"> 评估时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> 评估数据: {total_docs} 份文档 / {total_chunks} 个 chunks / {summary.total_questions} 个问题")
    lines.append(f"> 拒答阈值: dist_threshold={dist_threshold}, gap_threshold={gap_threshold}")
    lines.append(f"> 嵌入模型: OpenAI text-embedding-3-small (1536 维)")
    lines.append(f"> 向量库: LanceDB")
    lines.append("")

    # 验收结论
    lines.append("## 验收结论")
    lines.append("")
    verdict = "✅ 通过" if summary.passed else "❌ 未通过"
    lines.append(f"**验收结果: {verdict}**")
    lines.append("")
    for reason in summary.pass_reasons:
        lines.append(f"- {reason}")
    lines.append("")

    # 总体指标
    lines.append("## 总体指标")
    lines.append("")
    lines.append("| 指标 | 值 | 验收标准 |")
    lines.append("| --- | --- | --- |")
    lines.append(f"| top-5 命中率 | {summary.top5_hit_rate:.1%} | ≥ 80%（预期 ≥ 92%）|")
    lines.append(f"| top-1 命中率 | {summary.top1_hit_rate:.1%} | — |")
    lines.append(f"| no_answer 拒答率 | {summary.no_answer_rejection_rate:.1%} | ≥ 50% |")
    lines.append(f"| no_answer 拒答数 | {summary.no_answer_rejected}/{summary.no_answer_total} | — |")
    lines.append(f"| 权限违规 | {summary.permission_violations} | 0 |")
    lines.append(f"| 平均延迟 | {summary.avg_latency_ms:.0f}ms | — |")
    lines.append(f"| P50 延迟 | {summary.p50_latency_ms:.0f}ms | — |")
    lines.append(f"| P95 延迟 | {summary.p95_latency_ms:.0f}ms | — |")
    lines.append(f"| P99 延迟 | {summary.p99_latency_ms:.0f}ms | — |")
    lines.append("")

    # 分类命中率
    lines.append("## 分类命中率")
    lines.append("")
    lines.append("| 类别 | 问题数 | top-5 命中率 | top-1 命中率 | 备注 |")
    lines.append("| --- | ---: | ---: | ---: | --- |")
    for cat, rates in summary.category_rates.items():
        if cat == "no_answer":
            lines.append(f"| {cat} | {rates['total']} | — | — | 拒答率 {rates['rejection_rate']:.1%} |")
        else:
            lines.append(
                f"| {cat} | {rates.get('scorable', rates['total'])} | "
                f"{rates.get('top5_rate', 0):.1%} | {rates.get('top1_rate', 0):.1%} | — |"
            )
    lines.append("")

    # no_answer 详细分析
    no_answer_results = [r for r in results if r.category == "no_answer"]
    if no_answer_results:
        lines.append("## no_answer 问题详细分析")
        lines.append("")
        lines.append("| QID | 查询 | 拒答 | top-1 dist | gap | confidence |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for r in no_answer_results:
            rejected = "✅" if r.no_answer_correct else "❌"
            gap_str = f"{r.gap_top1_top2:.4f}" if r.gap_top1_top2 is not None else "—"
            lines.append(
                f"| {r.qid} | {r.query[:20]}… | {rejected} | "
                f"{r.dist_top1:.4f} | {gap_str} | {r.confidence_top1} |"
            )
        lines.append("")

    # 距离分布分析
    answerable_results = [r for r in results if r.category != "no_answer" and not r.rejected_top1]
    if answerable_results:
        dists = [r.dist_top1 for r in answerable_results]
        gaps = [r.gap_top1_top2 for r in answerable_results if r.gap_top1_top2 is not None]
        na_dists = [r.dist_top1 for r in no_answer_results]
        na_gaps = [r.gap_top1_top2 for r in no_answer_results if r.gap_top1_top2 is not None]

        lines.append("## 距离分布分析")
        lines.append("")
        lines.append("| 统计量 | 可回答 top-1 dist | 可回答 gap | 无答案 top-1 dist | 无答案 gap |")
        lines.append("| --- | --- | --- | --- | --- |")
        for stat_name, stat_fn in [("min", min), ("P10", lambda x: x[int(len(x)*0.10)] if x else 0),
                                    ("median", statistics.median), ("P90", lambda x: x[int(len(x)*0.90)] if x else 0),
                                    ("max", max)]:
            d_val = stat_fn(dists) if dists else 0
            g_val = stat_fn(gaps) if gaps else 0
            nd_val = stat_fn(na_dists) if na_dists else 0
            ng_val = stat_fn(na_gaps) if na_gaps else 0
            lines.append(f"| {stat_name} | {d_val:.4f} | {g_val:.4f} | {nd_val:.4f} | {ng_val:.4f} |")
        lines.append("")

    # 未命中问题详情
    missed = [r for r in results if r.category != "no_answer" and r.expect_source_titles and not r.top5_hit]
    if missed:
        lines.append("## 未命中问题详情")
        lines.append("")
        lines.append("| QID | 类别 | 查询 | 期望文档 | 返回 top-3 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for r in missed[:20]:  # 最多展示 20 条
            expect_str = "、".join(r.expect_source_titles[:2])
            return_str = "、".join(r.returned_source_titles[:3])
            lines.append(f"| {r.qid} | {r.category} | {r.query[:30]}… | {expect_str[:30]}… | {return_str[:30]}… |")
        if len(missed) > 20:
            lines.append(f"| ... | ... | ... | ... | 共 {len(missed)} 条未命中 |")
        lines.append("")

    report_text = "\n".join(lines)
    report_path.write_text(report_text, encoding="utf-8")
    logger.info(f"评估报告已保存: {report_path}")


# ── CLI 入口 ──

def main():
    import argparse

    parser = argparse.ArgumentParser(description="P2.D.1 检索评估")
    parser.add_argument("--api-key", type=str, default=None,
                        help="OpenAI API Key 文件路径或直接值")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="评估结果输出目录")
    parser.add_argument("--dist-threshold", type=float, default=1.0,
                        help="拒答绝对距离阈值 (默认: 1.0)")
    parser.add_argument("--gap-threshold", type=float, default=0.065,
                        help="拒答分数差阈值 (默认: 0.065)")
    args = parser.parse_args()

    # 解析 API Key
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key and args.api_key:
        key_path = Path(args.api_key)
        if key_path.exists():
            api_key = key_path.read_text().strip()
        else:
            api_key = args.api_key

    if not api_key or not api_key.startswith("sk-"):
        # 尝试从 poc-c 目录读取
        poc_c_key = PROJECT_ROOT / "poc-c" / "openai-key.txt"
        if poc_c_key.exists():
            api_key = poc_c_key.read_text().strip()
            logger.info(f"从 {poc_c_key} 读取 API Key")
        else:
            logger.error("未找到有效的 OpenAI API Key。请设置 OPENAI_API_KEY 环境变量或使用 --api-key 参数")
            sys.exit(1)

    # 输出目录
    output_dir = Path(args.output_dir) if args.output_dir else PROJECT_ROOT / "eval" / "p2d1"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 60)
    logger.info("P2.D.1 检索评估")
    logger.info(f"输出目录: {output_dir}")
    logger.info(f"拒答阈值: dist={args.dist_threshold}, gap={args.gap_threshold}")
    logger.info("=" * 60)

    summary = asyncio.run(run_evaluation(
        api_key=api_key,
        output_dir=output_dir,
        dist_threshold=args.dist_threshold,
        gap_threshold=args.gap_threshold,
    ))

    # 打印结果
    logger.info("=" * 60)
    logger.info("评估结果:")
    logger.info(f"  top-5 命中率: {summary.top5_hit_rate:.1%}")
    logger.info(f"  top-1 命中率: {summary.top1_hit_rate:.1%}")
    logger.info(f"  no_answer 拒答率: {summary.no_answer_rejection_rate:.1%}")
    logger.info(f"  权限违规: {summary.permission_violations}")
    logger.info(f"  平均延迟: {summary.avg_latency_ms:.0f}ms")
    for reason in summary.pass_reasons:
        logger.info(f"  {reason}")
    logger.info("=" * 60)

    return 0 if summary.passed else 1


if __name__ == "__main__":
    sys.exit(main())
