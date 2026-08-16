// GOAI 大赛赛道三 · 软件研发全流程协同 — 初赛方案 PPT 生成脚本
// 用法：node gen-ppt.js （输出 GOAI-赛道三-方案.pptx）
const pptxgen = require("pptxgenjs");

// ===== 主题色板（Ocean Gradient 变体，科技感）=====
const C = {
  navy: "0A2540",      // 主色（深蓝，占主导）
  deep: "065A82",      // 深蓝
  teal: "1C7293",      // 青绿
  ice:  "CADCFC",      // 冰蓝（浅）
  mint: "02C39A",      // 亮青（强调）
  white:"FFFFFF",
  off:  "F4F7FB",      // 浅背景
  gray: "5A6B7B",      // 灰
  dark: "1E293B",      // 深灰文字
};

const F = { h: "Microsoft YaHei", b: "Microsoft YaHei" }; // 标题/正文（中文字体）
const mkShadow = () => ({ type: "outer", color: "0A2540", blur: 8, offset: 3, angle: 90, opacity: 0.18 });

let pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10" x 5.625"
pres.author = "软件研发全流程协同团队";
pres.title = "GOAI 赛道三 · 软件研发全流程协同多Agent系统";

// ========== 1. 封面（深色）==========
(() => {
  const s = pres.addSlide();
  s.background = { color: C.navy };
  // 顶部细色带
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.12, fill: { color: C.mint } });
  // 主办方/赛道标签
  s.addText("GOAI 世界人工智能开源大赛 · 赛道三「软件研发全流程协同」", {
    x: 0.7, y: 0.6, w: 8.6, h: 0.4, fontSize: 13, color: C.ice, charSpacing: 2
  });
  // 主标题
  s.addText("软件研发全流程协同", {
    x: 0.7, y: 1.5, w: 8.6, h: 0.9, fontSize: 44, bold: true, color: C.white
  });
  s.addText("多 Agent 系统", {
    x: 0.7, y: 2.4, w: 8.6, h: 0.7, fontSize: 32, bold: true, color: C.mint
  });
  // 副标题
  s.addText("用 AgentTeams 打造一支可验证、可回滚、可沉淀的 PDCA 研发闭环 Agent 团队", {
    x: 0.7, y: 3.3, w: 8.6, h: 0.5, fontSize: 16, color: C.ice
  });
  // 亮点标签行
  const tags = ["6 Worker 真实闭环跑通", "7 个工程 Skill", "动态 Agent 团队"];
  tags.forEach((t, i) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: 0.7 + i * 2.05, y: 4.2, w: 1.9, h: 0.45, rectRadius: 0.1,
      fill: { color: C.teal, transparency: 20 }, line: { color: C.mint, width: 1 }
    });
    s.addText(t, { x: 0.7 + i * 2.05, y: 4.2, w: 1.9, h: 0.45, fontSize: 11, color: C.white, align: "center", valign: "middle" });
  });
  // 底部脚注
  s.addText("AgentTeams 协同基点 · AgentScope 生态 · 2026", {
    x: 0.7, y: 5.1, w: 8.6, h: 0.35, fontSize: 11, color: C.gray, charSpacing: 1
  });
})();

