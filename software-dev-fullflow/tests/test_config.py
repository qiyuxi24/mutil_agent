"""config.py 统一 .env 加载器单元测试。

验证：
  - _parse_dotenv：注释 / 空行 / KEY=VALUE / 引号 / 行内注释 / 空值
  - load_dotenv：注入 os.environ、不覆盖已有环境变量、幂等
"""

import os

import pytest

from loop.config import _parse_dotenv, load_dotenv


class TestParseDotenv:
    def test_skips_blank_and_comment_lines(self):
        text = "# 注释\n\nKEY=value\n# 另一行注释\n"
        assert _parse_dotenv(text) == {"KEY": "value"}

    def test_key_value_basic(self):
        text = "A=1\nB=hello world\nC=with#hash\n"
        # 无引号值：行内 # 视为注释起点
        assert _parse_dotenv(text) == {"A": "1", "B": "hello world", "C": "with"}

    def test_quoted_values_preserved(self):
        text = 'A="123"\nB=\'abc\'\nC="has # inside"\n'
        # 引号内 # 保留；无引号时才截断
        assert _parse_dotenv(text) == {"A": "123", "B": "abc", "C": "has # inside"}

    def test_empty_value(self):
        text = "EMPTY=\nKEPT=1\n"
        assert _parse_dotenv(text) == {"EMPTY": "", "KEPT": "1"}

    def test_spaces_around_equals(self):
        text = "  A  =  spaced  \n"
        assert _parse_dotenv(text) == {"A": "spaced"}

    def test_line_without_equals_ignored(self):
        text = "A=1\nnot_a_kv_line\nB=2\n"
        assert _parse_dotenv(text) == {"A": "1", "B": "2"}


class TestLoadDotenv:
    def test_loads_into_environ(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("AGT_MODE=local\nMAX_DELEGATE_ROUNDS=9\n", encoding="utf-8")
        monkeypatch.delenv("AGT_MODE", raising=False)
        monkeypatch.delenv("MAX_DELEGATE_ROUNDS", raising=False)
        ok = load_dotenv(path=str(env_file))
        assert ok is True
        assert os.environ["AGT_MODE"] == "local"
        assert os.environ["MAX_DELEGATE_ROUNDS"] == "9"

    def test_does_not_override_existing_env(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("AGT_MODE=from_file\n", encoding="utf-8")
        monkeypatch.setenv("AGT_MODE", "from_process")
        load_dotenv(path=str(env_file))
        # 真实环境变量优先级更高，.env 不覆盖
        assert os.environ["AGT_MODE"] == "from_process"

    def test_missing_file_returns_false(self, tmp_path):
        assert load_dotenv(path=str(tmp_path / "nope.env")) is False

    def test_clears_empty_value_does_not_set(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("EMPTY=\nKEPT=1\n", encoding="utf-8")
        monkeypatch.delenv("EMPTY", raising=False)
        monkeypatch.delenv("KEPT", raising=False)
        load_dotenv(path=str(env_file))
        # 空值也应注入（os.environ 值为空字符串），与语义一致
        assert os.environ.get("EMPTY") == ""
        assert os.environ["KEPT"] == "1"

    def test_idempotent_cached(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("A=1\n", encoding="utf-8")
        monkeypatch.delenv("A", raising=False)
        # 第一次加载
        assert load_dotenv(path=str(env_file)) is True
        # 之后无 path 调用不再重新找文件（_LOADED 已置位），但仍返回 True
        assert load_dotenv() is True
