// Parses mermaid diagrams with mermaid's own parser under Node, with jsdom providing window and document.
// Reads a JSON array of {file, line, code} objects from stdin, prints one OK or FAIL line per diagram and
// exits with a non-zero status if any diagram fails to parse. Run by check_docs.py.
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>");
for (const name of ["window", "document", "navigator"]) {
  Object.defineProperty(globalThis, name, { value: dom.window[name], configurable: true, writable: true });
}

const chunks = [];
for await (const chunk of process.stdin) {
  chunks.push(chunk);
}
const diagrams = JSON.parse(Buffer.concat(chunks).toString("utf8"));
const { default: mermaid } = await import("mermaid");

let failed = 0;
for (const diagram of diagrams) {
  try {
    await mermaid.parse(diagram.code);
    console.log(`OK   mermaid ${diagram.file}:${diagram.line}`);
  } catch (error) {
    failed += 1;
    console.log(`FAIL mermaid ${diagram.file}:${diagram.line}: ${error.message ?? error}`);
  }
}
process.exit(failed === 0 ? 0 : 1);
