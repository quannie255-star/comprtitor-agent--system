import sys
sys.stdout.reconfigure(encoding='utf-8')
from fpdf import FPDF


class ResumePDF(FPDF):
    def __init__(self):
        super().__init__('P', 'mm', 'A4')
        self.add_font('Hei', '', 'C:/Windows/Fonts/simhei.ttf')
        self.add_font('Song', '', 'C:/Windows/Fonts/simsun.ttc')
        self.set_auto_page_break(False)
        self.set_margin(14)
        self.LH = 3.5

    def header_block(self):
        self.set_font('Hei', '', 15)
        self.cell(0, 6.5, '聂 权', align='C', new_x='LMARGIN', new_y='NEXT')
        self.set_font('Song', '', 7.5)
        self.set_text_color(110, 110, 110)
        self.cell(0, 4, 'AI产品经理实习生  |  Multi-Agent架构 · 数据驱动 · 工程落地',
                  align='C', new_x='LMARGIN', new_y='NEXT')
        self.set_text_color(95, 95, 95)
        self.cell(0, 3.5, '137-9107-2007 | niequan2024@ruc.edu.cn | github.com/quannie255-star  |  北京 · 6月下旬到岗，每周5天',
                  align='C', new_x='LMARGIN', new_y='NEXT')
        self.set_draw_color(37, 99, 235)
        self.set_line_width(0.35)
        self.line(self.l_margin, self.get_y() + 0.5, self.w - self.r_margin, self.get_y() + 0.5)
        self.ln(2.5)
        self.set_text_color(26, 26, 26)

    def section_title(self, title):
        self.ln(1)
        self.set_font('Hei', '', 8.5)
        self.set_text_color(30, 64, 175)
        self.cell(0, 4, title, new_x='LMARGIN', new_y='NEXT')
        self.set_draw_color(215, 220, 228)
        self.set_line_width(0.15)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(1.5)
        self.set_text_color(26, 26, 26)

    def line_text(self, txt, font='Song', size=7.5):
        self.set_font(font, '', size)
        self.cell(0, self.LH, txt, new_x='LMARGIN', new_y='NEXT')

    def proj_head(self, title, sub):
        self.ln(0.8)
        self.set_font('Hei', '', 8)
        self.cell(0, 3.5, title, new_x='LMARGIN', new_y='NEXT')
        self.set_font('Song', '', 6.5)
        self.set_text_color(125, 125, 125)
        self.cell(0, 2.8, sub, new_x='LMARGIN', new_y='NEXT')
        self.set_text_color(26, 26, 26)

    def bullet(self, text, size=7):
        self.set_font('Song', '', size)
        x0 = self.l_margin + 3
        self.set_x(x0)
        self.cell(2.5, self.LH, '•', align='C')
        self.multi_cell(self.w - self.r_margin - x0 - 2.5, self.LH, text)

    def strength_bullet(self, label, text, size=7):
        self.set_font('Song', '', size)
        x0 = self.l_margin + 3
        self.set_x(x0)
        self.cell(2.5, self.LH, '•', align='C')
        self.set_font('Hei', '', size)
        self.cell(self.get_string_width(label), self.LH, label)
        self.set_font('Song', '', size)
        self.multi_cell(self.w - self.r_margin - self.get_x(), self.LH, text)


def build():
    pdf = ResumePDF()
    pdf.add_page()

    # ==================== HEADER ====================
    pdf.header_block()

    # ==================== EDUCATION ====================
    pdf.section_title('教育背景')
    pdf.line_text('中国人民大学 | 数据科学与大数据技术（理学学士） | 2024.09 - 2028.06', 'Hei', 7.5)
    pdf.line_text('数学分析(91)、人工智能与Python(87)  |  美赛M奖（前10%）· 统计建模大赛二等奖 · 大创国家级立项（负责人）', size=7)

    # ==================== 核心竞争力 ====================
    pdf.section_title('核心竞争力')
    pdf.strength_bullet('Multi-Agent 落地全链路：',
                        '从需求、DAG编排、Eval闭环到前端交付，独立完成2个Agent系统从0到1，沉淀 Vibecoding 工程手册。')
    pdf.strength_bullet('Agent 架构设计：',
                        '熟练运用 DAG 流转、条件路由、反馈闭环、大小模型路由、Human-in-the-loop 等模式，设计过 3 种 RejectReason 的质检驳回回路。')
    pdf.strength_bullet('数据驱动与评测：',
                        '擅长 Python + SQL 分析，搭建 Eval 体系，用准确率、可用率、Token 成本等指标驱动决策。')
    pdf.strength_bullet('AI Native 交付：',
                        'Vibe Coding 模式下 Plan-and-Execute 工作流，项目周期从周级压缩至天级，累计编写 400+ 测试用例。')

    # ==================== 项目经历 ====================
    pdf.section_title('项目经历')

    # --- AgentHub ---
    pdf.proj_head('AgentHub — IM 式多 Agent 协作平台',
                  '独立开发 | 2026.04 - 至今 | github.com/quannie255-star/AgentHub')
    pdf.bullet('自研 TaskParser 支持编号/逗号/@-mention 三种输入，结合关键词+LLM 双路径路由，Agent 分配准确率从 70% 提升至 90%+，内置 3 次重试+降级策略。')
    pdf.bullet('设计 FastAPI + SSE 实时流式架构，自研 asyncio.Queue 消息总线，实现双阶段流式渲染（replay + live），避免消息丢失。')
    pdf.bullet('插件化 Agent 适配：AbstractAgentAdapter 抽象基类 + AdapterRegistry，新增 Agent 类型只需实现 3 个方法。293 条测试全绿，20 个 Pydantic V2 Schema，Docker + GitHub Actions CI/CD。')

    # --- Competitive Analysis ---
    pdf.proj_head('AI 驱动的竞品分析 Agent 协作系统',
                  '独立开发 | 2026.04 - 至今 | github.com/quannie255-star/comprtitor-agent--system')
    pdf.bullet('基于 LangGraph 构建 Collector → Analyst → Writer → Reviewer 流水线，质检驳回自动回退重跑（最多 3 轮），同时支持顺序 fallback 保证可用性。')
    pdf.bullet('双轨质检：Python 硬编码规则（信源/Schema 一致性）+ LLM 语义审查，报告可用率从 60% 提升至 85%+。')
    pdf.bullet('字段级溯源模型：每条结论绑定信源 URL + 摘录 + 置信度，形成"报告→来源→轨迹→数据"4 层可逆链。自研 LLMTracer/CostTracker/AuditLogger/Guardrails 可观测性体系，130 条测试。')

    # --- Computing ---
    pdf.proj_head('异构算力协同调度平台（大创国家级立项）',
                  '负责人 | 2026.03 - 至今 | github.com/quannie255-star')
    pdf.bullet('访谈 3 个实验室，定位 K8s 插件形态降低接入成本，部署时长从 1 天缩短至 10 分钟，预期算力利用率提升 20%。', size=6.5)

    # Save
    pdf.output('聂权-简历-AI产品经理.pdf')
    print('OK')


if __name__ == '__main__':
    build()
