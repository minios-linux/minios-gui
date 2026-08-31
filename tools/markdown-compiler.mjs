#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import MarkdownIt from "markdown-it";
import { alert } from "@mdit/plugin-alert";
import { dl } from "@mdit/plugin-dl";
import { footnote } from "@mdit/plugin-footnote";
import { sub } from "@mdit/plugin-sub";
import { sup } from "@mdit/plugin-sup";
import { tasklist } from "@mdit/plugin-tasklist";
import admon from "markdown-it-admon";
import { bundledLanguages, createHighlighter } from "shiki";

const DOCUMENT_KIND = "minios-markup-document";
const DOCUMENT_SCHEMA_VERSION = 1;
const SAFE_IMAGE_SUFFIXES = new Set([".svg", ".png", ".jpg", ".jpeg", ".gif"]);
const __dirname = path.dirname(fileURLToPath(import.meta.url));

const SHIKI_THEMES = { light: "github-light", dark: "github-dark" };
const LANGUAGE_ALIASES = new Map([
  ["sh", "bash"], ["shell", "bash"], ["console", "bash"],
  ["ps1", "powershell"], ["pwsh", "powershell"],
  ["text", ""], ["plaintext", ""], ["txt", ""],
]);

function normalizeLanguageName(info) {
  let language = String(info || "").trim().split(/\s+/, 1)[0].toLowerCase();
  language = language.replace(/\{[^}]*\}$/, "");
  return LANGUAGE_ALIASES.has(language) ? LANGUAGE_ALIASES.get(language) : language;
}