// ========== 2. 场景价值（评审 25%）==========
(() => {
  const s = pres.addSlide();
  s.background = { color: C.off };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 0.1, h: 5.625, fill: { color: C.mint } });
  s.addText("场景价值", { x: 0.55, y: 0.4, w: 3, h: 0.5, fontSize: 28, bold: true, color: C.navy });
  s.addText("企业级软件研发的现实痛点", { x: 0.55, y: 0.95, w: 5, h: 0.4, fontSize: 15, color: C.teal });

  // 左侧痛点（2x2 网格）
  const pain = [
    ["多源信息割裂", "Issue / 日志 / 用户反馈分散，缺陷难归一、难去重"],
    ["定位靠经验", "根因分析依赖资深工程师经验，影响面难评估"],
    ["质量难保证", "修复后测试覆盖不足，回归风险高，凭自评无客观门禁"],
    ["知识不沉淀", "每次踩坑重来，组织经验流失，无法复用"],
  ];
  pain.forEach((p, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.55 + col * 2.3, y = 1.5 + row * 1.15;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x, y, w: 2.1, h: 1.0, rectRadius: 0.08, fill: { color: C.white },
      line: { color: "D5DFEA", width: 1 }, shadow: mkShadow()
    });
    s.addText(p[0], { x: x + 0.12, y: y + 0.08, w: 1.86, h: 0.3, fontSize: 12.5, bold: true, color: C.navy });
    s.addText(p[1], { x: x + 0.12, y: y + 0.38, w: 1.86, h: 0.55, fontSize: 9.5, color: C.gray, valign: "top" });
  });

  // 右侧方案
  s.addShape(pres.shapes.RECTANGLE, { x: 5.3, y: 1.5, w: 4.2, h: 3.4, fill: { color: C.navy } });
  s.addText("我们的解法", { x: 5.55, y: 1.72, w: 3.7, h: 0.4, fontSize: 16, bold: true, color: C.mint });
  const sol = [
    "把「缺陷/需求聚合 → 根因定位 → 修复 → 测试验证 → 发布确认 → 复盘沉淀」做成可验证的 PDCA 闭环",
    "AgentTeams 声明式能力，动态组建「软件研发 Agent 团队」，按项目需求招人/裁员",
    "确定性验证闸门 + 组织记忆 RAG，实现「越跑越懂项目」",
    "天然契合企业 B 端，可复制到任意软件研发组织",
  ];
  sol.forEach((t, i) => {
    s.addText([
      { text: "  ", options: {} },
      { text: t, options: { color: C.white } }
    ], { x: 5.55, y: 2.2 + i * 0.72, w: 3.7, h: 0.66, fontSize: 10.5, valign: "top", margin: 0 });
  });
  // 底部价值点
  s.addText("以 AgentTeams（原名 Hiclaw）为协同设计基点，覆盖官方 8 环节闭环硬性要求", {
    x: 0.55, y: 5.05, w: 9, h: 0.35, fontSize: 11, italic: true, color: C.teal
  });
})();

// ========== 3. 作品定位 + 理论总纲 ==========
(() => {
  const s = pres.addSlide();
  s.background = { color: C.off };
  s.addText("作品定位", { x: 0.55, y: 0.4, w: 3, h: 0.5, fontSize: 28, bold: true, color: C.navy });
  s.addText("一句话 + 理论总纲", { x: 0.55, y: 0.95, w: 5, h: 0.4, fontSize: 15, color: C.teal });

  // 一句话定位卡片
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.55, y: 1.5, w: 8.9, h: 1.1, rectRadius: 0.1, fill: { color: C.navy }, shadow: mkShadow()
  });
  s.addText("用 AgentTeams 的声明式能力，造一支「软件研发 Agent 团队」", {
    x: 0.8, y: 1.62, w: 8.4, h: 0.4, fontSize: 15, bold: true, color: C.white
  });
  s.addText("把「缺陷聚合 → 根因定位 → 修复 → 测试验证 → 发布确认 → 复盘沉淀」做成可验证、可回滚、可沉淀的 PDCA 闭环", {
    x: 0.8, y: 2.05, w: 8.4, h: 0.45, fontSize: 11.5, color: C.ice
  });

  // 三条子原理（3 列）
  s.addText("理论总纲：PDCA 闭环（主框架）+ 三条子原理", { x: 0.55, y: 2.9, w: 6, h: 0.4, fontSize: 14, bold: true, color: C.navy });

  const subs = [
    ["自动化质量门禁", "测试验证员用确定性工具当裁判，不合格代码不进发布", C.mint],
    ["最小影响可回滚", "灰度 + 金丝雀 + Saga 补偿回滚，发布全程留痕", C.teal],
    ["组织记忆复用", "复盘沉淀到 RAG 知识库，知识复用统计反哺成长，越跑越懂项目", C.deep],
  ];
  subs.forEach((t, i) => {
    const x = 0.55 + i * 3.03;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x, y: 3.4, w: 2.85, h: 1.55, rectRadius: 0.08, fill: { color: C.white },
      line: { color: "D5DFEA", width: 1 }, shadow: mkShadow()
    });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 3.4, w: 0.08, h: 1.55, fill: { color: t[2] } });
    s.addText(t[0], { x: x + 0.2, y: 3.55, w: 2.5, h: 0.35, fontSize: 13, bold: true, color: C.navy });
    s.addText(t[1], { x: x + 0.2, y: 3.92, w: 2.5, h: 0.9, fontSize: 10, color: C.gray, valign: "top" });
  });

  s.addText("动态 Agent 团队：按需招募新职能 Agent / 项目结束移除 Agent / 新 Agent 迅速与既有团队协作出结果", {
    x: 0.55, y: 5.1, w: 9, h: 0.35, fontSize: 11, italic: true, color: C.teal
  });
})();

