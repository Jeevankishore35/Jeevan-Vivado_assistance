#!/usr/bin/env python
import argparse
import os
import sys
import json
import time
import re

from symrtlo.assistant import (
    VivadoProjectScanner,
    VivadoLogDiagnoser,
    TimingSlackAnalyzer,
    VivadoProjectAdvisor,
    VivadoLiveWatcher,
    VIVADO_ERROR_KB
)
from symrtlo.data_flow import optimize_data_flow
from symrtlo.control_flow import optimize_fsm
from symrtlo.verifier import verify_equivalence
from symrtlo.dispatcher import dispatch_design
from symrtlo.rtl_copilot import RTLCodeGenerator, RTLCodeReviewer, HardwareAdvisor

# Optional Voice / TTS engine
tts_engine = None
VOICE_ENABLED = False

def init_optional_tts():
    global tts_engine
    try:
        import pyttsx3
        tts_engine = pyttsx3.init()
        tts_engine.setProperty("rate", 175)
        tts_engine.setProperty("volume", 0.9)
    except Exception:
        tts_engine = None

def assistant_speak(text):
    """Speaks out loud only if VOICE_ENABLED is True."""
    if VOICE_ENABLED and tts_engine:
        try:
            tts_engine.say(text)
            tts_engine.runAndWait()
        except Exception:
            pass

def print_banner():
    print("=" * 75)
    print("       VIVADO UNIVERSAL ASSISTANT & RTL / ASIC / FPGA CO-PILOT       ")
    print("=" * 75)
    print(" Mode: TEXT-PROMPTING (Primary) | Voice: OPTIONAL (Type 'voice on' to enable)")
    print(" Capabilities: Universal Error Diagnosis, RTL Generation, Linting & Timing Closure")
    print(" Type 'help' to see available text commands or type instructions in plain English.")
    print("=" * 75)

def handle_diagnose_log(log_path, use_llm=False):
    if not os.path.exists(log_path):
        print(f"[Error]: Log file '{log_path}' not found.")
        return
    print(f"\n[Vivado Diagnoser]: Analyzing log: {log_path}...")
    diagnoser = VivadoLogDiagnoser(log_path)
    res = diagnoser.diagnose(use_llm=use_llm)

    print("-" * 75)
    print(f"Status: {'PASS / SUCCESS' if res['is_successful'] else 'FAIL / ERRORS DETECTED'}")
    print(f"Total Errors           : {res['total_errors']}")
    print(f"Total Critical Warnings: {res['total_critical_warnings']}")
    print("-" * 75)

    if res["diagnoses"]:
        print("\n[*] Root Causes & Recommended Fixes:")
        for idx, item in enumerate(res["diagnoses"], start=1):
            print(f"\n[{idx}] Category: {item['category']}")
            print(f"    Raw Message : {item['raw_message']}")
            print(f"    Explanation : {item['explanation']}")
            print(f"    Suggested Fix: {item['fix_advice']}")
        
        msg = f"Found {res['total_errors']} errors. Primary issue is {res['diagnoses'][0]['category']}."
        assistant_speak(msg)
    else:
        print("\n[OK] No critical errors found in log!")
        assistant_speak("No critical errors found in Vivado log.")

    if res.get("ai_explanation"):
        print("\n[AI Insights & Recommendations]:")
        print(res["ai_explanation"])

def handle_timing(timing_rpt_path):
    if not os.path.exists(timing_rpt_path):
        print(f"[Error]: Timing report '{timing_rpt_path}' not found.")
        return
    print(f"\n[Timing Analyzer]: Analyzing report: {timing_rpt_path}...")
    analyzer = TimingSlackAnalyzer(timing_rpt_path)
    res = analyzer.analyze()

    print("-" * 75)
    print(f"Timing Met             : {'YES [PASS]' if res['timing_met'] else 'NO [VIOLATION]'}")
    print(f"Worst Negative Slack   : {res['wns']} ns")
    print(f"Total Negative Slack   : {res['tns']} ns")
    print(f"Failing Endpoints      : {res['failing_endpoints']}")
    print("-" * 75)

    if res["critical_paths"]:
        print("\n[!] Top Failing Critical Paths:")
        for idx, p in enumerate(res["critical_paths"], start=1):
            print(f"  [{idx}] Slack: {p['slack']} ns | Delay: {p['data_path_delay']} ns")
            print(f"      Source     : {p['source']}")
            print(f"      Destination: {p['destination']}")

    print("\n[Advice] Timing Closure Recommendations:")
    for rec in res["recommendations"]:
        print(f"  * {rec}")

    if res['timing_met']:
        assistant_speak(f"Timing constraints are met. Worst negative slack is {res['wns']} nanoseconds.")
    else:
        assistant_speak(f"Timing violation detected. Worst negative slack is {res['wns']} nanoseconds.")

