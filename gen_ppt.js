const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10" x 5.625"
pres.author = "AgentCollab Team";
pres.title = "AgentCollab 银行创新项目答辩";

// ── Color palette (banking professional) ──────────────────────────
const C = {
  NAVY:       "1B2845",
  NAVY_DEEP:  "121B33",
  STEEL:      "3D5A80",
  GOLD:       "D4A843",
  GOLD_DARK:  "B8902F",
  LIGHT_BG:   "F0F2F5",
  WHITE:      "FFFFFF",
  TEXT_DARK:  "1A1A2E",
  TEXT_MUTED: "6B7280",
  TEXT_LIGHT: "E8EAF0",
  DANGER:     "C0392B",
  DANGER_BG:  "FDEDEC",
  SUCCESS:    "1E8449",
  SUCCESS_BG: "EAFAF1",
  GOLD_BG:    "FEF9E7",
  STEEL_BG:   "E8EDF5",
  BORDER:     "D1D5DB",
};

// ── Fonts ──────────────────────────────────────────────────────────
const FH = "Georgia";   // header font
const FB = "Calibri";   // body font

// ── Helpers ────────────────────────────────────────────────────────

/** Add a content card with optional left accent bar */
function addCard(slide, x, y, w, h, opts = {}) {
  const accentColor = opts.accent || C.GOLD;
  const bgColor = opts.bg || C.WHITE;
  slide.addShape(pres.shapes.RECTANGLE, {
    x, y, w, h,
    fill: { color: bgColor },
    line: { color: C.BORDER, width: 0.5 },
    shadow: { type: "outer", color: "000000", blur: 4, offset: 1.5, angle: 90, opacity: 0.08 },
  });
  if (opts.accent !== false) {
    slide.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 0.06, h,
      fill: { color: accentColor },
      line: { width: 0 },
    });
  }
}

/** Add page number */
function addPageNum(slide, num, dark = false) {
  slide.addText(String(num), {
    x: 9.2, y: 5.2, w: 0.6, h: 0.3,
    fontSize: 9, fontFace: FB, color: dark ? "A0A8C0" : C.TEXT_MUTED,
    align: "right", valign: "middle", margin: 0,
  });
}

/** Add slide title on light slides */
function addTitle(slide, title, subtitle) {
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.GOLD }, line: { width: 0 },
  });
  slide.addText(title, {
    x: 0.5, y: 0.25, w: 9, h: 0.5,
    fontSize: 24, fontFace: FH, bold: true, color: C.NAVY,
    align: "left", valign: "middle", margin: 0,
  });
  if (subtitle) {
    slide.addText(subtitle, {
      x: 0.5, y: 0.72, w: 9, h: 0.3,
      fontSize: 12, fontFace: FB, color: C.TEXT_MUTED,
      align: "left", valign: "middle", margin: 0,
    });
  }
}

// ════════════════════════════════════════════════════════════════════
// Slide 1: Title
// ════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.NAVY };

  // Gold accent bar at bottom
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.5, w: 10, h: 0.125, fill: { color: C.GOLD }, line: { width: 0 },
  });

  // Decorative circles
  s.addShape(pres.shapes.OVAL, {
    x: 7.5, y: -1, w: 4, h: 4,
    fill: { color: C.STEEL, transparency: 80 }, line: { width: 0 },
  });
  s.addShape(pres.shapes.OVAL, {
    x: 8.2, y: 3, w: 3, h: 3,
    fill: { color: C.GOLD, transparency: 88 }, line: { width: 0 },
  });

  s.addText("AgentCollab", {
    x: 0.8, y: 1.5, w: 8.5, h: 0.8,
    fontSize: 40, fontFace: FH, bold: true, color: C.WHITE,
    align: "left", valign: "middle", margin: 0, charSpacing: 2,
  });

  s.addText("面向银行研发的可控 AI 协作治理平台", {
    x: 0.8, y: 2.35, w: 8.5, h: 0.5,
    fontSize: 18, fontFace: FB, color: C.GOLD,
    align: "left", valign: "middle", margin: 0,
  });

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.85, y: 3.1, w: 2.5, h: 0.03, fill: { color: C.GOLD }, line: { width: 0 },
  });

  s.addText("让 AI 提升研发效率，同时确保每一次修改可控、可审、可追溯、可回退", {
    x: 0.8, y: 3.3, w: 7.5, h: 0.4,
    fontSize: 13, fontFace: FB, color: C.TEXT_LIGHT,
    align: "left", valign: "middle", margin: 0, italic: true,
  });

  s.addText("银行创新项目答辩", {
    x: 0.8, y: 4.6, w: 4, h: 0.35,
    fontSize: 11, fontFace: FB, color: "A0A8C0",
    align: "left", valign: "middle", margin: 0,
  });
}

// ════════════════════════════════════════════════════════════════════
// Slide 2: AI 进入银行研发 — 无法回答的 6 个问题
// ════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.NAVY };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.GOLD }, line: { width: 0 },
  });

  s.addText("通用 AI 编程工具进入银行研发场景", {
    x: 0.5, y: 0.3, w: 9, h: 0.5,
    fontSize: 22, fontFace: FH, bold: true, color: C.WHITE,
    align: "left", valign: "middle", margin: 0,
  });
  s.addText("以下 6 个问题，传统工具无法回答", {
    x: 0.5, y: 0.8, w: 9, h: 0.35,
    fontSize: 13, fontFace: FB, color: C.GOLD, italic: true,
    align: "left", valign: "middle", margin: 0,
  });

  const questions = [
    "谁向 AI 提出了什么要求？",
    "AI 查看和修改了哪些文件？",
    "AI 为什么做出这项修改？",
    "修改经过了哪些安全检查？",
    "谁审查并批准了这项变更？",
    "出现问题时能否快速定位和恢复？",
  ];

  questions.forEach((q, i) => {
    const col = i < 3 ? 0 : 1;
    const row = i % 3;
    const x = 0.6 + col * 4.6;
    const y = 1.5 + row * 1.15;

    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 4.3, h: 0.95,
      fill: { color: C.NAVY_DEEP },
      line: { color: C.STEEL, width: 0.5 },
      shadow: { type: "outer", color: "000000", blur: 6, offset: 2, angle: 90, opacity: 0.2 },
    });
    // Number circle
    s.addShape(pres.shapes.OVAL, {
      x: x + 0.2, y: y + 0.22, w: 0.5, h: 0.5,
      fill: { color: C.GOLD }, line: { width: 0 },
    });
    s.addText(String(i + 1), {
      x: x + 0.2, y: y + 0.22, w: 0.5, h: 0.5,
      fontSize: 18, fontFace: FH, bold: true, color: C.NAVY,
      align: "center", valign: "middle", margin: 0,
    });
    s.addText(q, {
      x: x + 0.85, y: y, w: 3.3, h: 0.95,
      fontSize: 13, fontFace: FB, color: C.TEXT_LIGHT,
      align: "left", valign: "middle", margin: 0,
    });
  });

  s.addText("如果无法回答上述问题，AI 生成的代码就很难直接进入银行研发流程", {
    x: 0.5, y: 5.0, w: 9, h: 0.3,
    fontSize: 11, fontFace: FB, color: "A0A8C0", italic: true,
    align: "center", valign: "middle", margin: 0,
  });
  addPageNum(s, 2, true);
}