// ========== 4. 多 Agent 协同：6 Worker + PDCA（评审 25%）==========
(() => {
  const s = pres.addSlide();
  s.background = { color: C.off };
  s.addText("多 Agent 协同", { x: 0.55, y: 0.4, w: 3, h: 0.5, fontSize: 28, bold: true, color: C.navy });
  s.addText("6 个研发职能 Agent + PDCA 里程碑握手协议", { x: 0.55, y: 0.95, w: 6, h: 0.4, fontSize: 15, color: C.teal });

  // 6 个 Worker 卡片（3x2 网格）
  const workers = [
    ["缺陷聚合员", "Aggregator", "产品经理 + 缺陷管理", "P 计划"],
    ["根因定位员", "RootCause", "架构师 · RCA + 影响面", "D 执行"],
    ["修复工程师", "Fixer", "前后端开发", "D 执行"],
    ["测试验证员", "Tester", "测试工程师 · 质量门禁", "C 检查"],
    ["发布确认员", "Releaser", "运维 / DevOps", "A 处置"],
    ["复盘沉淀员", "Retrospector", "数据分析 + 知识沉淀", "A 处置"],
  ];
  workers.forEach((w, i) => {
    const col = i % 3, row = Math.floor(i / 3);
    const x = 0.55 + col * 3.03, y = 1.5 + row * 1.35;
    const stageColor = w[3].startsWith("P") ? C.mint : w[3].startsWith("D") ? C.teal : w[3].startsWith("C") ? C.deep : "7C6FD4";
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x, y, w: 2.85, h: 1.2, rectRadius: 0.08, fill: { color: C.white },
      line: { color: "D5DFEA", width: 1 }, shadow: mkShadow()
    });
    // 阶段色块（左上角）
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 2.85, h: 0.09, fill: { color: stageColor } });
    s.addShape(pres.shapes.OVAL, { x: x + 0.15, y: y + 0.22, w: 0.5, h: 0.5, fill: { color: stageColor, transparency: 15 } });
    s.addText(w[1].charAt(0), { x: x + 0.15, y: y + 0.22, w: 0.5, h: 0.5, fontSize: 18, bold: true, color: C.white, align: "center", valign: "middle" });
    s.addText(w[0], { x: x + 0.75, y: y + 0.18, w: 1.9, h: 0.3, fontSize: 12.5, bold: true, color: C.navy });
    s.addText(w[1], { x: x + 0.75, y: y + 0.46, w: 1.9, h: 0.25, fontSize: 9, color: C.teal });
    s.addText(w[2], { x: x + 0.75, y: y + 0.7, w: 1.3, h: 0.3, fontSize: 8.5, color: C.gray });
    s.addText(w[3], { x: x + 2.15, y: y + 0.85, w: 0.6, h: 0.25, fontSize: 8.5, bold: true, color: stageColor, align: "center" });
  });

  // 底部里程碑
  s.addText("里程碑握手：TASK_SPEC_READY → ROOT_CAUSE_FOUND → FIX_APPLIED → TEST_PASSED → RELEASE_OK → RETROSPECT_DONE（跨 Agent 交接，防死锁）", {
    x: 0.55, y: 5.0, w: 9, h: 0.35, fontSize: 11, italic: true, color: C.teal
  });
})();

