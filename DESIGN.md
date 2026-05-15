---
name: LeanReel
description: 可解释的个人媒体库瘦身决策桌面工具
colors:
  base-warm-black: "#12100e"
  surface-warm-panel: "#1c1a16"
  surface-raised: "#24221d"
  border-muted: "#2e2b25"
  border-focus-amber: "#5c4a2e"
  text-primary: "#e8e3db"
  text-secondary: "#8a857c"
  text-muted: "#5c5851"
  accent-amber: "#c8963e"
  accent-amber-hover: "#d9a84c"
  success-green: "#6b9955"
  danger-red: "#c4554a"
  warning-yellow: "#c8a23e"
  info-blue: "#5b8db8"
  row-alternate: "#171512"
  row-selection: "#3d2e14"
typography:
  body:
    fontFamily: "Segoe UI, Microsoft YaHei, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: "0"
  label:
    fontFamily: "Segoe UI, Microsoft YaHei, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "0"
  data:
    fontFamily: "Segoe UI, Microsoft YaHei, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.35
    letterSpacing: "0"
  mono:
    fontFamily: "Cascadia Code, Consolas, Fira Code, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.35
    letterSpacing: "0"
rounded:
  xs: "3px"
  sm: "4px"
  md: "6px"
spacing:
  xs: "4px"
  sm: "6px"
  md: "8px"
  lg: "12px"
  xl: "16px"
components:
  button-default:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "6px 16px"
  button-primary:
    backgroundColor: "{colors.accent-amber}"
    textColor: "{colors.base-warm-black}"
    rounded: "{rounded.md}"
    padding: "12px 24px"
  table-row-selected:
    backgroundColor: "{colors.row-selection}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.xs}"
    padding: "5px 8px"
  input-default:
    backgroundColor: "{colors.surface-raised}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "5px 8px"
---

# Design System: LeanReel

## 1. Overview

**Creative North Star: "The Media Workbench"**

LeanReel should feel like a precise desktop workbench for media decisions. The visual system is dense, warm, and restrained: dark enough for long batch sessions, but not theatrical. The user is not here to admire media covers. They are here to make safe decisions about files.

The interface rejects landing-page spectacle, generic AI gradients, glass effects, and decorative motion. The dominant surface is a stable three-pane tool: library, file table, strategy settings. The table is the center of gravity; everything else supports scanning, filtering, explaining, and executing.

**Key Characteristics:**
- Dense, task-first information layout.
- Warm dark neutral surfaces with one amber action accent.
- Status vocabulary that combines color, text, and affordance.
- Technical strategy names with short explanatory copy.
- Protected sources shown as non-actionable, not as ordinary queued work.

## 2. Colors

The palette is restrained: warm tinted neutrals carry the workspace, amber marks primary action and focus, semantic colors mark outcomes.

### Primary
- **Workbench Amber**: Primary action, selected strategy, active focus, progress. It must remain rare so it keeps authority.

### Secondary
- **Information Blue**: Skip and informational status, especially protected-source explanations.
- **Operational Green**: Completed work and verified success.
- **Risk Red**: Failed tasks, destructive or unrecoverable states.
- **Warning Yellow**: Risky options, aggressive compression, debug-only toggles.

### Neutral
- **Warm Black Base**: Main window background.
- **Warm Panel Surface**: Library panel, file table, menus, queue dock.
- **Raised Surface**: Inputs, buttons, hover states, active rows.
- **Muted Border**: Structural separation between panes and controls.
- **Primary Text**: File names, table data, active control text.
- **Secondary Text**: Labels, descriptions, supporting metadata.
- **Muted Text**: Disabled and low-emphasis states.

### Named Rules

**The One Amber Rule.** Amber is for action, focus, and selected state. Do not use amber as decoration.

**The Status Needs Text Rule.** Success, failure, skip, warning, and running states must not rely on color alone. Pair color with text, icon, or disabled behavior.

**The Protected Source Rule.** HEVC/H.265, HDR10, HDR10+ and Dolby Vision should use an informational skip treatment, not a warning treatment. They are good files, not errors.

## 3. Typography

**Display Font:** Segoe UI / Microsoft YaHei system stack  
**Body Font:** Segoe UI / Microsoft YaHei system stack  
**Label/Mono Font:** Cascadia Code / Consolas / Fira Code for commands, codecs, and technical tokens only

**Character:** Native, quiet, and utilitarian. Type should disappear into the workflow. The product does not need a decorative display voice.

### Hierarchy
- **Window and panel headings** (600, 13-14px, 1.3): Panel labels such as “压缩策略” and “编码设置”.
- **Table body** (400, 13px, 1.35): File names, codecs, sizes, strategy names, savings estimates.
- **Secondary labels** (400-600, 11-12px, 1.3): Strategy descriptions, queue metadata, helper text.
- **Technical tokens** (400, 12px mono, 1.35): Codec names, CRF/CQ, command-like values, exact parameters.
- **Status bar** (400, 12px, 1.3): Short operational state, no long prose.