// ════════════════════════════════════════════════════════════════════
// Slide 3: 五大核心痛点
// ════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.LIGHT_BG };
  addTitle(s, "银行研发场景中的五大核心痛点");

  const pains = [
    { t: "过程治理缺失", d: "通用 AI 工具关注效率，缺少指令记录、执行追踪和审批留痕" },
    { t: "审查效率较低", d: "人工逐行检查，重复劳动多，质量受个人经验影响" },
    { t: "安全规范散落", d: "制度文件、历史缺陷、个人经验难以统一复用" },
    { t: "AI 修改不可控", d: "AI 直接改主分支，多任务覆盖，未审查代码进入正式版本" },
    { t: "责任链断裂", d: "需求、代码、审查、审批分散在不同系统，难以追溯" },
  ];

  // Layout: 5 cards in a row
  const cardW = 1.72;
  const gap = 0.12;
  const startX = (10 - (cardW * 5 + gap * 4)) / 2;

  pains.forEach((p, i) => {
    const x = startX + i * (cardW + gap);
    const y = 1.35;
    const h = 3.4;

    // Card
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: cardW, h,
      fill: { color: C.WHITE },
      line: { color: C.BORDER, width: 0.5 },
      shadow: { type: "outer", color: "000000", blur: 4, offset: 1.5, angle: 90, opacity: 0.08 },
    });
    // Top accent
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: cardW, h: 0.06, fill: { color: C.DANGER }, line: { width: 0 },
    });
    // Number
    s.addText(String(i + 1), {
      x, y: y + 0.25, w: cardW, h: 0.6,
      fontSize: 32, fontFace: FH, bold: true, color: C.DANGER,
      align: "center", valign: "middle", margin: 0,
    });
    // Title
    s.addText(p.t, {
      x: x + 0.1, y: y + 0.9, w: cardW - 0.2, h: 0.5,
      fontSize: 14, fontFace: FB, bold: true, color: C.TEXT_DARK,
      align: "center", valign: "middle", margin: 0,
    });
    // Divider
    s.addShape(pres.shapes.RECTANGLE, {
      x: x + cardW / 2 - 0.25, y: y + 1.45, w: 0.5, h: 0.02,
      fill: { color: C.BORDER }, line: { width: 0 },
    });
    // Description
    s.addText(p.d, {
      x: x + 0.15, y: y + 1.6, w: cardW - 0.3, h: 1.6,
      fontSize: 10.5, fontFace: FB, color: C.TEXT_MUTED,
      align: "center", valign: "top", margin: 0, lineSpacingMultiple: 1.3,
    });
  });

  addPageNum(s, 3);
}

// ════════════════════════════════════════════════════════════════════
// Slide 4: 痛点详解 — 审查效率与安全规范
// ════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.LIGHT_BG };
  addTitle(s, "痛点详解", "人工审查效率低 × 安全规范依赖个人记忆");

  // Left card
  {
    const x = 0.5, y = 1.35, w = 4.4, h = 3.6;
    addCard(s, x, y, w, h, { accent: C.DANGER });
    s.addText("人工代码审查效率较低", {
      x: x + 0.25, y: y + 0.2, w: w - 0.4, h: 0.4,
      fontSize: 15, fontFace: FB, bold: true, color: C.DANGER, margin: 0,
    });
    const items = [
      "重复性检查耗费大量时间",
      "审查质量受个人经验影响",
      "安全问题可能被遗漏",
      "多人审查意见难以统一汇总",
      "项目规模扩大后审查压力持续增加",
    ];
    items.forEach((it, i) => {
      s.addShape(pres.shapes.OVAL, {
        x: x + 0.3, y: y + 0.85 + i * 0.55, w: 0.12, h: 0.12,
        fill: { color: C.DANGER }, line: { width: 0 },
      });
      s.addText(it, {
        x: x + 0.55, y: y + 0.75 + i * 0.55, w: w - 0.8, h: 0.4,
        fontSize: 12, fontFace: FB, color: C.TEXT_DARK, margin: 0, valign: "middle",
      });
    });
  }

  // Right card
  {
    const x = 5.1, y = 1.35, w = 4.4, h = 3.6;
    addCard(s, x, y, w, h, { accent: C.DANGER });
    s.addText("安全规范依赖个人记忆", {
      x: x + 0.25, y: y + 0.2, w: w - 0.4, h: 0.4,
      fontSize: 15, fontFace: FB, bold: true, color: C.DANGER, margin: 0,
    });
    s.addText("银行内部的安全知识散落在多处，难以统一复用", {
      x: x + 0.25, y: y + 0.6, w: w - 0.4, h: 0.3,
      fontSize: 11, fontFace: FB, color: C.TEXT_MUTED, italic: true, margin: 0,
    });
    const sources = ["制度文件", "项目文档", "历史缺陷记录", "审查人员个人经验", "聊天记录和会议纪要"];
    sources.forEach((src, i) => {
      const sy = y + 1.1 + i * 0.48;
      s.addShape(pres.shapes.RECTANGLE, {
        x: x + 0.3, y: sy, w: 0.35, h: 0.35,
        fill: { color: C.DANGER_BG }, line: { width: 0 },
      });
      s.addText(String(i + 1), {
        x: x + 0.3, y: sy, w: 0.35, h: 0.35,
        fontSize: 12, fontFace: FB, bold: true, color: C.DANGER,
        align: "center", valign: "middle", margin: 0,
      });
      s.addText(src, {
        x: x + 0.8, y: sy, w: w - 1.1, h: 0.35,
        fontSize: 12, fontFace: FB, color: C.TEXT_DARK, margin: 0, valign: "middle",
      });
    });
    s.addText("新员工难以快速掌握，同类问题在不同项目中重复出现", {
      x: x + 0.25, y: y + 3.15, w: w - 0.4, h: 0.3,
      fontSize: 10.5, fontFace: FB, color: C.TEXT_MUTED, italic: true, margin: 0,
    });
  }

  addPageNum(s, 4);
}