function normalizeVitePressAdmonitions(source) {
  const lines = String(source || "").split("\n");
  const output = [];
  const containers = [];
  let fence = null;

  for (const line of lines) {
    const fenceMatch = line.match(/^\s*(`{3,}|~{3,})/);
    if (fenceMatch) {
      const marker = fenceMatch[1];
      if (!fence) fence = marker[0];
      else if (marker[0] === fence) fence = null;
      output.push("    ".repeat(containers.length) + line);
      continue;
    }

    if (!fence) {
      const opening = line.match(/^\s*:::\s+(note|tip|info|warning|danger|success)(?:\s+(.*?))?\s*$/i);
      if (opening) {
        const kind = opening[1].toLowerCase();
        const title = String(opening[2] || "").trim();
        const escaped = title.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
        output.push("    ".repeat(containers.length) +
          `!!! ${kind}${escaped ? ` "${escaped}"` : ""}`);
        containers.push(kind);
        continue;
      }
      if (/^\s*:::\s*$/.test(line) && containers.length) {
        containers.pop();
        continue;
      }
    }

    output.push("    ".repeat(containers.length) + line);
  }

  return output.join("\n");
}

function batchHighlightLanguages(items) {
  const languages = new Set();
  const fence = /^\s*(?:```|~~~)\s*([^\s`~]*)/gm;
  for (const item of items || []) {
    for (const match of String(item?.text || "").matchAll(fence)) {
      const language = normalizeLanguageName(match[1]);
      if (language && language !== "mermaid" && bundledLanguages[language]) {
        languages.add(language);
      }
    }
  }
  return [...languages].sort();
}

class CompileError extends Error {}

function attrsObject(token) {
  if (!token?.attrs) return {};
  if (Array.isArray(token.attrs)) return Object.fromEntries(token.attrs);
  return { ...token.attrs };
}

function normalizedType(type) {
  return type.replace(/_(open|close)$/, "");
}

function tokenTree(tokens) {
  const root = { type: "root", children: [] };
  const stack = [root];
  for (const token of tokens || []) {
    if (token.nesting === -1) {
      if (stack.length > 1) stack.pop();
      continue;
    }
    const node = {
      type: normalizedType(token.type), tag: token.tag || "",
      attrs: attrsObject(token), content: token.content || "",
      info: token.info || "", meta: token.meta || {}, children: [],
    };
    if (token.children) node.children = tokenTree(token.children).children;
    stack.at(-1).children.push(node);
    if (token.nesting === 1) stack.push(node);
  }
  return root;
}

function slug(value) {
  const normalized = (value || "").normalize("NFKC").toLowerCase();
  let out = "";
  for (const char of normalized) {
    if (/^[\p{L}\p{N}\p{M}_-]$/u.test(char)) out += char;
    else if (/\s/u.test(char)) out += "-";
  }
  out = out.replace(/-+/g, "-").replace(/^-|-$/g, "");
  return out || "section";
}

function plainNodes(nodes) {
  let value = "";
  for (const node of nodes || []) {
    if (!node) continue;
    if (node[0] === "text") value += String(node[1] || "");
    else if (node[0] === "span") value += plainNodes(node[2]);
    else if (node[0] === "link") value += plainNodes(node[3]);
    else if (node[0] === "image" || node[0] === "diagram") value += String(node[2] || "");
  }
  return value;
}

function stableObject(value) {
  if (Array.isArray(value)) return value.map(stableObject);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.keys(value).sort().map(key => [key, stableObject(value[key])]));
}

function stableStringify(value) {
  return JSON.stringify(stableObject(value), null, 2) + "\n";
}

class AssetStore {
  constructor(outputRoot) {
    this.outputRoot = path.resolve(outputRoot);
    this.hashes = {};
  }

  addBytes(data, suffix, prefix = "asset") {
    const digest = crypto.createHash("sha256").update(data).digest("hex");
    suffix = suffix.toLowerCase();
    const relative = `assets/${prefix}-${digest.slice(0, 20)}${suffix}`;
    const destination = path.join(this.outputRoot, relative);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    if (fs.existsSync(destination)) {
      if (!fs.readFileSync(destination).equals(data)) throw new CompileError(`asset hash collision: ${relative}`);
    } else {
      fs.writeFileSync(destination, data);
    }
    this.hashes[relative] = digest;
    return relative;
  }

  addFile(filename) {
    const suffix = path.extname(filename).toLowerCase();
    if (!SAFE_IMAGE_SUFFIXES.has(suffix)) throw new CompileError(`unsupported image format: ${path.basename(filename)}`);
    return this.addBytes(fs.readFileSync(filename), suffix, "image");
  }
}

function sanitizeMermaidSvg(data) {
  let text = data.toString("utf8");
  // Mermaid emits labels as adjacent <tspan> elements and often puts the
  // separator at the start of the following tspan. librsvg follows SVG's
  // default whitespace collapsing rules more strictly than Chromium and can
  // therefore render "Bootstrap Failed?" as "BootstrapFailed?". Preserve
  // whitespace for text labels in the compiled SVG itself so browser and GTK
  // rendering agree.
  text = text.replace(
    /<text\b(?![^>]*\bxml:space=)([^>]*)>/gi,
    '<text xml:space="preserve"$1>');
  text = text.replace(/(<style\b[^>]*>)(.*?)(<\/style>)/gis, (_all, start, css, end) => {
    css = css.replace(/@keyframes[^{}]*\{(?:[^{}]*\{[^{}]*\}[^{}]*)*\}/g, "");
    css = css.replace(/filter\s*:\s*drop-shadow\([^;{}]*\)\s*;?/gi, "");
    css = css.replace(/animation\s*:[^;{}]*;?/gi, "");
    css = css.replace(/--[A-Za-z0-9_-]+\s*:[^;{}]*;?/g, "");
    css = css.replace(/[^{}]+\{\s*\}/g, "");
    return start + css + end;
  });
  return Buffer.from(text, "utf8");
}

class MermaidRenderer {
  constructor(command) {
    this.command = command || path.join(__dirname, "node_modules", ".bin", "mmdc");
    this.cache = new Map();
  }

  render(source) {
    if (this.cache.has(source)) return this.cache.get(source);
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "minios-mermaid-"));
    try {
      const sourcePath = path.join(root, "diagram.mmd");
      const outputPath = path.join(root, "diagram.svg");
      const configPath = path.join(root, "config.json");
      fs.writeFileSync(sourcePath, source, "utf8");
      fs.writeFileSync(configPath, JSON.stringify({
        securityLevel: "strict", htmlLabels: false,
        handDrawnSeed: 1,
        flowchart: { htmlLabels: false },
      }), "utf8");
      const puppeteerCache = process.env.PUPPETEER_CACHE_DIR
        || path.resolve(__dirname, "..", ".build-tools", "puppeteer-cache");
      const result = spawnSync(this.command, [
        "-i", sourcePath, "-o", outputPath,
        "-c", configPath, "-b", "transparent",
      ], {
        encoding: "utf8", timeout: 90000,
        env: { ...process.env, PUPPETEER_CACHE_DIR: puppeteerCache },
      });
      if (result.error || result.status !== 0 || !fs.existsSync(outputPath)) {
        const message = result.error?.message || result.stderr || result.stdout || "unknown error";
        throw new CompileError(`Mermaid renderer failed: ${String(message).trim()}`);
      }
      const data = sanitizeMermaidSvg(fs.readFileSync(outputPath));
      const lower = data.toString("utf8").toLowerCase();
      if (lower.includes("<foreignobject")) throw new CompileError("Mermaid SVG contains unsupported foreignObject");
      if (lower.includes("<script")) throw new CompileError("Mermaid SVG contains a script element");
      this.cache.set(source, data);
      return data;
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  }
}

class MarkdownCompiler {
  constructor(docsRoot, assetStore, mermaidRenderer, highlighter) {
    this.docsRoot = fs.realpathSync(docsRoot);
    this.assetStore = assetStore;
    this.mermaidRenderer = mermaidRenderer;
    this.highlighter = highlighter;
    this.parser = new MarkdownIt({ html: true, linkify: true })
      .use(tasklist)
      .use(footnote)
      .use(dl)
      .use(sub)
      .use(sup)
      .use(alert)
      .use(admon);
    this.slugCounts = new Map();
    this.headings = [];
  }

  compile(text, sourcePath) {
    this.slugCounts.clear();
    this.headings = [];
    const normalized = normalizeVitePressAdmonitions(text || "");
    const tree = tokenTree(this.parser.parse(normalized, {}));
    const nodes = this.compileBlocks(tree.children, path.resolve(sourcePath));
    return {
      product_kind: DOCUMENT_KIND,
      schema_version: DOCUMENT_SCHEMA_VERSION,
      nodes,
      headings: [...this.headings],
      plain_text: this.plainDocument(nodes),
    };
  }

  compileBlocks(children, sourcePath) {
    const output = [];
    for (const node of children || []) output.push(...this.compileBlock(node, sourcePath));
    return output;
  }

  compileBlock(node, sourcePath) {
    const kind = node.type;
    if (kind === "paragraph") return [["block", "paragraph", this.inlineFromContainer(node, sourcePath)]];
    if (kind === "heading") {
      const level = /^h\d$/.test(node.tag) ? Number(node.tag.slice(1)) : 1;
      const children = this.inlineFromContainer(node, sourcePath);
      const title = plainNodes(children).trim();
      const base = slug(title);
      const count = this.slugCounts.get(base) || 0;
      this.slugCounts.set(base, count + 1);
      const anchorName = count === 0 ? base : `${base}-${count}`;
      this.headings.push({ level, title, anchor: anchorName });
      return [["heading", level, anchorName, children]];
    }
    if (kind === "bullet_list" || kind === "ordered_list") return [this.compileList(node, sourcePath)];
    if (kind === "blockquote") return [["block", "quote", this.compileBlocks(node.children, sourcePath)]];
    if (kind === "table") return [this.compileTable(node, sourcePath)];
    if (kind === "fence" || kind === "code_block") return this.compileFence(node);
    if (kind === "hr" || kind === "thematic_break") return [["rule"]];
    if (kind === "alert" || kind === "admonition") return [this.compileAdmonition(node, sourcePath)];
    if (kind === "dl") return this.compileDefinitionList(node, sourcePath);
    if (kind === "footnote_block") return this.compileFootnotes(node, sourcePath);
    if (kind === "html_block" || kind === "html") return [["code_block", node.content.replace(/\n$/, ""), "html"]];
    if (node.children?.length) return this.compileBlocks(node.children, sourcePath);
    if (node.content) return [["block", "paragraph", [["text", node.content]]]];
    return [];
  }

  compileFence(node) {
    const language = this.normalizeLanguage(node.info || "");
    if (language !== "mermaid") {
      const source = node.content.replace(/\n$/, "");
      return [["code_block", source, language, this.highlightCode(source, language)]];
    }
    if (!this.mermaidRenderer) throw new CompileError("Mermaid source requires a build renderer");
    const svg = this.mermaidRenderer.render(node.content);
    const asset = this.assetStore.addBytes(svg, ".svg", "mermaid");
    return [["diagram", asset, "Mermaid diagram"]];
  }

  normalizeLanguage(info) {
    return normalizeLanguageName(info);
  }

  highlightCode(source, language) {
    if (!source || !language || !this.highlighter) return [];
    if (!this.highlighter.getLoadedLanguages().includes(language)) return [];
    let result;
    try {
      result = this.highlighter.codeToTokens(source, {
        lang: language, themes: SHIKI_THEMES,
      });
    } catch (_error) {
      return [];
    }
    const lightTheme = this.highlighter.getTheme(SHIKI_THEMES.light);
    const darkTheme = this.highlighter.getTheme(SHIKI_THEMES.dark);
    const output = [];
    const append = (text, light, dark) => {
      if (!text) return;
      const previous = output.at(-1);
      if (previous && previous[2] === light && previous[3] === dark) {
        previous[1] += text;
      } else {
        output.push(["syntax", text, light, dark]);
      }
    };
    for (let line = 0; line < result.tokens.length; line += 1) {
      if (line) append("\n", lightTheme.fg, darkTheme.fg);
      for (const token of result.tokens[line]) {
        append(
          token.content,
          token.htmlStyle?.color || lightTheme.fg,
          token.htmlStyle?.["--shiki-dark"] || darkTheme.fg,
        );
      }
    }
    return output;
  }

  checkboxState(node) {
    if (node.type === "checkbox_input") return Object.hasOwn(node.attrs || {}, "checked");
    for (const child of node.children || []) {
      const state = this.checkboxState(child);
      if (state !== null) return state;
    }
    return null;
  }

  compileList(node, sourcePath) {
    const ordered = node.type === "ordered_list";
    const start = ordered ? Number(node.attrs?.start || 1) : 1;
    const items = [];
    for (const item of node.children || []) {
      if (item.type !== "list_item") continue;
      const checked = this.checkboxState(item);
      const blocks = this.compileBlocks(item.children, sourcePath);
      if (checked !== null) {
        const paragraph = blocks.find(block => block?.[0] === "block" && block?.[1] === "paragraph");
        const firstText = paragraph?.[2]?.find(child => child?.[0] === "text");
        if (firstText) firstText[1] = String(firstText[1]).replace(/^\s+/, "");
      }
      items.push(["item", checked, blocks]);
    }
    return ["list", { ordered, start }, items];
  }

  compileTable(node, sourcePath) {
    const rows = [];
    for (const section of node.children || []) {
      const header = section.type === "thead";
      for (const row of section.children || []) {
        if (row.type !== "tr") continue;
        const cells = [];
        for (const cell of row.children || []) {
          if (cell.type !== "th" && cell.type !== "td") continue;
          cells.push(["table_cell", this.inlineFromContainer(cell, sourcePath)]);
        }
        rows.push(["table_row", header, cells]);
      }
    }
    return ["table", rows];
  }

  compileAdmonition(node, sourcePath) {
    const className = String(node.attrs?.class || "");
    let kind = className.match(/(?:markdown-alert-|admonition\s+)([a-z0-9_-]+)/i)?.[1] || "";
    if (!kind && node.info) kind = String(node.info).trim().split(/\s+/, 1)[0];
    kind = (kind || "note").toLowerCase();
    let title = "";
    const body = [];
    for (const child of node.children || []) {
      if (child.type === "alert_title" || child.type === "admonition_title") {
        title = plainNodes(this.inlineFromContainer(child, sourcePath)).trim() || child.content.trim();
      } else {
        body.push(child);
      }
    }
    const quoted = title.match(/^(["'])(.*)\1$/s);
    if (quoted) title = quoted[2];
    if (!title) title = kind.replace(/-/g, " ").replace(/\b\w/g, char => char.toUpperCase());
    return ["admonition", kind, title, this.compileBlocks(body, sourcePath)];
  }

  compileDefinitionList(node, sourcePath) {
    const output = [];
    let index = 0;
    while (index < (node.children || []).length) {
      const term = node.children[index];
      const definition = node.children[index + 1];
      if (term?.type === "dt") {
        const inline = this.inlineFromContainer(term, sourcePath);
        output.push(["block", "paragraph", [["span", "strong", inline]]]);
      }
      if (definition?.type === "dd") {
        output.push(["block", "quote", this.compileBlocks(definition.children, sourcePath)]);
        index += 1;
      }
      index += 1;
    }
    return output;
  }

  compileFootnotes(node, sourcePath) {
    const output = [["rule"]];
    for (const footnoteNode of node.children || []) {
      if (footnoteNode.type !== "footnote") continue;
      const label = String(footnoteNode.meta?.label ?? footnoteNode.meta?.id ?? "");
      output.push(["anchor", `fn-${slug(label)}`]);
      const prefix = ["span", "strong", [["text", `[${label}] `]]];
      const blocks = this.compileBlocks(footnoteNode.children, sourcePath);
      if (blocks[0]?.[0] === "block" && blocks[0]?.[1] === "paragraph") {
        blocks[0][2].unshift(prefix);
      } else {
        blocks.unshift(["block", "paragraph", [prefix]]);
      }
      output.push(...blocks);
    }
    return output;
  }

  inlineFromContainer(node, sourcePath) {
    if (node.type === "inline") return this.compileInline(node.children, sourcePath);
    const inline = (node.children || []).find(child => child.type === "inline");
    if (inline) return this.compileInline(inline.children, sourcePath);
    if (node.content && (node.type === "alert_title" || node.type === "admonition_title")) {
      return [["text", node.content]];
    }
    return this.compileInline(node.children, sourcePath);
  }

  compileInline(children, sourcePath) {
    const output = [];
    const stack = [[null, output]];
    const htmlStyles = {
      kbd: "kbd", strong: "strong", b: "strong",
      em: "emphasis", i: "emphasis", code: "code",
      sub: "subscript", sup: "superscript",
      s: "strikethrough", del: "strikethrough",
    };
    for (const node of children || []) {
      if (node.type === "html_inline") {
        const raw = (node.content || "").trim();
        if (/^<br\s*\/?\s*>$/i.test(raw)) {
          stack.at(-1)[1].push(["text", "\n"]);
          continue;
        }
        const match = raw.match(/^<\s*(\/?)\s*([a-z0-9]+)\s*>$/i);
        const tag = match?.[2]?.toLowerCase();
        if (tag && htmlStyles[tag]) {
          if (match[1]) {
            if (stack.length > 1 && stack.at(-1)[0] === tag) stack.pop();
          } else {
            const nested = [];
            stack.at(-1)[1].push(["span", htmlStyles[tag], nested]);
            stack.push([tag, nested]);
          }
          continue;
        }
      }
      stack.at(-1)[1].push(...this.compileInlineNode(node, sourcePath));
    }
    return output;
  }

  compileInlineNode(node, sourcePath) {
    const kind = node.type;
    if (kind === "text") return [["text", node.content || ""]];
    if (kind === "softbreak" || kind === "hardbreak") return [["text", "\n"]];
    if (kind === "code_inline") return [["span", "code", [["text", node.content || ""]]]];
    const spans = {
      strong: "strong", em: "emphasis", s: "strikethrough",
      sub: "subscript", sup: "superscript",
    };
    if (spans[kind]) {
      return [["span", spans[kind], this.compileInline(node.children, sourcePath)]];
    }
    if (kind === "link") {
      return [[
        "link", node.attrs?.href || "", node.attrs?.title || null,
        this.compileInline(node.children, sourcePath),
      ]];
    }
    if (kind === "image") return [this.compileImage(node, sourcePath)];
    if (kind === "footnote_ref") {
      const label = String(node.meta?.label ?? node.meta?.id ?? "");
      return [[
        "link", `#fn-${slug(label)}`, null,
        [["span", "footnote", [["text", `[${label}]`]]]],
      ]];
    }
    if (kind === "checkbox_input" || kind === "footnote_anchor") return [];
    if (kind === "html_inline") return [["text", node.content || ""]];
    if (node.children?.length) return this.compileInline(node.children, sourcePath);
    if (node.content) return [["text", node.content]];
    return [];
  }

  compileImage(node, sourcePath) {
    const source = String(node.attrs?.src || "");
    const alt = plainNodes(this.compileInline(node.children, sourcePath)).trim()
      || String(node.attrs?.alt || node.content || "").trim();
    const title = node.attrs?.title || null;
    if (/^[A-Za-z][A-Za-z0-9+.-]*:/.test(source) || source.startsWith("//")) {
      return ["text", alt || source];
    }
    const queryIndex = source.indexOf("?");
    if (queryIndex >= 0) throw new CompileError(`image query strings are not supported: ${source}`);
    let relative;
    try {
      relative = decodeURIComponent(source.split("#", 1)[0]);
    } catch (error) {
      throw new CompileError(`invalid image path: ${source}`);
    }
    if (!relative) return ["text", alt];
    const candidate = relative.startsWith("/")
      ? path.join(this.docsRoot, relative.replace(/^\/+/, ""))
      : path.resolve(path.dirname(sourcePath), relative);
    let resolved;
    try {
      resolved = fs.realpathSync(candidate);
    } catch (_error) {
      throw new CompileError(`local image is missing: ${source}`);
    }
    const prefix = this.docsRoot.endsWith(path.sep) ? this.docsRoot : this.docsRoot + path.sep;
    if (resolved !== this.docsRoot && !resolved.startsWith(prefix)) {
      throw new CompileError(`image escapes documentation root: ${source}`);
    }
    return ["image", this.assetStore.addFile(resolved), alt, title];
  }

  plainDocument(nodes) {
    const values = [];
    for (const node of nodes || []) {
      const text = this.plainNode(node).trim();
      if (text) values.push(text);
    }
    return values.join("\n");
  }

  plainNode(node) {
    if (!node) return "";
    const kind = node[0];
    if (kind === "text") return String(node[1] || "");
    if (kind === "span") return plainNodes(node[2]);
    if (kind === "link") return plainNodes(node[3]);
    if (kind === "heading") return plainNodes(node[3]);
    if (kind === "code_block") return String(node[1] || "");
    if (kind === "image" || kind === "diagram") return String(node[2] || "");
    if (kind === "block") {
      const children = node[2] || [];
      const inline = children.every(child => ["text", "span", "link", "image", "diagram"].includes(child?.[0]));
      return inline ? plainNodes(children) : this.plainDocument(children);
    }
    if (kind === "admonition") return `${node[2]}\n${this.plainDocument(node[3])}`;
    if (kind === "list") return this.plainDocument(node[2]);
    if (kind === "item") return this.plainDocument(node.length > 2 ? node[2] : node[1]);
    if (kind === "table") return this.plainDocument(node[1]);
    if (kind === "table_row") {
      const cells = node.length > 2 ? node[2] : node[1];
      return (cells || []).map(cell => this.plainNode(cell)).join(" | ");
    }
    if (kind === "table_cell") return plainNodes(node[1]);
    return "";
  }
}

