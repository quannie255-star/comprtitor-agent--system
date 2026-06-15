"""
LLM 安全护栏 (Guardrails)

三层防护：
  1. 输入过滤 — 敏感词检测 + Prompt 注入防御
  2. 输出过滤 — 越狱/有害内容检测
  3. 审计记录 — 每次拦截记录到 AuditLogger

用法：
    guard = Guardrails()
    cleaned, blocked = guard.filter_input(prompt)
    if blocked:
        raise GuardrailViolation("敏感词拦截")
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ============================================================
# 拦截规则配置
# ============================================================

# 敏感词列表（可扩展为外部配置文件）
SENSITIVE_PATTERNS = [
    # 越狱攻击
    r"(忽略|忘记|无视)\s*(你|上面|之前|所有)?\s*(的\s*)?(提示|指令|规则|限制|prompt)",
    r"(扮演|假装|你现在是|你是)\s*(一个\s*)?(黑客|攻击者|恶意|反派|无限制)",
    r"(DAN|jailbreak|越狱)\s*(模式|prompt)?",
    r"(system\s*prompt|系统\s*提示词).{0,20}(泄露|打印|输出|告诉我)",
    # Prompt 注入
    r"<\|im_start\|>|<\|im_end\|>",  # 伪 token 注入
    r"\{\{.*?\}\}.*?\{\{.*?\}\}",     # 模板注入
    r"忽略上述指令.*(执行|输出|回答)",
    # 数据泄露
    r"(api[_\-]?key|secret|token|password)\s*[:=]\s*\S{8,}",
    # 有害内容
    r"(制造|制作|合成)\s*(炸弹|武器|毒品|违禁)",
]

# 输出越狱检测
OUTPUT_PATTERNS = [
    r"(作为\s*AI|我\s*无法|我\s*不能).{0,30}(但我可以|不过)",
    r"(破解|越狱)\s*成功",
    r"这是\s*(机密|内部|秘密)\s*(信息|文档|数据)",
]


@dataclass
class GuardrailEvent:
    """护栏拦截事件"""
    timestamp: str
    agent_name: str
    direction: str          # "input" | "output"
    rule: str               # 匹配到的规则
    content_snippet: str    # 触发内容（截断）
    blocked: bool

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "agent": self.agent_name,
            "direction": self.direction,
            "rule": self.rule,
            "content_snippet": self.content_snippet[:200],
            "blocked": self.blocked,
        }


class GuardrailViolation(Exception):
    """护栏拦截异常"""
    def __init__(self, message: str, rule: str = "", content: str = ""):
        super().__init__(message)
        self.rule = rule
        self.content_snippet = content[:200]


class Guardrails:
    """LLM 安全护栏

    集成方式：
        guard = Guardrails()

        # 输入前过滤
        ok, reason = guard.check_input(prompt)
        if not ok:
            raise GuardrailViolation(reason)

        # 输出后检测
        ok, reason = guard.check_output(response)
        if not ok:
            logger.warning(f"输出越狱检测: {reason}")
    """

    def __init__(self, strict_mode: bool = True):
        self.strict_mode = strict_mode
        self.events: list[GuardrailEvent] = []
        self.blocked_count = 0
        self.warning_count = 0

    def check_input(self, prompt: str, agent_name: str = "") -> tuple[bool, str]:
        """检查输入 prompt

        Returns:
            (is_safe, reason) — is_safe=False 表示应拦截
        """
        for pattern in SENSITIVE_PATTERNS:
            match = re.search(pattern, prompt, re.IGNORECASE)
            if match:
                snippet = prompt[max(0, match.start() - 20):match.end() + 20]
                event = GuardrailEvent(
                    timestamp=datetime.now().isoformat(),
                    agent_name=agent_name,
                    direction="input",
                    rule=pattern,
                    content_snippet=snippet,
                    blocked=True,
                )
                self.events.append(event)
                self.blocked_count += 1
                return False, f"输入违规: {match.group(0)[:50]}"

        return True, ""

    def check_output(self, output: str, agent_name: str = "") -> tuple[bool, str]:
        """检查 LLM 输出

        Returns:
            (is_safe, reason) — is_safe=False 表示检测到越狱/有害内容
        """
        for pattern in OUTPUT_PATTERNS:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                snippet = output[max(0, match.start() - 20):match.end() + 20]
                event = GuardrailEvent(
                    timestamp=datetime.now().isoformat(),
                    agent_name=agent_name,
                    direction="output",
                    rule=pattern,
                    content_snippet=snippet,
                    blocked=self.strict_mode,
                )
                self.events.append(event)
                if self.strict_mode:
                    self.blocked_count += 1
                    return False, f"输出越狱检测: {match.group(0)[:50]}"
                else:
                    self.warning_count += 1

        return True, ""

    def sanitize(self, text: str) -> str:
        """清洗文本：移除明显注入标记（但不拦截）"""
        cleaned = text
        # 移除 <|im_start|> / <|im_end|> 等伪 token
        cleaned = re.sub(r'<\|[^|]+\|>', '', cleaned)
        # 截断过长的重复模式（防止 token 炸弹）
        cleaned = re.sub(r'(.{20,}?)\1{5,}', r'\1[重复内容已截断]', cleaned)
        return cleaned[:32000]  # 硬截断，防止超长输入

    def summary(self) -> dict:
        """护栏运行摘要"""
        return {
            "total_checks": len(self.events) + self.blocked_count + self.warning_count,
            "input_checks": sum(1 for e in self.events if e.direction == "input"),
            "output_checks": sum(1 for e in self.events if e.direction == "output"),
            "blocked": self.blocked_count,
            "warnings": self.warning_count,
            "events": [e.to_dict() for e in self.events[-10:]],  # 最近 10 条
        }
