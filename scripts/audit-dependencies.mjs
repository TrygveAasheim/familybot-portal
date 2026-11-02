#!/usr/bin/env node

import { spawnSync } from "node:child_process";

// These are narrow, reviewed exceptions, not a severity-wide bypass. Remove an
// entry as soon as the affected toolchain can consume the patched dependency.
const allowedDevelopmentAdvisories = new Set([
  "GHSA-G3HV-75WG-M249", // minimatch <11; lint-only and incompatible with jsx-a11y today.
]);

function runAudit(extraArguments = []) {
  const result = spawnSync(
    "npm",
    ["audit", "--json", "--audit-level=low", ...extraArguments],
    { encoding: "utf8", maxBuffer: 20 * 1024 * 1024 },
  );
  if (result.error || ![0, 1].includes(result.status)) {
    throw new Error(result.error?.message || result.stderr || "npm audit failed unexpectedly");
  }
  let report;
  try {
    report = JSON.parse(result.stdout);
  } catch {
    throw new Error("npm audit did not return valid JSON");
  }
  if (report.error) {
    throw new Error(report.error.summary || report.error.message || "npm audit returned an error");
  }
  return report;
}

function advisoryId(advisory) {
  if (!advisory || typeof advisory !== "object" || typeof advisory.url !== "string") {
    return null;
  }
  return advisory.url.match(/(GHSA-[\w-]+)$/i)?.[1]?.toUpperCase() || null;
}

function main() {
  const report = runAudit();
  const productionReport = runAudit(["--omit=dev"]);
  const productionTotal = productionReport.metadata?.vulnerabilities?.total ?? 0;
  if (productionTotal !== 0) {
    throw new Error(`production dependency audit found ${productionTotal} known vulnerability finding(s)`);
  }

  const vulnerabilities = report.vulnerabilities || {};
  const packageNames = Object.keys(vulnerabilities);
  if (packageNames.length === 0) {
    console.log("Dependency audit OK: no known vulnerabilities.");
    return;
  }

  const unresolved = new Set();
  const collectAdvisories = (packageName, visiting = new Set()) => {
    if (visiting.has(packageName)) return new Set();
    const vulnerability = vulnerabilities[packageName];
    if (!vulnerability) {
      unresolved.add(`unknown dependency chain: ${packageName}`);
      return new Set();
    }
    const nextVisiting = new Set(visiting).add(packageName);
    const found = new Set();
    for (const via of vulnerability.via || []) {
      if (typeof via === "string") {
        for (const id of collectAdvisories(via, nextVisiting)) found.add(id);
      } else {
        const id = advisoryId(via);
        if (id) found.add(id);
        else unresolved.add(`unidentified advisory affecting ${packageName}`);
      }
    }
    return found;
  };

  const unexpected = new Set();
  for (const packageName of packageNames) {
    const ids = collectAdvisories(packageName);
    if (ids.size === 0) unresolved.add(`no advisory resolved for ${packageName}`);
    for (const id of ids) {
      if (!allowedDevelopmentAdvisories.has(id)) unexpected.add(id);
    }
  }
  if (unresolved.size > 0 || unexpected.size > 0) {
    const details = [...unresolved, ...[...unexpected].map((id) => `unapproved advisory: ${id}`)];
    throw new Error(`dependency audit found findings outside the reviewed allowlist:\n- ${details.join("\n- ")}`);
  }

  console.log(
    `Dependency audit OK: ${packageNames.length} development-only finding(s) trace solely to reviewed ` +
      `${[...allowedDevelopmentAdvisories].join(", ")}; production dependencies have no findings.`,
  );
}

try {
  main();
} catch (error) {
  console.error(`Dependency audit failed: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
}