// ========== 5. PDCA 闭环状态机 ==========
(() => {
  const s = pres.addSlide();
  s.background = { color: C.navy };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 0.1, h: 5.625, fill: { color: C.mint } });
  s.addText("PDCA 闭环状态机", { x: 0.55, y: 0.4, w: 4, h: 0.5, fontSize: 28, bold: true, color: C.white });
  s.addText("官方 8 环节 → PDCA 四象限 8 主状态（确定性、可审计、带回滚）", { x: 0.55, y: 0.95, w: 8, h: 0.4, fontSize: 15, color: C.ice });

  // 四象限流程块
  const quadrants = [
    ["P 计划", "任务输入 → 拆解", "SPEC_INPUT / DECOMPOSE", C.mint],
    ["D 执行", "根因 + 修复", "ROOT_CAUSE / FIX_APPLY", C.teal],
    ["C 检查", "测试验证", "TEST_VERIFY", C.deep],
    ["A 处置", "发布 + 复盘", "RELEASE / RETROSPECT", "7C6FD4"],
  ];
  quadrants.forEach((q, i) => {
    const x = 0.55 + i * 2.3, y = 1.55;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x, y, w: 2.05, h: 1.15, rectRadius: 0.1, fill: { color: C.deep, transparency: 30 },
      line: { color: q[3], width: 1.5 }
    });
    s.addText(q[0], { x, y: y + 0.12, w: 2.05, h: 0.35, fontSize: 16, bold: true, color: q[3], align: "center" });
    s.addText(q[1], { x, y: y + 0.5, w: 2.05, h: 0.28, fontSize: 10.5, color: C.white, align: "center" });
    s.addText(q[2], { x, y: y + 0.78, w: 2.05, h: 0.28, fontSize: 8.5, color: C.ice, align: "center" });
    // 箭头
    if (i < 3) {
      s.addShape(pres.shapes.OVAL, { x: x + 2.08, y: y + 0.48, w: 0.18, h: 0.18, fill: { color: q[3] } });
    }
  });

  // 里程碑时间线
  s.addText("里程碑（跨 Agent 交接 / @mention 驱动，写入 state.json 可审计）", {
    x: 0.55, y: 2.95, w: 8, h: 0.35, fontSize: 13, bold: true, color: C.white
  });
  const milestones = [
    ["TASK_SPEC_READY", "聚合完成"],
    ["ROOT_CAUSE_FOUND", "根因确认"],
    ["FIX_APPLIED", "修复落地"],
    ["TEST_PASSED", "测试通过"],
    ["RELEASE_OK", "发布确认"],
    ["RETROSPECT_DONE", "复盘闭合"],
  ];
  milestones.forEach((m, i) => {
    const x = 0.55 + i * 1.48;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x, y: 3.4, w: 1.34, h: 0.75, rectRadius: 0.08, fill: { color: C.off, transparency: 10 },
      line: { color: "334E68", width: 1 }
    });
    s.addText(m[0], { x, y: 3.5, w: 1.34, h: 0.3, fontSize: 8, bold: true, color: C.mint, align: "center" });
    s.addText(m[1], { x, y: 3.8, w: 1.34, h: 0.28, fontSize: 8.5, color: C.white, align: "center" });
    if (i < 5) {
      s.addShape(pres.shapes.RECTANGLE, { x: x + 1.36, y: 3.75, w: 0.12, h: 0.04, fill: { color: C.teal } });
    }
  });

  // 验证闸门 + 回滚（底部 2 列）
  s.addText("三条子原理落地", { x: 0.55, y: 4.35, w: 4, h: 0.35, fontSize: 13, bold: true, color: C.white });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.55, y: 4.72, w: 4.3, h: 0.6, fill: { color: C.teal, transparency: 55 }, line: { color: C.teal, width: 1 } });
  s.addText("自动化质量门禁：确定性测试/编译/静态分析当裁判，TEST_FAILED 打回 Fixer", {
    x: 0.7, y: 4.8, w: 4.0, h: 0.45, fontSize: 9.5, color: C.white, valign: "middle"
  });
  s.addShape(pres.shapes.RECTANGLE, { x: 5.1, y: 4.72, w: 4.4, h: 0.6, fill: { color: "7C6FD4", transparency: 55 }, line: { color: "7C6FD4", width: 1 } });
  s.addText("最小影响可回滚：灰度 + 金丝雀 + Saga 补偿，RELEASE_ROLLED_BACK 打回", {
    x: 5.25, y: 4.8, w: 4.1, h: 0.45, fontSize: 9.5, color: C.white, valign: "middle"
  });
})();