// ════════════════════════════════════════════════════════════════════
// Slide 5: 痛点详解 — 不可控风险与责任链断裂
// ════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.LIGHT_BG };
  addTitle(s, "痛点详解", "AI 修改不可控 × 变更责任链不完整");

  // Left card
  {
    const x = 0.5, y = 1.35, w = 4.4, h = 3.6;
    addCard(s, x, y, w, h, { accent: C.DANGER });
    s.addText("AI 修改代码存在不可控风险", {
      x: x + 0.25, y: y + 0.2, w: w - 0.4, h: 0.4,
      fontSize: 15, fontFace: FB, bold: true, color: C.DANGER, margin: 0,
    });
    s.addText("如果 AI 可以直接修改主分支", {
      x: x + 0.25, y: y + 0.6, w: w - 0.4, h: 0.3,
      fontSize: 11, fontFace: FB, color: C.TEXT_MUTED, italic: true, margin: 0,
    });
    const risks = [
      "多个任务相互覆盖",
      "未审查代码进入正式版本",
      "错误修改影响其他开发人员",
      "安全问题随代码一同发布",
      "出现故障时难以恢复",
    ];
    risks.forEach((r, i) => {
      s.addShape(pres.shapes.OVAL, {
        x: x + 0.3, y: y + 1.15 + i * 0.5, w: 0.12, h: 0.12,
        fill: { color: C.DANGER }, line: { width: 0 },
      });
      s.addText(r, {
        x: x + 0.55, y: y + 1.05 + i * 0.5, w: w - 0.8, h: 0.4,
        fontSize: 12, fontFace: FB, color: C.TEXT_DARK, margin: 0, valign: "middle",
      });
    });
  }

  // Right card — responsibility chain
  {
    const x = 5.1, y = 1.35, w = 4.4, h = 3.6;
    addCard(s, x, y, w, h, { accent: C.DANGER });
    s.addText("变更责任链不完整", {
      x: x + 0.25, y: y + 0.2, w: w - 0.4, h: 0.4,
      fontSize: 15, fontFace: FB, bold: true, color: C.DANGER, margin: 0,
    });
    s.addText("传统工具数据分散在不同系统中", {
      x: x + 0.25, y: y + 0.6, w: w - 0.4, h: 0.3,
      fontSize: 11, fontFace: FB, color: C.TEXT_MUTED, italic: true, margin: 0,
    });

    // Chain visualization
    const chain = ["谁提出需求", "AI 执行什么", "发现哪些风险", "谁作审批", "产生什么影响"];
    const chainY = y + 1.2;
    const chainH = 0.4;
    const itemW = (w - 0.5) / chain.length;
    chain.forEach((item, i) => {
      const cx = x + 0.25 + i * itemW;
      s.addShape(pres.shapes.RECTANGLE, {
        x: cx, y: chainY, w: itemW - 0.08, h: chainH,
        fill: { color: C.DANGER_BG }, line: { color: C.DANGER, width: 0.5 },
      });
      s.addText(item, {
        x: cx, y: chainY, w: itemW - 0.08, h: chainH,
        fontSize: 9.5, fontFace: FB, bold: true, color: C.DANGER,
        align: "center", valign: "middle", margin: 0,
      });
      if (i < chain.length - 1) {
        s.addText("→", {
          x: cx + itemW - 0.12, y: chainY, w: 0.2, h: chainH,
          fontSize: 12, fontFace: FB, color: C.BORDER,
          align: "center", valign: "middle", margin: 0,
        });
      }
    });

    s.addText("难以快速还原完整变更过程", {
      x: x + 0.25, y: chainY + chainH + 0.3, w: w - 0.4, h: 0.3,
      fontSize: 12, fontFace: FB, color: C.DANGER, bold: true, margin: 0, align: "center",
    });
    s.addText("问题定位和责任追溯效率低下，审计合规难度大", {
      x: x + 0.25, y: chainY + chainH + 0.65, w: w - 0.4, h: 0.4,
      fontSize: 11, fontFace: FB, color: C.TEXT_MUTED, margin: 0, align: "center", italic: true,
    });
  }

  addPageNum(s, 5);
}

