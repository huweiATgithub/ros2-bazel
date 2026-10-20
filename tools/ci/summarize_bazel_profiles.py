#!/usr/bin/env python3
"""Summarize Bazel 9 JSON traces/BEP without third-party dependencies."""
import collections
import gzip
import json
import pathlib
import sys


def interval_union_seconds(events):
    intervals = sorted((e["ts"], e["ts"] + e["dur"]) for e in events)
    end = None
    total = 0
    for start, stop in intervals:
        total += max(0, stop - max(start, end if end is not None else start))
        end = max(stop, end if end is not None else stop)
    return total / 1e6


def summarize(path):
    label = path.name.removesuffix(".profile.gz")
    with gzip.open(path, "rt") as stream:
        trace = json.load(stream)
    events = [e for e in trace.get("traceEvents", [])
              if e.get("ph") == "X" and "dur" in e and "ts" in e]
    bep_path = path.parent / (label + ".bep.jsonl")
    bep = []
    if bep_path.exists():
        for line in bep_path.read_text().splitlines():
            try:
                bep.append(json.loads(line))
            except json.JSONDecodeError:
                # A killed invocation can leave one partial final event.
                continue
    metrics = next((e["buildMetrics"] for e in bep if "buildMetrics" in e), {})
    actions = [e for e in events if e.get("cat") == "action processing"]
    mnemonic = collections.defaultdict(lambda: [0, 0.0])
    owners = collections.defaultdict(lambda: [0, 0.0])
    for event in actions:
        args = event.get("args", {})
        kind = args.get("mnemonic", "unknown")
        target = args.get("target", args.get("target_label", args.get("label", "unknown")))
        owner = target.split("//")[0] if target.startswith("@") else "main workspace"
        if target == "unknown":
            owner = "unknown"
        for key, group in [(kind, mnemonic), (owner, owners)]:
            group[key][0] += 1
            group[key][1] += event["dur"] / 1e6
    categories = collections.defaultdict(list)
    for event in events:
        categories[event.get("cat", "unknown")].append(event)
    tests = [{"label": e.get("id", {}).get("testSummary", {}).get("label"),
              "summary": e["testSummary"]} for e in bep if "testSummary" in e]
    return {
        "label": label,
        "build_metrics": metrics,
        "finished": next((e["finished"] for e in bep if "finished" in e), {}),
        "tests": tests,
        "action_processing_by_mnemonic": dict(sorted(mnemonic.items(), key=lambda x: -x[1][1])),
        "action_processing_by_repository": dict(sorted(owners.items(), key=lambda x: -x[1][1])),
        "top_action_processing_events": sorted(actions, key=lambda e: -e["dur"])[:20],
        "critical_path_events": [e for e in events if "critical path" in e.get("cat", "")],
        "phase_events": [e for e in trace.get("traceEvents", []) if e.get("cat") == "build phase marker"],
        "trace_categories": {cat: {"count": len(items),
                                    "summed_seconds": sum(e["dur"] for e in items) / 1e6,
                                    "union_seconds": interval_union_seconds(items)}
                             for cat, items in sorted(categories.items())},
    }


def main():
    directory = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "ci-profiles")
    results = [summarize(path) for path in sorted(directory.glob("*.profile.gz"))]
    (directory / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    lines = ["# Bazel CI profile summary", "",
             "Initial means the first build on this fresh runner, potentially using a restored",
             "disk cache; see cache-restore.txt. Older uncached runs label this cold-build.",
             "Warm means an unchanged repeat in the SAME workspace/server, not a separate",
             "runner. Compare initial-build across runs to measure cross-runner caching.",
             "Action-processing durations overlap and include scheduling/overhead; they are",
             "not CPU time and must not be added to wall time. Category unions can also overlap.",
             "BEP phase times can overlap when analysis and execution are interleaved.",
             "See summary.json for raw BEP metrics, phase/critical-path events and category timing,",
             "and *.time.json for invocation wall time. Bazel 9 removed analyze-profile;",
             "these reports are extracted directly from JSON traces and BEP instead.", ""]
    for result in results:
        lines += ["## " + result["label"], "", "Build result: " + json.dumps(result["finished"].get("exitCode", {})), "", "BEP timing: " + json.dumps(result["build_metrics"].get("timingMetrics", {})),
                  "", "Action/cache counters: " + json.dumps(result["build_metrics"].get("actionSummary", {})),
                  "", "Top action-processing mnemonics (count, summed seconds):"]
        for key, (count, seconds) in list(result["action_processing_by_mnemonic"].items())[:10]:
            lines.append(f"- {key}: {count}, {seconds:.3f}s")
        lines += ["", "Action-processing by repository (count, summed seconds):"]
        for key, (count, seconds) in result["action_processing_by_repository"].items():
            lines.append(f"- {key}: {count}, {seconds:.3f}s")
        lines += ["", "Trace phases:"]
        for event in result["phase_events"]:
            if "dur" in event:
                lines.append(f"- {event.get('name', '?')}: {event['dur'] / 1e6:.3f}s")
            else:
                lines.append(f"- {event.get('name', '?')}: marker at {event['ts'] / 1e6:.3f}s")
        lines += ["", "Download/bootstrap categories (union wall seconds; may overlap phases):"]
        for category, data in result["trace_categories"].items():
            if any(word in category.lower() for word in ("fetch", "download", "module")):
                lines.append(f"- {category}: {data['union_seconds']:.3f}s")
        lines += ["", "Critical-path trace components:"]
        for event in result["critical_path_events"]:
            lines.append(f"- {event.get('name', '?')}: {event['dur'] / 1e6:.3f}s")
        lines.append("")
    report = "\n".join(lines) + "\n"
    (directory / "summary.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