// ========== 6. Skill 工程体系（评审 25%）==========
(() => {
  const s = pres.addSlide();
  s.background = { color: C.off };
  s.addText("Skill 工程体系", { x: 0.55, y: 0.4, w: 3, h: 0.5, fontSize: 28, bold: true, color: C.navy });
  s.addText("三层 Skill 体系：可复用、可管理、可安全执行（对齐官方 9 字段规范）", { x: 0.55, y: 0.95, w: 8, h: 0.4, fontSize: 15, color: C.teal });

  // 三层结构（左）
  const layers = [
    ["L1 基座 Skill", "通用工程基础：repo-context / code-search / git-operations"],
    ["L2 领域 Skill", "研发闭环能力：issue-parsing / root-cause-analysis / impact-analysis / code-gen / test-generation"],
    ["L3 协同 Skill", "闭环收口：release-gate / retrospective / knowledge-rag / evidence-log"],
  ];
  layers.forEach((l, i) => {
    const y = 1.5 + i * 0.78;
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: 0.55, y, w: 4.6, h: 0.68, rectRadius: 0.08, fill: { color: i === 0 ? C.deep : i === 1 ? C.teal : C.navy }, shadow: mkShadow()
    });
    s.addText(l[0], { x: 0.72, y: y + 0.06, w: 4.2, h: 0.26, fontSize: 11.5, bold: true, color: C.white });
    s.addText(l[1], { x: 0.72, y: y + 0.34, w: 4.25, h: 0.3, fontSize: 8.5, color: C.ice });
  });

  // 右侧：9 字段规范
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.4, y: 1.5, w: 4.1, h: 2.5, rectRadius: 0.08, fill: { color: C.white }, line: { color: "D5DFEA", width: 1 }, shadow: mkShadow()
  });
  s.addText("每个 Skill 按官方 9 字段定义", { x: 5.6, y: 1.62, w: 3.7, h: 0.35, fontSize: 13, bold: true, color: C.navy });
  const fields = ["名称 · 用途", "输入输出", "调用条件", "依赖工具", "失败处理", "安全边界", "复用价值", "协同流程关系"];
  fields.forEach((f, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 5.6 + col * 1.85, y = 2.05 + row * 0.42;
    s.addShape(pres.shapes.RECTANGLE, { x, y, w: 1.75, h: 0.32, fill: { color: i % 2 === 0 ? "E8F1F8" : "F0FAF6" } });
    s.addText(f, { x, y, w: 1.75, h: 0.32, fontSize: 9.5, color: C.dark, align: "center", valign: "middle" });
  });

  // 底部：安全 + 确定性脚本
  s.addShape(pres.shapes.RECTANGLE, { x: 0.55, y: 4.35, w: 8.95, h: 0.55, fill: { color: "E8F1F8" } });
  s.addText("确定性脚本落地（官方缺失的差异价值）：check-patch-integrity（补丁完整性）/ verify_test_gate（测试闸门）→ 客观裁判，非 LLM 自评", {
    x: 0.7, y: 4.42, w: 8.6, h: 0.4, fontSize: 10.5, color: C.navy, valign: "middle"
  });
  s.addText("Skill 由 Manager 集中管理 · Worker 声明式挂载 · 安全边界注入（file_guard / tool_guard 沙箱守卫）", {
    x: 0.55, y: 5.05, w: 9, h: 0.35, fontSize: 11, italic: true, color: C.teal
  });
})();