// ════════════════════════════════════════════════════════════════════
// Slide 6: 解决方案 — 核心闭环
// ════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.NAVY };

  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.GOLD }, line: { width: 0 },
  });

  s.addText("我们的解决方案", {
    x: 0.5, y: 0.25, w: 9, h: 0.5,
    fontSize: 24, fontFace: FH, bold: true, color: C.WHITE,
    align: "left", valign: "middle", margin: 0,
  });
  s.addText("让 AI 在银行可控的研发治理框架下安全工作", {
    x: 0.5, y: 0.72, w: 9, h: 0.3,
    fontSize: 13, fontFace: FB, color: C.GOLD, italic: true,
    align: "left", valign: "middle", margin: 0,
  });

  // Flow: 7 steps
  const steps = [
    { t: "创建任务", d: "人工提交研发需求" },
    { t: "代码生成", d: "Agent 分析并生成代码" },
    { t: "代码审查", d: "质量 + 安全双重检查" },
    { t: "安全门禁", d: "确定性工具自动扫描" },
    { t: "多人复核", d: "经办—复核分离决策" },
    { t: "合并记录", d: "审批后合并并归档" },
    { t: "审计追溯", d: "全链路可查可回退" },
  ];

  const flowY = 1.6;
  const flowH = 2.6;
  const stepW = 1.2;
  const arrowW = 0.15;
  const totalW = stepW * steps.length + arrowW * (steps.length - 1);
  const startX = (10 - totalW) / 2;

  steps.forEach((st, i) => {
    const x = startX + i * (stepW + arrowW);

    // Card
    s.addShape(pres.shapes.RECTANGLE, {
      x, y: flowY, w: stepW, h: flowH,
      fill: { color: C.NAVY_DEEP },
      line: { color: C.STEEL, width: 0.5 },
      shadow: { type: "outer", color: "000000", blur: 6, offset: 2, angle: 90, opacity: 0.2 },
    });
    // Top accent
    s.addShape(pres.shapes.RECTANGLE, {
      x, y: flowY, w: stepW, h: 0.06,
      fill: { color: i === 0 ? C.GOLD : C.STEEL }, line: { width: 0 },
    });
    // Number circle
    s.addShape(pres.shapes.OVAL, {
      x: x + stepW / 2 - 0.3, y: flowY + 0.3, w: 0.6, h: 0.6,
      fill: { color: i === 0 ? C.GOLD : C.STEEL }, line: { width: 0 },
    });
    s.addText(String(i + 1), {
      x: x + stepW / 2 - 0.3, y: flowY + 0.3, w: 0.6, h: 0.6,
      fontSize: 22, fontFace: FH, bold: true, color: C.WHITE,
      align: "center", valign: "middle", margin: 0,
    });
    // Title
    s.addText(st.t, {
      x: x + 0.05, y: flowY + 1.05, w: stepW - 0.1, h: 0.4,
      fontSize: 12, fontFace: FB, bold: true, color: C.GOLD,
      align: "center", valign: "middle", margin: 0,
    });
    // Description
    s.addText(st.d, {
      x: x + 0.08, y: flowY + 1.5, w: stepW - 0.16, h: 0.9,
      fontSize: 9.5, fontFace: FB, color: C.TEXT_LIGHT,
      align: "center", valign: "top", margin: 0, lineSpacingMultiple: 1.2,
    });

    // Arrow
    if (i < steps.length - 1) {
      s.addText("→", {
        x: x + stepW - 0.02, y: flowY + flowH / 2 - 0.2, w: arrowW + 0.05, h: 0.4,
        fontSize: 16, fontFace: FB, color: C.GOLD,
        align: "center", valign: "middle", margin: 0,
      });
    }
  });

  s.addText("核心不是让 AI 自动写代码，而是把 AI 能力嵌入银行可控的研发治理流程", {
    x: 0.5, y: 4.65, w: 9, h: 0.4,
    fontSize: 12, fontFace: FB, color: C.GOLD, italic: true,
    align: "center", valign: "middle", margin: 0,
  });

  addPageNum(s, 6, true);
}

// ════════════════════════════════════════════════════════════════════
// Slide 7: 创新点 1 — 多 Agent 职责分离
// ════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.LIGHT_BG };
  addTitle(s, "创新点 1：多 Agent 职责分离", "不是让一个模型同时写代码并给自己打分，而是通过职责分离形成交叉检查");

  const agents = [
    { t: "代码生成 Agent", d: "分析任务并生成或修改代码", color: C.STEEL, bg: C.STEEL_BG, num: "01" },
    { t: "代码审查 Agent", d: "检查逻辑、可读性、规范和潜在 Bug", color: C.SUCCESS, bg: C.SUCCESS_BG, num: "02" },
    { t: "安全审查 Agent", d: "检查注入、越权、敏感信息和不安全配置", color: C.DANGER, bg: C.DANGER_BG, num: "03" },
    { t: "汇总 Agent", d: "汇总审查结论并按严重程度输出报告", color: C.GOLD_DARK, bg: C.GOLD_BG, num: "04" },
  ];

  const cardW = 2.1, cardH = 2.6, gap = 0.2;
  const startX = (10 - (cardW * 4 + gap * 3)) / 2;
  const cardY = 1.55;

  agents.forEach((a, i) => {
    const x = startX + i * (cardW + gap);

    s.addShape(pres.shapes.RECTANGLE, {
      x, y: cardY, w: cardW, h: cardH,
      fill: { color: C.WHITE },
      line: { color: C.BORDER, width: 0.5 },
      shadow: { type: "outer", color: "000000", blur: 4, offset: 1.5, angle: 90, opacity: 0.08 },
    });
    // Top accent
    s.addShape(pres.shapes.RECTANGLE, {
      x, y: cardY, w: cardW, h: 0.06, fill: { color: a.color }, line: { width: 0 },
    });
    // Number bg
    s.addShape(pres.shapes.RECTANGLE, {
      x: x + 0.2, y: cardY + 0.3, w: 0.7, h: 0.45,
      fill: { color: a.bg }, line: { width: 0 },
    });
    s.addText(a.num, {
      x: x + 0.2, y: cardY + 0.3, w: 0.7, h: 0.45,
      fontSize: 16, fontFace: FH, bold: true, color: a.color,
      align: "center", valign: "middle", margin: 0,
    });
    // Title
    s.addText(a.t, {
      x: x + 0.2, y: cardY + 0.95, w: cardW - 0.4, h: 0.5,
      fontSize: 13, fontFace: FB, bold: true, color: C.TEXT_DARK,
      align: "left", valign: "middle", margin: 0,
    });
    // Description
    s.addText(a.d, {
      x: x + 0.2, y: cardY + 1.5, w: cardW - 0.4, h: 0.9,
      fontSize: 11, fontFace: FB, color: C.TEXT_MUTED,
      align: "left", valign: "top", margin: 0, lineSpacingMultiple: 1.3,
    });
  });

  // Bottom insight bar
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 4.45, w: 9, h: 0.6,
    fill: { color: C.GOLD_BG }, line: { width: 0 },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 4.45, w: 0.06, h: 0.6, fill: { color: C.GOLD }, line: { width: 0 },
  });
  s.addText("创新重点不是模型数量，而是通过职责分离让不同 Agent 从不同角度交叉检查，再由人工作出最终决定", {
    x: 0.7, y: 4.45, w: 8.6, h: 0.6,
    fontSize: 11.5, fontFace: FB, color: C.GOLD_DARK, italic: true,
    align: "left", valign: "middle", margin: 0,
  });

  addPageNum(s, 7);
}

