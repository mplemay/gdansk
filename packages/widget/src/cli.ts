#!/usr/bin/env node
import { resolve } from "node:path";

import { buildProject } from "./build";
import { startDevelopment } from "./development";

type Arguments = {
  command: "build" | "dev";
  host: string;
  manifest: string | undefined;
  outDirectory: string;
  port: number;
  root: string;
};

function parseArguments(argv: string[]): Arguments {
  const [command, ...rest] = argv;
  if (command !== "build" && command !== "dev") throw new Error("Usage: gdansk-widget <build|dev> [options]");
  const values = new Map<string, string>();
  for (let index = 0; index < rest.length; index += 2) {
    const key = rest[index];
    const value = rest[index + 1];
    if (!key?.startsWith("--") || typeof value === "undefined") throw new Error(`Invalid gdansk-widget argument ${JSON.stringify(key)}.`);
    values.set(key, value);
  }
  const root = resolve(values.get("--root") ?? process.cwd());
  return {
    command,
    host: values.get("--host") ?? "127.0.0.1",
    manifest: values.get("--manifest"),
    outDirectory: values.get("--out-dir") ?? "dist",
    port: Number.parseInt(values.get("--port") ?? "13714", 10),
    root,
  };
}

async function main(): Promise<void> {
  const options = parseArguments(process.argv.slice(2));
  if (options.command === "build") {
    await buildProject(options.root, options.outDirectory);
    return;
  }
  if (!options.manifest) throw new Error("gdansk-widget dev requires --manifest.");
  await startDevelopment({ host: options.host, manifest: resolve(options.manifest), port: options.port, root: options.root });
}

await main();