// ========== 7. 差异化亮点：动态 Agent 团队 ==========
(() => {
  const s = pres.addSlide();
  s.background = { color: C.off };
  s.addText("差异化亮点", { x: 0.55, y: 0.4, w: 3, h: 0.5, fontSize: 28, bold: true, color: C.navy });
  s.addText("「AI 公司」式动态 Agent 团队 + 成员绩效评价", { x: 0.55, y: 0.95, w: 8, h: 0.4, fontSize: 15, color: C.teal });

  // 动态团队核心（左）
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.55, y: 1.5, w: 5.3, h: 3.0, rectRadius: 0.08, fill: { color: C.navy }, shadow: mkShadow()
  });
  s.addText("动态组建 / 招人 / 裁员", { x: 0.8, y: 1.65, w: 4.8, h: 0.4, fontSize: 16, bold: true, color: C.mint });
  const dyn = [
    ["按需招募", "新项目缺某职能 → 声明式创建新 Worker（无状态、可销毁）"],
    ["迅速协作", "新 Agent 通过 mcpServers + skills 立即与既有团队协作出结果"],
    ["合理裁员", "项目结束 / 角色不需要 → 移除 Worker，团队成本可控"],
    ["解决痛点", "技术栈和提示词不可能预先写死，广谱开发需动态扩展"],
  ];
  dyn.forEach((d, i) => {
    s.addText([
      { text: d[0] + "  ", options: { bold: true, color: C.mint } },
      { text: d[1], options: { color: C.ice } }
    ], { x: 0.8, y: 2.15 + i * 0.58, w: 4.8, h: 0.55, fontSize: 10.5, valign: "top", margin: 0 });
  });

  // 右侧：绩效评价
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 6.05, y: 1.5, w: 3.45, h: 3.0, rectRadius: 0.08, fill: { color: C.white }, line: { color: "D5DFEA", width: 1 }, shadow: mkShadow()
  });
  s.addText("成员绩效评价（HR 系统）", { x: 6.25, y: 1.62, w: 3.0, h: 0.35, fontSize: 13, bold: true, color: C.navy });
  const evals = [
    ["合格度", "客观 KPI 达标判定，确定性优先"],
    ["贡献度", "反事实归因（借鉴 C3 / Shapley），不删 Agent"],
    ["成长分", "沉淀知识被跨任务复用的次数（学习与成长）"],
  ];
  evals.forEach((e, i) => {
    s.addShape(pres.shapes.OVAL, { x: 6.25, y: 2.1 + i * 0.55, w: 0.4, h: 0.4, fill: { color: [C.mint, C.teal, C.deep][i] } });
    s.addText(e[0], { x: 6.75, y: 2.08 + i * 0.55, w: 2.5, h: 0.28, fontSize: 11, bold: true, color: C.navy });
    s.addText(e[1], { x: 6.75, y: 2.34 + i * 0.55, w: 2.55, h: 0.26, fontSize: 8.5, color: C.gray });
  });
  s.addText("综合分 = 0.5 合格 + 0.35 贡献 + 0.15 成长", {
    x: 6.25, y: 3.78, w: 3.05, h: 0.3, fontSize: 9.5, bold: true, color: C.teal
  });
  s.addText("治理：留任 / 培训 / 降级 / 裁员 的客观依据", {
    x: 6.25, y: 4.08, w: 3.05, h: 0.28, fontSize: 8.5, color: C.gray
  });

  s.addText("研究依据：AgentInit / AgentVerse / MetaGPT / ChatDev / CoMAS 等（已核实的 arXiv 引用）", {
    x: 0.55, y: 4.7, w: 9, h: 0.35, fontSize: 11, italic: true, color: C.teal
  });
  s.addText("确定性状态机 · 确定性验证闸门 · 上下文工程 · 成员评价（含知识复用成长分）—— 官方缺失的差异价值，已嵌入官方框架", {
    x: 0.55, y: 5.05, w: 9, h: 0.35, fontSize: 11, italic: true, color: C.teal
  });
})();