// ════════════════════════════════════════════════════════════════════
// Slide 8: 创新点 2 — AI 与人工协同决策
// ════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.LIGHT_BG };
  addTitle(s, "创新点 2：AI 与人工协同决策", "与银行业务中的「经办—复核」思想具有较高契合度");

  // Left: AI 职责
  {
    const x = 0.5, y = 1.45, w = 4.2, h = 2.6;
    addCard(s, x, y, w, h, { accent: C.STEEL });
    s.addText("AI 职责", {
      x: x + 0.25, y: y + 0.2, w: w - 0.4, h: 0.4,
      fontSize: 15, fontFace: FB, bold: true, color: C.STEEL, margin: 0,
    });
    const aiTasks = ["生成代码", "检查逻辑与规范", "扫描安全风险", "汇总审查报告", "提供修改建议"];
    aiTasks.forEach((t, i) => {
      s.addShape(pres.shapes.OVAL, {
        x: x + 0.3, y: y + 0.85 + i * 0.42, w: 0.1, h: 0.1,
        fill: { color: C.STEEL }, line: { width: 0 },
      });
      s.addText(t, {
        x: x + 0.5, y: y + 0.75 + i * 0.42, w: w - 0.7, h: 0.35,
        fontSize: 12, fontFace: FB, color: C.TEXT_DARK, margin: 0, valign: "middle",
      });
    });
  }

  // Center: 协同
  {
    const cx = 4.725, cy = 2.275;
    s.addShape(pres.shapes.OVAL, {
      x: cx, y: cy, w: 0.55, h: 0.55,
      fill: { color: C.GOLD }, line: { width: 0 },
    });
    s.addText("协同", {
      x: cx, y: cy, w: 0.55, h: 0.55,
      fontSize: 11, fontFace: FB, bold: true, color: C.NAVY,
      align: "center", valign: "middle", margin: 0,
    });
  }

  // Right: 人工职责
  {
    const x = 5.3, y = 1.45, w = 4.2, h = 2.6;
    addCard(s, x, y, w, h, { accent: C.SUCCESS });
    s.addText("人工职责", {
      x: x + 0.25, y: y + 0.2, w: w - 0.4, h: 0.4,
      fontSize: 15, fontFace: FB, bold: true, color: C.SUCCESS, margin: 0,
    });
    const humanTasks = ["指定复核人员", "设置法定通过人数", "配置驳回一票否决", "填写驳回原因", "最终审批决策"];
    humanTasks.forEach((t, i) => {
      s.addShape(pres.shapes.OVAL, {
        x: x + 0.3, y: y + 0.85 + i * 0.42, w: 0.1, h: 0.1,
        fill: { color: C.SUCCESS }, line: { width: 0 },
      });
      s.addText(t, {
        x: x + 0.5, y: y + 0.75 + i * 0.42, w: w - 0.7, h: 0.35,
        fontSize: 12, fontFace: FB, color: C.TEXT_DARK, margin: 0, valign: "middle",
      });
    });
  }

  // Bottom: key principle
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 4.3, w: 9, h: 0.7,
    fill: { color: C.NAVY }, line: { width: 0 },
  });
  s.addText("未经人工批准的代码不能进入主分支", {
    x: 0.5, y: 4.3, w: 9, h: 0.7,
    fontSize: 15, fontFace: FH, bold: true, color: C.GOLD,
    align: "center", valign: "middle", margin: 0,
  });

  addPageNum(s, 8);
}

// ════════════════════════════════════════════════════════════════════
// Slide 9: 创新点 3 — 隔离式代码执行
// ════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.LIGHT_BG };
  addTitle(s, "创新点 3：隔离式代码执行", "每项任务都在独立 Git 分支和工作树中执行");

  // Branch visualization (left side)
  {
    const baseX = 0.7, baseY = 1.6;
    // Master branch line
    s.addShape(pres.shapes.RECTANGLE, {
      x: baseX, y: baseY + 1.5, w: 4.2, h: 0.08,
      fill: { color: C.NAVY }, line: { width: 0 },
    });
    s.addShape(pres.shapes.OVAL, {
      x: baseX + 4.0, y: baseY + 1.4, w: 0.28, h: 0.28,
      fill: { color: C.NAVY }, line: { width: 0 },
    });
    s.addText("主分支 master", {
      x: baseX, y: baseY + 1.65, w: 4.2, h: 0.3,
      fontSize: 11, fontFace: FB, bold: true, color: C.NAVY,
      align: "center", valign: "middle", margin: 0,
    });

    // Task branches
    const tasks = [
      { label: "任务 A 独立工作树", color: C.STEEL, yOff: 0 },
      { label: "任务 B 独立工作树", color: C.SUCCESS, yOff: 0.65 },
      { label: "任务 C 独立工作树", color: C.GOLD_DARK, yOff: 1.3 },
    ];
    tasks.forEach((t, i) => {
      const ty = baseY + t.yOff;
      // Branch line
      s.addShape(pres.shapes.RECTANGLE, {
        x: baseX + 0.5 + i * 0.3, y: ty, w: 3.0, h: 0.06,
        fill: { color: t.color }, line: { width: 0 },
      });
      // Branch label
      s.addShape(pres.shapes.RECTANGLE, {
        x: baseX + 0.5 + i * 0.3, y: ty - 0.2, w: 2.5, h: 0.35,
        fill: { color: t.color }, line: { width: 0 },
      });
      s.addText(t.label, {
        x: baseX + 0.5 + i * 0.3, y: ty - 0.2, w: 2.5, h: 0.35,
        fontSize: 10, fontFace: FB, bold: true, color: C.WHITE,
        align: "center", valign: "middle", margin: 0,
      });
      // Connector to master
      s.addShape(pres.shapes.RECTANGLE, {
        x: baseX + 0.5 + i * 0.3 + 2.9, y: ty, w: 0.06, h: 1.5 - t.yOff,
        fill: { color: t.color, transparency: 40 }, line: { width: 0 },
      });
    });
  }

  // Right: benefits
  {
    const x = 5.3, y = 1.45, w = 4.2, h = 3.5;
    addCard(s, x, y, w, h, { accent: C.SUCCESS });
    s.addText("隔离带来的价值", {
      x: x + 0.25, y: y + 0.2, w: w - 0.4, h: 0.4,
      fontSize: 14, fontFace: FB, bold: true, color: C.SUCCESS, margin: 0,
    });
    const benefits = [
      "不同任务互不影响",
      "AI 无法直接污染主分支",
      "人工可在合并前查看完整 Diff",
      "驳回后可继续在原分支修改",
      "任务终止后可清理对应分支",
    ];
    benefits.forEach((b, i) => {
      s.addShape(pres.shapes.OVAL, {
        x: x + 0.3, y: y + 0.9 + i * 0.5, w: 0.12, h: 0.12,
        fill: { color: C.SUCCESS }, line: { width: 0 },
      });
      s.addText(b, {
        x: x + 0.55, y: y + 0.8 + i * 0.5, w: w - 0.8, h: 0.4,
        fontSize: 12, fontFace: FB, color: C.TEXT_DARK, margin: 0, valign: "middle",
      });
    });
  }

  addPageNum(s, 9);
}

