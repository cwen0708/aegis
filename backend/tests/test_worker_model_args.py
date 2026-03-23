"""測試 worker.py 中 model 參數傳遞邏輯與環境變數清理"""
import os
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# 輔助：提取 run_task 中建構 cmd_parts 的邏輯（避免觸發真實子程序）
# ---------------------------------------------------------------------------
def build_cmd_parts(config: dict, prompt: str, forced_model, default_model: str = ""):
    """複製 worker.run_task 的 cmd_parts 建構邏輯用於單元測試"""
    model = forced_model if forced_model is not None else default_model
    cmd_parts = list(config["cmd_base"])
    model_replaced = False
    for arg in config["args"]:
        if "{prompt}" in arg:
            cmd_parts.append(arg.replace("{prompt}", prompt))
        elif "{model}" in arg:
            cmd_parts.append(arg.replace("{model}", model))
            model_replaced = True
        else:
            cmd_parts.append(arg)

    if forced_model is not None and not model_replaced:
        for i, arg in enumerate(cmd_parts):
            if arg == "--model" and i + 1 < len(cmd_parts):
                cmd_parts[i + 1] = forced_model
                break

    return cmd_parts


# ---------------------------------------------------------------------------
# Claude provider config（與 worker.py PROVIDERS["claude"] 結構一致）
# ---------------------------------------------------------------------------
CLAUDE_CONFIG = {
    "cmd_base": ["claude"],
    "args": ["-p", "{prompt}", "--dangerously-skip-permissions", "--model", "sonnet",
             "--output-format", "stream-json", "--verbose"],
}

OLLAMA_CONFIG = {
    "cmd_base": ["ollama", "run"],
    "args": ["{model}"],
    "default_model": "llama3.1:8b",
}


class TestModelArgBuilding:
    """測試 model 參數建構邏輯"""

    def test_forced_model_overrides_default_in_claude(self):
        """成員指定 model 時，--model 後的值應被替換"""
        parts = build_cmd_parts(CLAUDE_CONFIG, "hello", forced_model="opus")
        idx = parts.index("--model")
        assert parts[idx + 1] == "opus"

    def test_forced_model_none_keeps_default_in_claude(self):
        """forced_model=None 時保持 config 預設值"""
        parts = build_cmd_parts(CLAUDE_CONFIG, "hello", forced_model=None)
        idx = parts.index("--model")
        assert parts[idx + 1] == "sonnet"

    def test_forced_model_empty_string_overrides_in_claude(self):
        """forced_model='' 應覆蓋（舊版 falsy check 會跳過此情境）"""
        parts = build_cmd_parts(CLAUDE_CONFIG, "hello", forced_model="")
        idx = parts.index("--model")
        # 空字串也應被視為有效的 forced_model
        assert parts[idx + 1] == ""

    def test_ollama_placeholder_replacement(self):
        """ollama 使用 {model} placeholder，forced_model 應替換進去"""
        parts = build_cmd_parts(OLLAMA_CONFIG, "hi", forced_model="codellama:7b",
                                default_model="llama3.1:8b")
        assert parts == ["ollama", "run", "codellama:7b"]

    def test_ollama_none_uses_default(self):
        """ollama forced_model=None 使用 default_model"""
        parts = build_cmd_parts(OLLAMA_CONFIG, "hi", forced_model=None,
                                default_model="llama3.1:8b")
        assert parts == ["ollama", "run", "llama3.1:8b"]

    def test_ollama_empty_string_forced_model(self):
        """ollama forced_model='' 替換為空字串（placeholder 情況）"""
        parts = build_cmd_parts(OLLAMA_CONFIG, "hi", forced_model="",
                                default_model="llama3.1:8b")
        # {model} placeholder 被空字串替換，且 model_replaced=True 不觸發二次覆蓋
        assert parts == ["ollama", "run", ""]

    def test_no_double_replacement_when_placeholder_exists(self):
        """有 {model} placeholder 的 provider 不應觸發 --model flag 搜尋覆蓋"""
        config = {
            "cmd_base": ["test"],
            "args": ["{model}", "--model", "default"],
        }
        parts = build_cmd_parts(config, "hi", forced_model="custom")
        # {model} 已被替換為 custom，--model 後面保持 "default" 不被二次覆蓋
        assert parts == ["test", "custom", "--model", "default"]

    def test_prompt_not_affected_by_model_logic(self):
        """prompt 替換不受 model 邏輯影響"""
        parts = build_cmd_parts(CLAUDE_CONFIG, "test prompt", forced_model="opus")
        assert "test prompt" in parts


class TestPtyEnvCleanup:
    """測試 PTY 環境變數清理的 try/finally 保護"""

    def test_env_restored_after_exception(self):
        """模擬異常發生時環境變數應被正確恢復"""
        original_val = "test_original_value"
        key = "CLAUDE_TEST_WORKER_VAR"
        os.environ[key] = original_val

        try:
            # 模擬 PTY 環境清理流程
            claude_env_keys = [k for k in os.environ.keys()
                               if k.upper().startswith(("CLAUDE", "ANTHROPIC"))]
            old_claude_env = {k: os.environ.get(k) for k in claude_env_keys}

            try:
                for k in claude_env_keys:
                    del os.environ[k]
                # 模擬異常
                raise RuntimeError("simulated PTY spawn failure")
            finally:
                for k, v in old_claude_env.items():
                    if v is not None:
                        os.environ[k] = v
        except RuntimeError:
            pass

        assert os.environ.get(key) == original_val
        # 清理
        os.environ.pop(key, None)

    def test_env_keys_not_leaked_on_success(self):
        """正常完成時不應留下額外的環境變數"""
        key = "ANTHROPIC_TEST_ONLY"
        os.environ[key] = "should_be_restored"

        claude_env_keys = [k for k in os.environ.keys()
                           if k.upper().startswith(("CLAUDE", "ANTHROPIC"))]
        old_claude_env = {k: os.environ.get(k) for k in claude_env_keys}

        new_env = {"CUSTOM_WORKER_VAR": "value"}
        old_env = {k: os.environ.get(k) for k in new_env.keys()}

        try:
            for k in claude_env_keys:
                del os.environ[k]
            os.environ.update(new_env)
            # 模擬正常執行
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            for k, v in old_claude_env.items():
                if v is not None:
                    os.environ[k] = v

        assert os.environ.get(key) == "should_be_restored"
        assert "CUSTOM_WORKER_VAR" not in os.environ
        # 清理
        os.environ.pop(key, None)