function sha256(data) {
  return crypto.createHash("sha256").update(data).digest("hex");
}

function safeOutputPath(root, relative) {
  if (!relative || path.isAbsolute(relative) || relative.split(/[\\/]/).includes("..")) {
    throw new CompileError(`invalid output path: ${relative}`);
  }
  const target = path.resolve(root, relative);
  const prefix = root.endsWith(path.sep) ? root : root + path.sep;
  if (target !== root && !target.startsWith(prefix)) throw new CompileError(`output path escapes root: ${relative}`);
  return target;
}

async function compileBatch(filename) {
  const request = JSON.parse(fs.readFileSync(filename, "utf8"));
  if (request.schema_version !== 1 || !Array.isArray(request.items)) {
    throw new CompileError("invalid compiler batch request");
  }
  const docsRoot = fs.realpathSync(request.docs_root);
  const outputRoot = path.resolve(request.output_root);
  fs.mkdirSync(outputRoot, { recursive: true });
  const assets = new AssetStore(outputRoot);
  const renderer = new MermaidRenderer(request.mermaid_command);
  const highlighter = await createHighlighter({
    themes: Object.values(SHIKI_THEMES),
    langs: batchHighlightLanguages(request.items),
  });
  const compiler = new MarkdownCompiler(docsRoot, assets, renderer, highlighter);
  const results = [];
  for (const item of request.items) {
    if (!item || typeof item.id !== "string" || typeof item.text !== "string") {
      throw new CompileError("invalid compiler batch item");
    }
    const document = compiler.compile(item.text, item.source_path);
    const payload = stableStringify(document);
    const destination = safeOutputPath(outputRoot, item.output_path);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.writeFileSync(destination, payload, "utf8");
    results.push({
      id: item.id,
      sha256: sha256(Buffer.from(payload, "utf8")),
      headings: document.headings,
    });
  }
  return { schema_version: 1, items: results, assets: stableObject(assets.hashes) };
}

async function main() {
  const filename = process.argv[2];
  if (!filename || process.argv.length !== 3) {
    console.error("usage: markdown-compiler.mjs BATCH.json");
    return 2;
  }
  try {
    process.stdout.write(JSON.stringify(await compileBatch(filename)) + "\n");
    return 0;
  } catch (error) {
    console.error(`markdown-compiler.mjs: error: ${error.message || error}`);
    return 1;
  }
}

process.exitCode = await main();