// ════════════════════════════════════════════════════════════════════
// Slide 10: 创新点 4 — 全链路审计责任链
// ════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.LIGHT_BG };
  addTitle(s, "创新点 4：全链路审计责任链", "串联一次变更的完整过程，提高问题定位和责任追溯效率");

  // Chain of 8 nodes
  const chain = [
    "人工创建任务",
    "向 AI 下达指令",
    "Agent 执行过程",
    "审查意见与投票",
    "驳回反馈",
    "代码合并",
    "冲突处理",
    "版本回退",
  ];

  const chainY = 1.8;
  const nodeW = 1.05, nodeH = 0.8, arrowGap = 0.08;
  const totalW = nodeW * chain.length + arrowGap * (chain.length - 1);
  const startX = (10 - totalW) / 2;

  chain.forEach((item, i) => {
    const x = startX + i * (nodeW + arrowGap);

    // Alternating colors
    const isEven = i % 2 === 0;
    const bgColor = isEven ? C.NAVY : C.STEEL;

    s.addShape(pres.shapes.RECTANGLE, {
      x, y: chainY, w: nodeW, h: nodeH,
      fill: { color: bgColor }, line: { width: 0 },
      shadow: { type: "outer", color: "000000", blur: 4, offset: 1.5, angle: 90, opacity: 0.1 },
    });
    // Number
    s.addText(String(i + 1), {
      x, y: chainY + 0.08, w: nodeW, h: 0.25,
      fontSize: 10, fontFace: FH, bold: true, color: C.GOLD,
      align: "center", valign: "middle", margin: 0,
    });
    // Label
    s.addText(item, {
      x: x + 0.05, y: chainY + 0.32, w: nodeW - 0.1, h: 0.4,
      fontSize: 10, fontFace: FB, bold: true, color: C.WHITE,
      align: "center", valign: "middle", margin: 0, lineSpacingMultiple: 1.1,
    });

    // Arrow
    if (i < chain.length - 1) {
      s.addText("→", {
        x: x + nodeW - 0.05, y: chainY + 0.2, w: arrowGap + 0.15, h: 0.4,
        fontSize: 14, fontFace: FB, color: C.GOLD,
        align: "center", valign: "middle", margin: 0,
      });
    }
  });

  // Key insight box
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 3.2, w: 8.6, h: 1.8,
    fill: { color: C.WHITE }, line: { color: C.BORDER, width: 0.5 },
    shadow: { type: "outer", color: "000000", blur: 4, offset: 1.5, angle: 90, opacity: 0.08 },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.7, y: 3.2, w: 0.06, h: 1.8, fill: { color: C.GOLD }, line: { width: 0 },
  });

  s.addText("可还原完整变更过程", {
    x: 1.0, y: 3.35, w: 8, h: 0.4,
    fontSize: 14, fontFace: FB, bold: true, color: C.NAVY, margin: 0,
  });

  s.addText([
    { text: "谁提出需求", options: { bold: true, color: C.GOLD_DARK } },
    { text: "  →  ", options: { color: C.TEXT_MUTED } },
    { text: "AI 执行了什么", options: { bold: true, color: C.GOLD_DARK } },
    { text: "  →  ", options: { color: C.TEXT_MUTED } },
    { text: "发现了哪些风险", options: { bold: true, color: C.GOLD_DARK } },
    { text: "  →  ", options: { color: C.TEXT_MUTED } },
    { text: "谁作出审批", options: { bold: true, color: C.GOLD_DARK } },
    { text: "  →  ", options: { color: C.TEXT_MUTED } },
    { text: "最终产生了什么影响", options: { bold: true, color: C.GOLD_DARK } },
  ], {
    x: 1.0, y: 3.8, w: 8, h: 0.5,
    fontSize: 12, fontFace: FB, align: "left", valign: "middle", margin: 0,
  });

  s.addText("通过责任链可以快速定位问题、追溯责任，满足银行审计合规要求", {
    x: 1.0, y: 4.4, w: 8, h: 0.4,
    fontSize: 11, fontFace: FB, color: C.TEXT_MUTED, italic: true, margin: 0,
  });

  addPageNum(s, 10);
}

