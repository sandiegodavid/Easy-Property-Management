import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = fileURLToPath(new URL("../", import.meta.url));
const configPath = fileURLToPath(new URL("../tsconfig.json", import.meta.url));
const host = {
  getCanonicalFileName: (fileName) => fileName,
  getCurrentDirectory: () => root,
  getNewLine: () => "\n",
};

function fail(diagnostics) {
  console.error(ts.formatDiagnosticsWithColorAndContext(diagnostics, host));
  process.exit(1);
}

const config = ts.readConfigFile(configPath, ts.sys.readFile);
if (config.error) fail([config.error]);
const parsed = ts.parseJsonConfigFileContent(config.config, ts.sys, root, undefined, configPath);

if (parsed.errors.length) fail(parsed.errors);
if (parsed.fileNames.length === 0) {
  throw new Error("Frontend type checking requires actual sources.");
} else {
  const program = ts.createProgram({
    rootNames: parsed.fileNames,
    options: parsed.options,
    projectReferences: parsed.projectReferences,
  });
  const diagnostics = ts.getPreEmitDiagnostics(program);
  if (diagnostics.length) fail(diagnostics);
  console.log(`Type checking passed (${parsed.fileNames.length} source files).`);
}