def handle_optimize_file(file_path, goal="area", apply_fixes=True):
    if not os.path.exists(file_path):
        print(f"[Error]: File '{file_path}' not found.")
        return
    
    print(f"\n[Optimizer]: Analyzing & Optimizing '{file_path}' (Goal: {goal.upper()})...")
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        code = f.read()

    dispatch = dispatch_design(code, goal)
    print(f"  - Recommended Path : {dispatch.get('optimization_path', 'data_flow').upper()}")
    print(f"  - FSM Detected      : {dispatch.get('fsm_detected', False)}")
    print(f"  - Suggested Rules   : {', '.join(dispatch.get('suggested_rules', []))}")
    print(f"  - Summary           : {dispatch.get('summary', '')}")

    if apply_fixes:
        opt_code = code
        applied = []
        if dispatch.get("optimization_path") in ("data_flow", "both"):
            opt_code, rules = optimize_data_flow(opt_code, goal, dispatch.get("suggested_rules", []))
            applied.extend(rules)
        if dispatch.get("optimization_path") in ("control_flow", "both") or dispatch.get("fsm_detected"):
            opt_code, rules = optimize_fsm(opt_code, goal, dispatch.get("suggested_rules", []))
            applied.extend(rules)

        is_equiv, equiv_msg = verify_equivalence(code, opt_code)
        if is_equiv:
            out_file = file_path.replace(".v", "_opt.v") if file_path.endswith(".v") else file_path + "_opt.v"
            with open(out_file, "w", encoding="utf-8") as out_f:
                out_f.write(opt_code)
            print(f"\n[SUCCESS]: Formally verified equivalence (Z3 SMT Solver).")
            print(f"[OUTPUT]: Optimized Verilog saved to: {out_file}")
            print(f"[RULES APPLIED]: {', '.join(applied) if applied else 'None'}")
            assistant_speak(f"Optimization complete. Optimized Verilog saved to {os.path.basename(out_file)}.")
        else:
            print(f"[WARNING]: Formal equivalence verification failed ({equiv_msg}). Original code preserved.")

def handle_analyze_project(project_dir, goal="area", apply_fixes=False):
    print(f"\n[Project Advisor]: Scanning Vivado project in '{project_dir}'...")
    advisor = VivadoProjectAdvisor(project_dir)
    res = advisor.analyze_and_optimize_all(goal=goal, apply_fixes=apply_fixes)

    print("-" * 75)
    print(f"Total Verilog Files Found : {res['total_files']}")
    print(f"Total Optimization Rules  : {res['total_rules_suggested']}")
    print("-" * 75)

    for f in res["files_analyzed"]:
        print(f"\n[File]: {f['file_name']}")
        print(f"   Path: {f['file_path']}")
        if "error" in f:
            print(f"   [Error]: {f['error']}")
            continue
        print(f"   Architecture Detected : {f['path_recommended'].upper()} (FSM: {f['fsm_detected']})")
        print(f"   Suggested Rules       : {', '.join(f['suggested_rules']) if f['suggested_rules'] else 'None (Already Optimal)'}")
        print(f"   Summary               : {f['summary']}")
        if f.get("optimized_file"):
            print(f"   [Generated Optimized File]: {f['optimized_file']}")

    assistant_speak(f"Project scan complete. Found {res['total_files']} files with {res['total_rules_suggested']} optimization suggestions.")

def handle_generate_rtl(spec, save_path=None):
    print(f"\n[RTL Generator]: Generating synthesizable Verilog for '{spec}'...")
    code, title = RTLCodeGenerator.generate(spec)
    print("-" * 75)
    print(f"Architecture Title: {title}")
    print("-" * 75)
    print(code)
    print("-" * 75)

    if not save_path:
        # Default filename based on spec
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', spec.lower()).strip('_')[:20]
        save_path = f"{sanitized}.v"

    with open(save_path, "w", encoding="utf-8") as f:
        f.write(code)
    print(f"[Saved]: Synthesizable Verilog code saved to: '{save_path}'")
    assistant_speak(f"RTL code generated and saved to {save_path}.")

