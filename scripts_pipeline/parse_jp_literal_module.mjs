import vm from "node:vm";

const EXPORT_RE = /export\{([^}]*)\};\s*(?:\/\/# sourceMappingURL=.*)?\s*$/s;
const EXPORT_ITEM_RE = /^([A-Za-z_$][\w$]*)\s+as\s+([A-Za-z_$][\w$]*|default)$/;

/**
 * Parse the generated literal-only ES modules used by toho-vote.info.
 *
 * The module is evaluated in a fresh VM context without host functions,
 * filesystem/network access, dynamic string compilation, or WebAssembly.
 * Execution is time limited. Only the final static export list is rewritten.
 */
export function parseOfficialLiteralModule(source, { timeoutMs = 10_000 } = {}) {
  if (typeof source !== "string" || source.length === 0) {
    throw new TypeError("source must be a non-empty string");
  }
  if (source.length > 25_000_000) {
    throw new Error(`refusing unusually large module (${source.length} bytes)`);
  }

  const match = source.match(EXPORT_RE);
  if (!match) {
    throw new Error("static export list not found at end of module");
  }

  const exports = match[1]
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const item = part.match(EXPORT_ITEM_RE);
      if (!item) throw new Error(`unsupported export item: ${part}`);
      return { local: item[1], exported: item[2] };
    });

  if (!exports.some((item) => item.exported === "default")) {
    throw new Error("module does not expose a default export");
  }

  const exportObject = exports
    .map(({ local, exported }) => `${JSON.stringify(exported)}:${local}`)
    .join(",");
  const rewritten =
    source.slice(0, match.index) +
    `globalThis.__officialModuleExports=Object.freeze({${exportObject}});`;

  const sandbox = Object.create(null);
  const context = vm.createContext(sandbox, {
    name: "toho-vote-static-data",
    codeGeneration: { strings: false, wasm: false },
  });
  const script = new vm.Script(rewritten, {
    filename: "official-data-module.js",
    displayErrors: true,
  });
  script.runInContext(context, { timeout: timeoutMs, displayErrors: true });

  // Round-trip through JSON to remove cross-context prototypes and reject
  // values outside the data model used by the official generated modules.
  const serialized = JSON.stringify(sandbox.__officialModuleExports);
  if (serialized === undefined) throw new Error("module exports are not JSON serializable");
  return JSON.parse(serialized);
}

export function sanitizedDefaultExport(source, { omit = [] } = {}) {
  const exports = parseOfficialLiteralModule(source);
  const value = exports.default;
  if (value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) return value;
  const cleaned = { ...value };
  for (const key of omit) delete cleaned[key];
  return cleaned;
}

