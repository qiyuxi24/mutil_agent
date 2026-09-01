"""技能路由中间件（src/skill_router.py）测试。

对齐 SkillRouter 论文（arXiv:2603.22455）的 retrieve-and-rerank + body-aware
方法论，覆盖：索引、触发词优先、正文感知（body-aware，论文核心洞见——
只看 description 会漏）、角色匹配、frontmatter 校验、CLI JSON 输出。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from skill_router import SkillRouter, SkillRouterError


def _write_skill(root: Path, name: str, description: str, assign_when: str, body: str) -> None:
    d = root / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\nassign_when: {assign_when}\n---\n\n{body}\n",
        encoding="utf-8",
    )


@pytest.fixture()
def skills_dir(tmp_path: Path) -> Path:
    _write_skill(
        tmp_path, "code-gen",
        "基于根因与影响面报告生成最小修复补丁并应用。触发词：修复、补丁、fix、patch。",
        "修复工程师（Fixer）需要生成修复补丁时分配。",
        "生成最小修复补丁，git checkout 独立分支，应用补丁，运行静态自检，产出 fix-summary.json。",
    )
    _write_skill(
        tmp_path, "repo-context",
        "分析代码仓库结构、技术栈与构建命令。触发词：仓库、结构、技术栈。",
        "任何 Worker 需要理解仓库时分配。",
        "扫描目录树，读取构建配置（package.json/go.mod），生成 repo-context.json。",
    )
    _write_skill(
        tmp_path, "knowledge-rag",
        "从知识库检索答案支撑任务。",
        "任务需要外部知识时分配。",
        "把问题转为向量 embedding，对知识库做 top-k 文档检索，返回出处与置信度。",
    )
    return tmp_path / "skills"


# ---------- 索引 ----------

def test_index_counts_skills(skills_dir: Path) -> None:
    router = SkillRouter(skills_dir=skills_dir)
    assert len(router.skills) == 3
    names = {doc.name for doc in router.skills}
    assert names == {"code-gen", "repo-context", "knowledge-rag"}


def test_validate_all_ok(skills_dir: Path) -> None:
    assert SkillRouter(skills_dir=skills_dir).validate() == []


def test_validate_missing_field(tmp_path: Path) -> None:
    d = tmp_path / "skills" / "bad"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: bad\nassign_when: 有角色没有描述\n---\n\nbody\n", encoding="utf-8"
    )
    errors = SkillRouter(skills_dir=tmp_path / "skills").validate()
    assert any("description" in err for err in errors)


def test_aris_format_assign_when_fallback(tmp_path: Path) -> None:
    """ARIS 风格：无 assign_when，触发词内嵌在 description 的 Use when 段。"""
    d = tmp_path / "skills" / "arxiv"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\n"
        "name: arxiv\n"
        "description: Search and download academic papers from arXiv. "
        "Use when user says \"search arxiv\" or \"download paper\".\n"
        "argument-hint: query\n"
        "---\n\n"
        "## Steps\nSearch the arXiv API for the given query.\n",
        encoding="utf-8",
    )
    router = SkillRouter(skills_dir=tmp_path / "skills")
    assert router.validate() == []
    doc = router.skills[0]
    assert "Use when" in doc.assign_when
    assert doc.name == "arxiv"
    hits = router.route("search arxiv for LLM papers", top_k=1)
    assert hits[0].skill == "arxiv"


def test_validate_dir_name_mismatch(tmp_path: Path) -> None:
    d = tmp_path / "skills" / "mismatch"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: other\ndescription: x\nassign_when: y\n---\n\nbody\n", encoding="utf-8"
    )
    errors = SkillRouter(skills_dir=tmp_path / "skills").validate()
    assert any("不一致" in err for err in errors)


def test_missing_frontmatter_raises(tmp_path: Path) -> None:
    d = tmp_path / "skills" / "nofm"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("# 没有 frontmatter\n\nbody\n", encoding="utf-8")
    with pytest.raises(SkillRouterError):
        SkillRouter(skills_dir=tmp_path / "skills", strict=True)
    # 宽松模式下跳过坏文档并记录错误，不中断索引
    router = SkillRouter(skills_dir=tmp_path / "skills")
    assert router.skills == []
    assert any("frontmatter" in err for err in router.errors)


# ---------- 路由 ----------

def test_route_trigger_preference(skills_dir: Path) -> None:
    router = SkillRouter(skills_dir=skills_dir)
    hits = router.route("修复登录接口的空指针，生成补丁", top_k=3)
    assert hits[0].skill == "code-gen"
    assert hits[0].score > hits[1].score
    assert any("触发词" in reason for reason in hits[0].reasons)


def test_route_body_aware(skills_dir: Path) -> None:
    """论文核心洞见：只看 description 会漏，正文包含触发细节也要能路由到。"""
    router = SkillRouter(skills_dir=skills_dir)
    # 「向量 embedding / top-k 检索」只出现在 knowledge-rag 正文，description 是泛化的
    hits = router.route("把问题转成向量 embedding 做 top-k 文档检索", top_k=3)
    assert hits[0].skill == "knowledge-rag"
    assert any("正文" in reason for reason in hits[0].reasons)


def test_route_worker_boost(skills_dir: Path) -> None:
    router = SkillRouter(skills_dir=skills_dir)
    hits = router.route("生成补丁", top_k=3, worker="fixer")
    assert hits[0].skill == "code-gen"
    assert any("角色匹配" in reason for reason in hits[0].reasons)


def test_route_empty_query(skills_dir: Path) -> None:
    router = SkillRouter(skills_dir=skills_dir)
    assert router.route("   ") == []


def test_route_json_shape(skills_dir: Path) -> None:
    router = SkillRouter(skills_dir=skills_dir)
    payload = json.loads(router.to_json(router.route("修复补丁", top_k=2)))
    assert payload["router"] == "skill_router"
    assert len(payload["hits"]) == 2
    first = payload["hits"][0]
    assert set(first) == {"rank", "skill", "score", "reasons", "path"}
    assert first["rank"] == 1


# ---------- CLI ----------

ROOT = Path(__file__).resolve().parent.parent


def _run_cli(skills_dir: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "src" / "skill_router.py"), *extra,
         "--skills-dir", str(skills_dir)],
        capture_output=True,
        text=True,
    )


def test_cli_json_output(skills_dir: Path) -> None:
    proc = _run_cli(skills_dir, "--query", "修复补丁", "--top-k", "2", "--json")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["hits"][0]["skill"] == "code-gen"


def test_cli_validate(skills_dir: Path) -> None:
    proc = _run_cli(skills_dir, "--validate")
    assert proc.returncode == 0, proc.stderr
    assert "校验通过" in proc.stdout