def handle_review_rtl(file_path):
    if not os.path.exists(file_path):
        print(f"[Error]: File '{file_path}' not found.")
        return
    print(f"\n[RTL Reviewer / Linter]: Performing static analysis on '{file_path}'...")
    reviewer = RTLCodeReviewer(file_path)
    res = reviewer.review()

    print("-" * 75)
    print(f"Reset Convention Detected : {res['reset_architecture']}")
    print(f"Lint Status               : {'CLEAN / SYNTHESIS READY' if res['is_clean'] else 'ISSUES / HAZARDS DETECTED'}")
    print(f"Total Findings            : {res['total_findings']}")
    print("-" * 75)

    if res["findings"]:
        print("\n[*] Static Linting Findings & Fixes:")
        for idx, f in enumerate(res["findings"], start=1):
            print(f"\n[{idx}] [{f['severity']}] {f['category']}")
            print(f"    Signal/Token: {f['signal']}")
            print(f"    Explanation : {f['details']}")
            print(f"    Action Item : {f['fix']}")
    else:
        print("\n[OK] Clean RTL code! No inferred latches, blocking race conditions, or non-synthesizable delays detected.")

def handle_explain_concept(query):
    print(f"\n[Hardware Architecture Advisor]: Query: '{query}'...")
    
    # First check error database for error codes (e.g. [Synth 8-3352])
    for kb in VIVADO_ERROR_KB:
        if re.search(kb["pattern"], query, re.IGNORECASE) or kb["category"].lower() in query.lower():
            print("-" * 75)
            print(f"Error Category : {kb['category']}")
            print(f"Explanation    : {kb['explanation']}")
            print(f"Recommended Fix: {kb['fix_advice']}")
            print("-" * 75)
            return

    # Check hardware topics (CDC, Reset, Timing, DSP)
    ans = HardwareAdvisor.explain(query)
    print("-" * 75)
    print(ans)
    print("-" * 75)

def live_event_handler(event):
    print("\n" + "=" * 75)
    print(f"[!] [LIVE VIVADO EVENT DETECTED]: {event['type']}")
    print(f"    Time: {event['timestamp']}")
    print(f"    File: {event['file']}")
    print("=" * 75)

    if event.get("diagnosis"):
        diag = event["diagnosis"]
        print(f"Total Errors: {diag['total_errors']} | Critical Warnings: {diag['total_critical_warnings']}")
        for d in diag["diagnoses"][:3]:
            print(f"  * {d['category']}: {d['explanation']}")
            print(f"    --> Fix: {d['fix_advice']}")
        if diag["total_errors"] > 0:
            assistant_speak(f"Vivado run finished with {diag['total_errors']} errors.")

    if event.get("timing"):
        timing = event["timing"]
        status_str = 'PASS' if timing['timing_met'] else 'FAIL'
        print(f"Timing Met: {status_str} (WNS: {timing['wns']} ns)")
        for rec in timing["recommendations"]:
            print(f"  * {rec}")
        assistant_speak(f"Timing analysis updated. Status is {status_str}.")

def handle_watch(project_dir):
    print(f"\n[Live Watcher]: Starting Real-time Vivado Project Watcher on: '{project_dir}'")
    print("Watching for synthesis / implementation updates and log outputs...")
    print("Press Ctrl+C to exit watching mode.\n")
    
    watcher = VivadoLiveWatcher(project_dir, on_event_callback=live_event_handler)
    try:
        watcher.start_polling(interval_seconds=2.5)
    except KeyboardInterrupt:
        watcher.stop()

# =====================================================================
# Interactive Text-Prompting Console
# =====================================================================