// ========== 8. 工程落地：真实闭环实测（评审 20%）==========
(() => {
  const s = pres.addSlide();
  s.background = { color: C.navy };
  s.addText("工程落地 · 真实闭环实测", { x: 0.55, y: 0.4, w: 5, h: 0.5, fontSize: 28, bold: true, color: C.white });
  s.addText("在官方 AgentTeams 平台真实驱动 6 Worker 跑通完整 PDCA 闭环（不是 mock）", { x: 0.55, y: 0.95, w: 8, h: 0.4, fontSize: 15, color: C.ice });

  // 左侧：里程碑时间线（真实数据）
  s.addText("闭环里程碑时间线（真实测量）", { x: 0.55, y: 1.5, w: 5, h: 0.35, fontSize: 14, bold: true, color: C.mint });
  const tl = [
    ["0s", "TASK_SPEC_READY", "aggregator", "P 计划"],
    ["0s", "ROOT_CAUSE_FOUND", "rootcause", "D 执行"],
    ["0-45s", "FIX_APPLIED", "fixer · 10/10 测试", "D 执行"],
    ["0-45s", "TEST_PASSED", "tester", "C 检查"],
    ["60s", "RELEASE_OK", "releaser", "A 处置"],
    ["181s", "RETROSPECT_DONE", "retrospector", "A 处置 · 闭合"],
  ];
  tl.forEach((t, i) => {
    const y = 1.95 + i * 0.5;
    s.addShape(pres.shapes.OVAL, { x: 0.7, y: y + 0.03, w: 0.22, h: 0.22, fill: { color: C.mint } });
    s.addText(t[0], { x: 0.62, y, w: 1.0, h: 0.28, fontSize: 9, bold: true, color: C.mint, align: "center" });
    s.addText(t[1], { x: 1.7, y, w: 2.5, h: 0.28, fontSize: 11, bold: true, color: C.white });
    s.addText(t[2] + " · " + t[3], { x: 4.3, y, w: 1.8, h: 0.28, fontSize: 8.5, color: C.ice });
  });

  // 右侧：结果卡片
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 6.4, y: 1.5, w: 3.1, h: 3.5, rectRadius: 0.1, fill: { color: C.deep, transparency: 30 }, line: { color: C.mint, width: 1.5 }, shadow: mkShadow()
  });
  s.addText("真实产出", { x: 6.6, y: 1.66, w: 2.7, h: 0.35, fontSize: 14, bold: true, color: C.mint });
  const results = [
    ["181s", "完整闭环闭合"],
    ["10/10", "自动化测试通过"],
    ["400", "空用户名（不再 500）"],
    ["6", "Worker 真实接力"],
  ];
  results.forEach((r, i) => {
    const y = 2.15 + i * 0.68;
    s.addText(r[0], { x: 6.6, y, w: 1.2, h: 0.45, fontSize: 20, bold: true, color: C.white });
    s.addText(r[1], { x: 7.85, y: y + 0.08, w: 1.6, h: 0.35, fontSize: 10, color: C.ice, valign: "middle" });
  });
  s.addText("三层修复：入口校验 + 空值防护 + 异常映射；交付物已推送 MinIO", {
    x: 6.6, y: 4.72, w: 2.7, h: 0.28, fontSize: 8.5, color: C.ice
  });

  // 底部：三支柱
  s.addText("工程三大支柱：可观测（Trace/Log/Metrics）· 沙箱安全（file_guard/tool_guard 守卫）· 声明式工具链（MCP + Skill scripts）", {
    x: 0.55, y: 5.1, w: 9, h: 0.35, fontSize: 11, italic: true, color: C.ice
  });
})();

