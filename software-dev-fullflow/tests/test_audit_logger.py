"""audit_logger.py 结构化审计日志单元测试。

覆盖：
- 四种语义化记录（decision / handoff / human_intervention / milestone / error）
- 字段完整性（timestamp / trace_id / agent_id / event_type / action / result）
- JSON Lines 落盘 + read_audit_log 回读
- 关闭后文件可被临时目录清理（Windows 句柄释放）
"""

from pathlib import Path

from loop.audit_logger import AuditLogger, read_audit_log


class TestAuditLogger:
    def test_log_decision(self, tmp_path: Path):
        with AuditLogger(tmp_path) as audit:
            line = audit.log_decision("t1", "manager", decision="approve release",
                                      justification="灰度通过", result="PASS")
        rec = read_audit_log(tmp_path / "audit.jsonl")[0]
        assert rec["event_type"] == "decision"
        assert rec["trace_id"] == "t1"
        assert rec["agent_id"] == "manager"
        assert rec["result"] == "PASS"
        assert rec["detail"]["decision"] == "approve release"
        assert rec["timestamp"]

    def test_log_handoff(self, tmp_path: Path):
        with AuditLogger(tmp_path) as audit:
            audit.log_handoff("t1", "fixer", "tester", milestone="FIX_APPLIED")
        rec = read_audit_log(tmp_path / "audit.jsonl")[0]
        assert rec["event_type"] == "handoff"
        assert rec["detail"]["from"] == "fixer"
        assert rec["detail"]["to"] == "tester"
        assert rec["detail"]["milestone"] == "FIX_APPLIED"

    def test_log_human_intervention(self, tmp_path: Path):
        with AuditLogger(tmp_path) as audit:
            audit.log_human_intervention("t1", "releaser", reason="需人工放量", approved=False)
        rec = read_audit_log(tmp_path / "audit.jsonl")[0]
        assert rec["event_type"] == "human_intervention"
        assert rec["result"] == "FAIL"
        assert rec["detail"]["reason"] == "需人工放量"

    def test_log_milestone_and_error(self, tmp_path: Path):
        with AuditLogger(tmp_path) as audit:
            audit.log_milestone("t1", "tester", "TEST_PASSED", state="TEST_VERIFY")
            audit.log_error("t1", "fixer", "compile", error="syntax error")
        recs = read_audit_log(tmp_path / "audit.jsonl")
        assert len(recs) == 2
        assert recs[0]["event_type"] == "milestone"
        assert recs[0]["result"] == "PASS"
        assert recs[1]["event_type"] == "error"
        assert recs[1]["result"] == "FAIL"
        assert recs[1]["detail"]["error"] == "syntax error"

    def test_all_entries_have_required_fields(self, tmp_path: Path):
        with AuditLogger(tmp_path) as audit:
            audit.log_decision("t2", "manager", decision="d")
            audit.log_handoff("t2", "a", "b")
            audit.log_milestone("t2", "a", "M")
            audit.log_error("t2", "a", "act", "err")
            audit.log_human_intervention("t2", "a", reason="r")
        required = {"timestamp", "trace_id", "agent_id", "event_type", "action", "result"}
        for rec in read_audit_log(tmp_path / "audit.jsonl"):
            assert required.issubset(rec.keys())

    def test_missing_file_returns_empty(self, tmp_path: Path):
        assert read_audit_log(tmp_path / "nope.jsonl") == []
