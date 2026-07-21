import {readFileSync, writeFileSync} from "node:fs";
import {Recorder, exactReplay, type JsonValue, type TraceRun, validateTrace} from "../src/index.js";

const jsonl = (path: string): Record<string, any>[] => readFileSync(path, "utf8").split(/\r?\n/).filter(Boolean).map((line: string) => JSON.parse(line));
const [command, ...args] = process.argv.slice(2);

if (command === "bfcl") {
  const [casesPath, answersPath, outputPath, rawLimit = "10"] = args;
  if (!casesPath || !answersPath || !outputPath) throw new Error("bfcl requires cases answers output [limit]");
  const answers = new Map<string, Array<Record<string, JsonValue>>>(jsonl(answersPath).map(row => [row.id, row.ground_truth]));
  const runs = jsonl(casesPath).slice(0, Number(rawLimit)).map(row => {
    const recorder = new Recorder(`bfcl:${row.id}`, {dataset: "BFCL-v4", case_id: row.id});
    recorder.event({kind: "conversation", name: "user.request", request: row.question as JsonValue});
    for (const tool of row.function ?? []) recorder.event({kind: "tool_proposal", name: tool.name,
      request: tool.parameters as JsonValue, attributes: {description: tool.description ?? ""}});
    for (const expected of answers.get(row.id) ?? []) for (const [name, request] of Object.entries(expected as object))
      recorder.event({kind: "tool", name, request: request as JsonValue, response: {fixture: true}, attributes: {ground_truth: true}});
    return recorder.finish();
  });
  writeFileSync(outputPath, JSON.stringify(runs, null, 2) + "\n");
} else if (command === "validate-replay") {
  const [inputPath, outputPath] = args;
  if (!inputPath || !outputPath) throw new Error("validate-replay requires input output");
  const parsed: unknown = JSON.parse(readFileSync(inputPath, "utf8"));
  const runs = Array.isArray(parsed) ? parsed : [parsed];
  for (const run of runs) validateTrace(run);
  const results = (runs as TraceRun[]).map(run => exactReplay(run));
  writeFileSync(outputPath, JSON.stringify(results, null, 2) + "\n");
} else throw new Error("command must be bfcl or validate-replay");