def interactive_text_console():
    global VOICE_ENABLED
    print_banner()

    print("\n[*] Available Text Prompt Capabilities:")
    print("   - generate <spec>       : e.g. 'generate synchronous fifo' or 'generate uart'")
    print("   - review <file.v>       : e.g. 'review my_design.v' (lints latches, comb loops, race conditions)")
    print("   - optimize <file.v>     : e.g. 'optimize examples/adder_subexpression.v for area'")
    print("   - scan <project_dir>    : e.g. 'scan examples/' (evaluates full project for PPA)")
    print("   - diagnose <log_path>   : e.g. 'diagnose vivado.log' (diagnoses all Vivado errors)")
    print("   - timing <report_path>  : e.g. 'timing timing_summary.rpt' (evaluates WNS & critical paths)")
    print("   - explain <error/topic> : e.g. 'explain [Synth 8-3352]' or 'explain cdc' or 'explain reset'")
    print("   - watch <project_dir>   : e.g. 'watch .' (live monitors open Vivado session)")
    print("   - voice on / voice off  : Toggles optional voice audio output")
    print("   - help / exit\n")

    while True:
        try:
            prompt = input("Vivado-Assistant >>> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting Vivado AI Assistant. Goodbye!")
            break

        if not prompt:
            continue

        prompt_lower = prompt.lower()

        # Exit
        if prompt_lower in ("exit", "quit", "q", "bye"):
            print("Exiting Vivado AI Assistant. Goodbye!")
            break

        # Voice Toggle
        elif prompt_lower in ("voice on", "enable voice", "turn voice on"):
            VOICE_ENABLED = True
            init_optional_tts()
            print("[Voice Mode]: ENABLED (Spoken voice audio output active).")
            assistant_speak("Voice feedback is now enabled.")
            continue

        elif prompt_lower in ("voice off", "disable voice", "turn voice off"):
            VOICE_ENABLED = False
            print("[Voice Mode]: DISABLED (Silent text-only mode active).")
            continue

        # Help
        elif prompt_lower in ("help", "?", "commands"):
            print("\nAvailable Commands & Text Prompts:")
            print("  1. generate <spec>                             - Generate synthesizable Verilog module")
            print("  2. review <file.v>                             - Lint Verilog for latches, CDC, ASIC/FPGA rules")
            print("  3. optimize <file.v> [for area|power|timing]   - Optimize RTL with formal Z3 proof")
            print("  4. scan <directory>                            - Scan entire project and optimize all files")
            print("  5. diagnose <log_path>                         - Diagnose any Vivado error/warning in log")
            print("  6. timing <report_path>                        - Evaluate clock slack & failing endpoints")
            print("  7. explain <error_code|concept>                - Explain error codes or ASIC/FPGA concepts")
            print("  8. watch <directory>                           - Live background monitor for open Vivado runs")
            print("  9. voice on / voice off                        - Toggle spoken voice output")
            print("  10. exit                                       - Quit assistant\n")
            continue

        # 1. RTL Generation
        elif prompt_lower.startswith("generate ") or prompt_lower.startswith("create rtl ") or "generate rtl" in prompt_lower:
            spec = prompt
            for prefix in ("generate ", "create rtl ", "generate rtl "):
                if prompt_lower.startswith(prefix):
                    spec = prompt[len(prefix):].strip()
                    break
            handle_generate_rtl(spec)

        # 2. RTL Code Review / Linting
        elif prompt_lower.startswith("review ") or prompt_lower.startswith("lint "):
            parts = prompt.split()
            target_file = parts[1] if len(parts) > 1 else "examples/adder_subexpression.v"
            handle_review_rtl(target_file)

        # 3. Explain Error or Concept
        elif prompt_lower.startswith("explain ") or prompt_lower.startswith("ask ") or prompt_lower.startswith("how to "):
            query = prompt
            for prefix in ("explain ", "ask ", "how to "):
                if prompt_lower.startswith(prefix):
                    query = prompt[len(prefix):].strip()
                    break
            handle_explain_concept(query)

        # 4. Optimize Single File
        elif prompt_lower.startswith("optimize ") or "optimize file" in prompt_lower:
            parts = prompt.split()
            file_match = re.search(r'([^\s]+\.v\b)', prompt)
            target_file = file_match.group(1) if file_match else (parts[1] if len(parts) > 1 else "examples/adder_subexpression.v")
            goal = "timing" if "timing" in prompt_lower else ("power" if "power" in prompt_lower else "area")
            handle_optimize_file(target_file, goal=goal, apply_fixes=True)

        # 5. Scan / Analyze Project
        elif prompt_lower.startswith("scan ") or prompt_lower.startswith("analyze ") or "scan project" in prompt_lower:
            parts = prompt.split()
            target_dir = "."
            for p in parts[1:]:
                if not p.startswith("-") and p not in ("project", "in", "for", "area", "power", "timing"):
                    target_dir = p
                    break
            goal = "timing" if "timing" in prompt_lower else ("power" if "power" in prompt_lower else "area")
            handle_analyze_project(target_dir, goal=goal, apply_fixes=True)

        # 6. Diagnose Log
        elif prompt_lower.startswith("diagnose ") or "check errors" in prompt_lower or "why did vivado fail" in prompt_lower:
            parts = prompt.split()
            log_file = "vivado.log"
            for p in parts:
                if p.endswith((".log", ".txt")):
                    log_file = p
                    break
            handle_diagnose_log(log_file, use_llm=False)

        # 7. Check Timing
        elif prompt_lower.startswith("timing ") or "check timing" in prompt_lower or "timing slack" in prompt_lower:
            parts = prompt.split()
            rpt_file = "timing_summary.rpt"
            for p in parts:
                if p.endswith((".rpt", ".txt", ".log")):
                    rpt_file = p
                    break
            handle_timing(rpt_file)

        # 8. Live Watch
        elif prompt_lower.startswith("watch ") or prompt_lower == "watch":
            parts = prompt.split()
            watch_dir = parts[1] if len(parts) > 1 else "."
            handle_watch(watch_dir)

        # 9. Fallback / Direct Path Handler
        else:
            if os.path.exists(prompt):
                if prompt.endswith((".v", ".sv")):
                    handle_optimize_file(prompt, goal="area", apply_fixes=True)
                elif prompt.endswith(".log"):
                    handle_diagnose_log(prompt)
                elif prompt.endswith(".rpt"):
                    handle_timing(prompt)
                elif os.path.isdir(prompt):
                    handle_analyze_project(prompt, goal="area", apply_fixes=True)
            else:
                # Check if it's an error code query like "[Synth 8-3352]"
                if re.search(r'\[(Synth|DRC|Timing|Place|Route|Bitstream|Constraints|Labtool|IP_Flow|BD)[^\]]*\]', prompt, re.IGNORECASE):
                    handle_explain_concept(prompt)
                elif "error" in prompt_lower or "fail" in prompt_lower:
                    handle_diagnose_log("vivado.log")
                elif "time" in prompt_lower or "slack" in prompt_lower or "wns" in prompt_lower:
                    handle_timing("timing_summary.rpt")
                elif "generate" in prompt_lower or "fifo" in prompt_lower or "ram" in prompt_lower or "fsm" in prompt_lower:
                    handle_generate_rtl(prompt)
                else:
                    handle_explain_concept(prompt)