// ════════════════════════════════════════════════════════════════════
// Slide 11: 创新点 5 — 四层经验记忆
// ════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.LIGHT_BG };
  addTitle(s, "创新点 5：四层经验记忆", "同类问题被驳回后保存经验，后续任务主动规避");

  const layers = [
    { t: "任务记忆", d: "当前任务的上下文、进度、错误和决策", scope: "单次任务", color: C.STEEL, bg: C.STEEL_BG },
    { t: "Agent 记忆", d: "某个 Agent 的历史经验和常见错误", scope: "单个 Agent", color: C.SUCCESS, bg: C.SUCCESS_BG },
    { t: "项目记忆", d: "项目架构、历史审查结论和项目规范", scope: "单个项目", color: C.GOLD_DARK, bg: C.GOLD_BG },
    { t: "全局记忆", d: "可跨项目复用的通用安全与开发经验", scope: "所有项目", color: C.NAVY, bg: C.STEEL_BG },
  ];

  // Pyramid layout (inverted — widest at bottom)
  const pyrCenterX = 5;
  const layerW = [3.0, 4.2, 5.4, 6.6];
  const layerH = 0.65;
  const gap = 0.08;
  const startY = 1.4;

  layers.forEach((l, i) => {
    const w = layerW[i];
    const x = pyrCenterX - w / 2;
    const y = startY + i * (layerH + gap);

    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h: layerH,
      fill: { color: l.bg }, line: { color: l.color, width: 1 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w: 0.06, h: layerH, fill: { color: l.color }, line: { width: 0 },
    });
    s.addText(l.t, {
      x: x + 0.2, y, w: 2.0, h: layerH,
      fontSize: 13, fontFace: FB, bold: true, color: l.color,
      align: "left", valign: "middle", margin: 0,
    });
    s.addText(l.d, {
      x: x + 2.3, y, w: w - 3.2, h: layerH,
      fontSize: 11, fontFace: FB, color: C.TEXT_DARK,
      align: "left", valign: "middle", margin: 0,
    });
    // Scope tag
    s.addShape(pres.shapes.RECTANGLE, {
      x: x + w - 0.85, y: y + 0.18, w: 0.7, h: 0.4,
      fill: { color: l.color }, line: { width: 0 },
    });
    s.addText(l.scope, {
      x: x + w - 0.85, y: y + 0.18, w: 0.7, h: 0.4,
      fontSize: 9, fontFace: FB, bold: true, color: C.WHITE,
      align: "center", valign: "middle", margin: 0,
    });
  });

  // Example box
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 4.5, w: 9, h: 0.55,
    fill: { color: C.GOLD_BG }, line: { width: 0 },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 4.5, w: 0.06, h: 0.55, fill: { color: C.GOLD }, line: { width: 0 },
  });
  s.addText("示例：某次代码因「敏感信息写入日志」被驳回 → 平台保存经验 → 后续相似任务中 Agent 主动规避同类问题", {
    x: 0.7, y: 4.5, w: 8.6, h: 0.55,
    fontSize: 11, fontFace: FB, color: C.GOLD_DARK, italic: true,
    align: "left", valign: "middle", margin: 0,
  });

  addPageNum(s, 11);
}

// ════════════════════════════════════════════════════════════════════
// Slide 12: 创新点 6 — 可回退的变更闭环
// ════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.LIGHT_BG };
  addTitle(s, "创新点 6：可回退的变更闭环", "生成 → 审查 → 审批 → 合并 → 追溯 → 恢复");

  // Circular flow with 6 steps
  const steps = [
    { t: "生成", d: "Agent 生成代码", color: C.STEEL },
    { t: "审查", d: "多 Agent 交叉检查", color: C.SUCCESS },
    { t: "审批", d: "多人复核决策", color: C.GOLD_DARK },
    { t: "合并", d: "通过后合并到主分支", color: C.NAVY },
    { t: "追溯", d: "责任链定位问题", color: C.DANGER },
    { t: "恢复", d: "版本回退恢复", color: C.STEEL },
  ];

  const centerX = 3.2, centerY = 3.2;
  const radius = 1.5;
  const nodeSize = 1.1;

  steps.forEach((st, i) => {
    const angle = (i / steps.length) * 2 * Math.PI - Math.PI / 2;
    const x = centerX + Math.cos(angle) * radius - nodeSize / 2;
    const y = centerY + Math.sin(angle) * radius - nodeSize / 2;

    s.addShape(pres.shapes.OVAL, {
      x, y, w: nodeSize, h: nodeSize,
      fill: { color: st.color }, line: { width: 0 },
      shadow: { type: "outer", color: "000000", blur: 4, offset: 1.5, angle: 90, opacity: 0.15 },
    });
    s.addText(st.t, {
      x, y: y + 0.15, w: nodeSize, h: 0.35,
      fontSize: 14, fontFace: FH, bold: true, color: C.WHITE,
      align: "center", valign: "middle", margin: 0,
    });
    s.addText(st.d, {
      x: x - 0.15, y: y + 0.5, w: nodeSize + 0.3, h: 0.4,
      fontSize: 9, fontFace: FB, color: C.WHITE,
      align: "center", valign: "middle", margin: 0, lineSpacingMultiple: 1.1,
    });
  });

  // Center text
  s.addShape(pres.shapes.OVAL, {
    x: centerX - 0.55, y: centerY - 0.55, w: 1.1, h: 1.1,
    fill: { color: C.WHITE }, line: { color: C.GOLD, width: 2 },
  });
  s.addText("闭环", {
    x: centerX - 0.55, y: centerY - 0.55, w: 1.1, h: 1.1,
    fontSize: 16, fontFace: FH, bold: true, color: C.GOLD_DARK,
    align: "center", valign: "middle", margin: 0,
  });

  // Right: recovery steps
  {
    const x = 5.8, y = 1.45, w = 3.8, h = 3.5;
    addCard(s, x, y, w, h, { accent: C.DANGER });
    s.addText("出现问题时", {
      x: x + 0.25, y: y + 0.2, w: w - 0.4, h: 0.4,
      fontSize: 14, fontFace: FB, bold: true, color: C.DANGER, margin: 0,
    });
    const recovery = [
      "定位对应任务",
      "查看当时的指令、审查和审批记录",
      "找到受影响版本",
      "执行可审计的版本回退",
    ];
    recovery.forEach((r, i) => {
      s.addShape(pres.shapes.OVAL, {
        x: x + 0.3, y: y + 0.85 + i * 0.62, w: 0.28, h: 0.28,
        fill: { color: C.DANGER }, line: { width: 0 },
      });
      s.addText(String(i + 1), {
        x: x + 0.3, y: y + 0.85 + i * 0.62, w: 0.28, h: 0.28,
        fontSize: 11, fontFace: FB, bold: true, color: C.WHITE,
        align: "center", valign: "middle", margin: 0,
      });
      s.addText(r, {
        x: x + 0.7, y: y + 0.8 + i * 0.62, w: w - 1.0, h: 0.4,
        fontSize: 11.5, fontFace: FB, color: C.TEXT_DARK, margin: 0, valign: "middle",
      });
    });
  }

  addPageNum(s, 12);
}