// ========== 9. 三层架构总览 ==========
(() => {
  const s = pres.addSlide();
  s.background = { color: C.off };
  s.addText("系统架构总览", { x: 0.55, y: 0.4, w: 4, h: 0.5, fontSize: 28, bold: true, color: C.navy });
  s.addText("基于 AgentTeams 原生能力外包一层确定性调度", { x: 0.55, y: 0.95, w: 8, h: 0.4, fontSize: 15, color: C.teal });

  const rows = [
    ["L3 · 平台集成", "AgentTeams（agt CLI + Matrix 房间协议）· Human 介入审批 · 沙箱", C.navy, C.mint],
    ["L2 · 标准接口层", "AgentTeamsLoop 调度引擎 · AgentInterface · AgentBus/EventBus · 6 Worker", C.deep, C.white],
    ["L1 · 调度核心升级", "IterativeWorker 迭代 · 动态预算分配 · 语义记忆检索 · 异步并行派单", C.teal, C.white],
    ["共享协议层", "state.py 确定性状态机 · evaluation.py 评价 · knowledge_tracker.py 知识复用统计 · context.py 上下文", C.off, C.navy],
  ];
  rows.forEach((r, i) => {
    const y = 1.45 + i * 0.95;
    // 左层名
    s.addShape(pres.shapes.RECTANGLE, { x: 0.55, y, w: 2.0, h: 0.78, fill: { color: r[2] } });
    s.addText(r[0], { x: 0.55, y, w: 2.0, h: 0.78, fontSize: 12, bold: true, color: r[3], align: "center", valign: "middle" });
    // 右内容
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: 2.75, y, w: 6.7, h: 0.78, rectRadius: 0.06, fill: { color: C.white }, line: { color: "D5DFEA", width: 1 }
    });
    s.addText(r[1], { x: 2.95, y, w: 6.3, h: 0.78, fontSize: 10.5, color: C.dark, valign: "middle" });
    // 连接箭头
    if (i < 3) {
      s.addShape(pres.shapes.RECTANGLE, { x: 5.9, y: y + 0.78, w: 0.06, h: 0.17, fill: { color: C.teal } });
    }
  });

  s.addText("agentteams_loop.py 本就是 AgentTeams 原生（非另起炉灶），确定性层是官方缺失的增量价值", {
    x: 0.55, y: 5.15, w: 9, h: 0.35, fontSize: 11, italic: true, color: C.teal
  });
})();

// ========== 10. 结尾（深色）+ 开源 ==========
(() => {
  const s = pres.addSlide();
  s.background = { color: C.navy };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.12, fill: { color: C.mint } });
  s.addText("一个能真实跑通的", { x: 0.7, y: 1.5, w: 8.6, h: 0.6, fontSize: 30, color: C.ice, align: "center" });
  s.addText("软件研发多 Agent 团队", { x: 0.7, y: 2.15, w: 8.6, h: 0.8, fontSize: 42, bold: true, color: C.mint, align: "center" });

  s.addText("以 AgentTeams 为唯一协同基点 · 覆盖官方 8 环节闭环 · 6 Worker 真实跑通 · 确定性可验证 · 知识可沉淀", {
    x: 0.7, y: 3.4, w: 8.6, h: 0.5, fontSize: 14, color: C.white, align: "center"
  });

  // 开源计划
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 2.3, y: 4.15, w: 5.4, h: 0.5, rectRadius: 0.1, fill: { color: C.teal, transparency: 30 }, line: { color: C.mint, width: 1 }
  });
  s.addText("开源承诺：确定性调度层将贡献回 AgentTeams 开源生态", {
    x: 2.3, y: 4.15, w: 5.4, h: 0.5, fontSize: 11.5, color: C.white, align: "center", valign: "middle"
  });

  s.addText("GOAI 世界人工智能开源大赛 · 赛道三 · 谢谢", {
    x: 0.7, y: 5.0, w: 8.6, h: 0.4, fontSize: 13, color: C.gray, align: "center", charSpacing: 2
  });
})();

// 输出
const outFile = "GOAI-赛道三-方案.pptx";
pres.writeFile({ fileName: outFile }).then(() => {
  console.log("✅ 已生成: " + outFile);
}).catch(e => console.error("❌ 失败: " + e));