def main():
    global VOICE_ENABLED
    parser = argparse.ArgumentParser(description="Vivado Universal AI Assistant & RTL / ASIC / FPGA Co-Pilot")
    parser.add_argument("--watch", help="Directory or Vivado project folder to watch in real-time")
    parser.add_argument("--analyze-project", help="Analyze and optimize all Verilog files in a Vivado project directory")
    parser.add_argument("--optimize", help="Path to single Verilog file to optimize")
    parser.add_argument("--generate", help="Generate synthesizable Verilog code (e.g. --generate 'sync fifo')")
    parser.add_argument("--review", help="Perform deep static linting on a Verilog file")
    parser.add_argument("--explain", help="Explain an error code (e.g. '[Synth 8-3352]') or hardware concept")
    parser.add_argument("--goal", choices=["area", "power", "timing"], default="area", help="Optimization goal")
    parser.add_argument("--apply-fixes", action="store_true", help="Generate optimized Verilog files (_opt.v)")
    parser.add_argument("--diagnose-log", help="Path to vivado.log or synthesis runme.log to diagnose errors")
    parser.add_argument("--timing", help="Path to timing_summary.rpt to evaluate clock slack and failing paths")
    parser.add_argument("--llm", action="store_true", help="Use AI (Gemini/OpenAI) for deeper natural language error insights")
    parser.add_argument("--voice", action="store_true", help="Enable optional voice spoken responses (default: text-only)")
    parser.add_argument("--chat", action="store_true", help="Launch interactive text-prompting console")

    args = parser.parse_args()

    if args.voice:
        VOICE_ENABLED = True
        init_optional_tts()

    # CLI flag execution
    if args.generate:
        handle_generate_rtl(args.generate)
    elif args.review:
        handle_review_rtl(args.review)
    elif args.explain:
        handle_explain_concept(args.explain)
    elif args.optimize:
        handle_optimize_file(args.optimize, goal=args.goal, apply_fixes=True)
    elif args.diagnose_log:
        handle_diagnose_log(args.diagnose_log, use_llm=args.llm)
    elif args.timing:
        handle_timing(args.timing)
    elif args.analyze_project:
        handle_analyze_project(args.analyze_project, goal=args.goal, apply_fixes=args.apply_fixes)
    elif args.watch:
        handle_watch(args.watch)
    else:
        # Default: Interactive Text Prompting Console
        interactive_text_console()

if __name__ == "__main__":
    main()