// ════════════════════════════════════════════════════════════════════
// Slide 13: 与普通 AI 编程工具对比
// ════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.LIGHT_BG };
  addTitle(s, "与普通 AI 编程工具的区别");

  const rows = [
    ["对比维度", "普通 AI 编程工具", "AgentCollab"],
    ["主要目标", "提高个人编码速度", "提升团队效率并控制 AI 风险"],
    ["执行方式", "单一助手生成代码", "多 Agent 分工协作"],
    ["代码隔离", "取决于使用者操作", "每任务独立分支和工作树"],
    ["安全审查", "通常需人工额外完成", "独立安全 Agent 自动审查"],
    ["人工审批", "通常没有完整流程", "多人投票、驳回反馈、人工决策"],
    ["审计能力", "对话和代码记录分散", "指令到影响形成完整责任链"],
    ["经验复用", "依赖个人上下文", "四层记忆和技能仓库"],
    ["故障恢复", "依赖外部版本工具", "内置版本记录与回退"],
  ];

  const tableY = 1.35;
  const tableW = 9;
  const colW = [1.8, 3.6, 3.6];
  const rowH = 0.4;

  rows.forEach((row, ri) => {
    const isHeader = ri === 0;
    const y = tableY + ri * rowH;
    row.forEach((cell, ci) => {
      const x = 0.5 + colW.slice(0, ci).reduce((a, b) => a + b, 0);
      s.addShape(pres.shapes.RECTANGLE, {
        x, y, w: colW[ci], h: rowH,
        fill: { color: isHeader ? C.NAVY : (ri % 2 === 0 ? C.WHITE : C.STEEL_BG) },
        line: { color: C.BORDER, width: 0.3 },
      });
      // Accent for AgentCollab column
      if (ci === 2 && !isHeader) {
        s.addShape(pres.shapes.RECTANGLE, {
          x, y, w: 0.05, h: rowH, fill: { color: C.GOLD }, line: { width: 0 },
        });
      }
      s.addText(cell, {
        x: x + (ci === 0 ? 0.15 : 0.2), y, w: colW[ci] - 0.25, h: rowH,
        fontSize: isHeader ? 11 : 10.5,
        fontFace: isHeader ? FH : FB,
        bold: isHeader || ci === 0,
        color: isHeader ? C.WHITE : (ci === 2 ? C.NAVY : C.TEXT_DARK),
        align: "left", valign: "middle", margin: 0,
      });
    });
  });

  // Bottom message
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: tableY + rows.length * rowH + 0.12, w: 9, h: 0.5,
    fill: { color: C.NAVY }, line: { width: 0 },
  });
  s.addText("创新的重点不是模型数量，而是把 AI 能力嵌入银行可控的研发治理流程", {
    x: 0.5, y: tableY + rows.length * rowH + 0.12, w: 9, h: 0.5,
    fontSize: 12, fontFace: FB, bold: true, color: C.GOLD,
    align: "center", valign: "middle", margin: 0,
  });

  addPageNum(s, 13);
}

// ════════════════════════════════════════════════════════════════════
// Slide 14: 总结
// ════════════════════════════════════════════════════════════════════
{
  const s = pres.addSlide();
  s.background = { color: C.NAVY };

  // Gold accent bar
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.GOLD }, line: { width: 0 },
  });
  s.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.5, w: 10, h: 0.125, fill: { color: C.GOLD }, line: { width: 0 },
  });

  // Decorative
  s.addShape(pres.shapes.OVAL, {
    x: -1.5, y: 3.5, w: 4, h: 4,
    fill: { color: C.STEEL, transparency: 85 }, line: { width: 0 },
  });

  s.addText("总结", {
    x: 0.5, y: 0.5, w: 9, h: 0.5,
    fontSize: 22, fontFace: FH, bold: true, color: C.GOLD,
    align: "left", valign: "middle", margin: 0,
  });

  // Main message
  s.addText("AgentCollab 不是一个「更会写代码的 AI」", {
    x: 0.7, y: 1.3, w: 8.6, h: 0.6,
    fontSize: 20, fontFace: FH, color: C.WHITE,
    align: "left", valign: "middle", margin: 0,
  });
  s.addText("而是一套让 AI 能够在银行研发治理框架下安全工作的协作机制", {
    x: 0.7, y: 1.9, w: 8.6, h: 0.6,
    fontSize: 20, fontFace: FH, bold: true, color: C.GOLD,
    align: "left", valign: "middle", margin: 0,
  });

  // Three pillars
  const pillars = [
    { t: "可控", d: "任务隔离 + 安全门禁\n+ 人工审批" },
    { t: "可审", d: "全链路责任链\n+ 四层经验记忆" },
    { t: "可回退", d: "版本记录 + 责任追溯\n+ 一键恢复" },
  ];

  pillars.forEach((p, i) => {
    const x = 0.7 + i * 3.0;
    const y = 3.1;
    const w = 2.7, h = 1.5;

    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h,
      fill: { color: C.NAVY_DEEP },
      line: { color: C.GOLD, width: 0.5 },
    });
    s.addShape(pres.shapes.RECTANGLE, {
      x, y, w, h: 0.06, fill: { color: C.GOLD }, line: { width: 0 },
    });
    s.addText(p.t, {
      x, y: y + 0.2, w, h: 0.5,
      fontSize: 18, fontFace: FH, bold: true, color: C.GOLD,
      align: "center", valign: "middle", margin: 0,
    });
    s.addText(p.d, {
      x: x + 0.2, y: y + 0.7, w: w - 0.4, h: 0.7,
      fontSize: 11, fontFace: FB, color: C.TEXT_LIGHT,
      align: "center", valign: "top", margin: 0, lineSpacingMultiple: 1.3,
    });
  });

  addPageNum(s, 14, true);
}

// ── Generate ──────────────────────────────────────────────────────
pres.writeFile({ fileName: "c:/REPO/demo/AgentCollab答辩.pptx" })
  .then(() => console.log("PPT generated: AgentCollab答辩.pptx"))
  .catch(err => console.error("Error:", err));