### Named Rules

**The No Display Type Rule.** Product labels, buttons, table headers, queue rows, and status text use the system sans stack. Do not introduce display fonts into the app shell.

**The Technical Name Rule.** Strategy names expose encoder and quality parameter first, for example `x265 HEVC CRF 20 标准转码`. The explanatory sentence goes below or in a tooltip.

## 4. Elevation

LeanReel uses tonal layering and borders, not heavy shadows. Depth is conveyed by background steps: base, panel, raised control, selected row. Shadows are not part of the current vocabulary and should remain absent unless a future floating overlay truly needs separation.

### Named Rules

**The Flat Workbench Rule.** Tables, panels, toolbars, and strategy rows are flat by default. Use borders and tonal changes for separation.

**The No Glass Rule.** Do not use blur, translucency, glow cards, or glass surfaces. They reduce readability in dense desktop tools.

## 5. Components

### Buttons
- **Shape:** Gently squared desktop control (4-6px radius).
- **Default:** Raised warm surface, muted border, primary text.
- **Primary:** Amber fill, warm black text, bold 14-15px label. Use only for the main queue-start action or equivalent primary commitment.
- **Hover / Focus:** Border shifts toward focus amber. Avoid layout shift.
- **Disabled:** Muted text, no strong fill. Disabled must look unavailable, not merely low contrast.

### Strategy Rows
- **Style:** Single-line selectable rows, not large marketing cards.
- **Content:** Indicator, technical strategy name, CPU/GPU/COPY tag, estimated savings.
- **Description:** Separate description label below the selected row. Do not stuff long prose into every row.
- **State:** Checked row uses amber border and selected warm background.

### File Table
- **Role:** Primary decision surface.
- **Columns:** File name, size, codec, HDR, matched strategy, estimated savings.
- **Protected rows:** Checkbox disabled, strategy column shows skip reason, savings column should prefer “不处理” where space allows.
- **Sorting:** Numeric columns sort by hidden numeric values, not display text.
- **Selection:** Selection is for inspection. Checked state is for processing. They must stay visually distinct.

### Inputs / Fields
- **Style:** Raised surface, 1px muted border, 4px radius.
- **Focus:** Amber border. Do not add glow.
- **Disabled:** Muted text and no hover affordance.
- **Technical values:** Use exact labels such as `CQ`, `CRF`, `NV 预设`, and add tooltips when the label is not self-explanatory.

### Chips / Tags
- **CPU/GPU/COPY:** Compact uppercase tags inside strategy rows.
- **HDR and codec statuses:** Use color plus readable text. Avoid icon-only tags.
- **Skip reasons:** Treat as informational status, not errors.

### Navigation
- **Library panel:** Tree navigation with search. Use folder hierarchy as structure, not decorative icons.
- **View mode:** Flat/tree selection belongs near file table controls.
- **Queue dock:** Bottom dock is a transient operational panel. It should summarize progress first, then show individual rows.

### Queue Rows
- **Status icon:** Running, completed, failed, skipped, pending, cancelled each get icon plus color.
- **Primary text:** File name.
- **Secondary text:** Current stage, size delta, or failure detail.
- **Progress:** Overall progress sits above rows; per-row stage text is enough unless detailed progress becomes necessary.

## 6. Do's and Don'ts

### Do:
- **Do** keep the three-pane layout as the default mental model: library, files, strategy.
- **Do** show protected-source skip reasons plainly: `跳过：HEVC/H.265 片源`, `跳过：HDR10 片源`, `跳过：HDR10+ 片源`, `跳过：Dolby Vision 片源`.
- **Do** use technical strategy names, then explain in one short sentence.
- **Do** keep amber rare and meaningful.
- **Do** make disabled checkboxes visibly disabled for files that must not be processed.
- **Do** preserve dense tables, numeric sorting, and column resizing.
- **Do** use tooltips for CRF, CQ, NV preset, debug toggles, and protected-source rules.

### Don't:
- **Don't** rename technical strategies back to vague labels like “轻量压缩”, “均衡压缩”, or “极限压缩”.
- **Don't** process HEVC/H.265, HDR10, HDR10+ or Dolby Vision through default UI paths.
- **Don't** use landing-page patterns, hero sections, decorative cards, or identical card grids.
- **Don't** use purple-blue gradients, glassmorphism, glow borders, or gradient text.
- **Don't** rely on color alone for task status.
- **Don't** put long strategy descriptions inside every selectable row.
- **Don't** use side-stripe borders as status accents. Use full borders, tags, text, or disabled behavior.
