import os
import re
import sys
import time
import json
from pathlib import Path
from symrtlo.parser import parse_verilog
from symrtlo.dispatcher import dispatch_design, get_llm_client
from symrtlo.data_flow import optimize_data_flow
from symrtlo.control_flow import optimize_fsm
from symrtlo.verifier import verify_equivalence

# =====================================================================
# 1. Vivado Project Scanner
# =====================================================================

class VivadoProjectScanner:
    """Scans Vivado project directories and .xpr files for Verilog sources, runs, and reports."""

    def __init__(self, root_path=None):
        self.root_path = os.path.abspath(root_path or os.getcwd())

    def find_all_verilog_files(self):
        """Discovers all Verilog (.v, .sv) source files in the project path."""
        verilog_files = []
        if os.path.isfile(self.root_path) and self.root_path.endswith(('.v', '.sv')):
            return [self.root_path]

        for root, dirs, files in os.walk(self.root_path):
            # Ignore hidden or build cache directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('__pycache__', 'sim_1')]
            for f in files:
                if f.endswith(('.v', '.sv')) and not f.endswith('_opt.v'):
                    verilog_files.append(os.path.join(root, f))
        return sorted(verilog_files)

    def find_latest_vivado_runs(self):
        """Finds the most recent synth_1 and impl_1 run folders and logs."""
        runs_info = {
            "project_dir": self.root_path,
            "xpr_file": None,
            "synth_run_dir": None,
            "impl_run_dir": None,
            "synth_log": None,
            "impl_log": None,
            "synth_util_rpt": None,
            "synth_timing_rpt": None,
            "impl_util_rpt": None,
            "impl_timing_rpt": None,
            "root_log": None
        }

        # Check for .xpr
        if os.path.isdir(self.root_path):
            for f in os.listdir(self.root_path):
                if f.endswith('.xpr'):
                    runs_info["xpr_file"] = os.path.join(self.root_path, f)
                    break
            
            # Check for root vivado.log
            root_log = os.path.join(self.root_path, "vivado.log")
            if os.path.exists(root_log):
                runs_info["root_log"] = root_log

            # Look for *.runs directory
            for root, dirs, files in os.walk(self.root_path):
                if os.path.basename(root) == "synth_1":
                    runs_info["synth_run_dir"] = root
                    for f in files:
                        if f.endswith(".log") and ("runme" in f or "synth" in f):
                            runs_info["synth_log"] = os.path.join(root, f)
                        elif "utilization" in f and f.endswith(".rpt"):
                            runs_info["synth_util_rpt"] = os.path.join(root, f)
                        elif "timing" in f and f.endswith(".rpt"):
                            runs_info["synth_timing_rpt"] = os.path.join(root, f)

                elif os.path.basename(root) == "impl_1":
                    runs_info["impl_run_dir"] = root
                    for f in files:
                        if f.endswith(".log") and ("runme" in f or "impl" in f):
                            runs_info["impl_log"] = os.path.join(root, f)
                        elif "utilization" in f and f.endswith(".rpt"):
                            runs_info["impl_util_rpt"] = os.path.join(root, f)
                        elif "timing" in f and f.endswith(".rpt"):
                            runs_info["impl_timing_rpt"] = os.path.join(root, f)

        return runs_info


# =====================================================================
# 2. Universal Vivado Error Knowledge Base & Diagnostic Engine
# =====================================================================

VIVADO_ERROR_KB = [
    # --- 1. Synthesis & Elaboration Errors [Synth 8-xxx] ---
    {
        "pattern": r"\[Synth 8-3352\]|\[DRC MDRV-1\]|multi-driven net|multiple drivers",
        "category": "Multi-Driven Net (Conflict)",
        "explanation": "A wire or signal is being assigned in multiple procedural always blocks or continuous assign statements simultaneously.",
        "fix_advice": "Ensure each register (reg/wire) is assigned in exactly ONE procedural always block. Merge conflicting assignments into a single block."
    },
    {
        "pattern": r"\[Synth 8-327\]|inferring latch",
        "category": "Unintended Latch Inferred",
        "explanation": "A combinational always block (`always @(*)`) does not assign values in all possible if/else or case branches, creating transparent hardware latches.",
        "fix_advice": "Assign default values to all outputs at the top of the combinational block, or ensure full coverage with `else` and `default` branches."
    },
    {
        "pattern": r"\[Synth 8-439\]|module '.*' not found|blackbox",
        "category": "Missing / Unbound Module (Blackbox)",
        "explanation": "A sub-module instantiation references a module name that is missing from the Vivado project hierarchy.",
        "fix_advice": "Check the spelling of the instantiated module name or add the missing `.v`/`.sv` file to the project sources (Add Sources > Design Sources)."
    },
    {
        "pattern": r"\[Synth 8-27\]|\[Synth 8-685\]|syntax error|unexpected token",
        "category": "Verilog Syntax / Grammar Error",
        "explanation": "Verilog syntax violation, missing semicolon, mismatched begin/end, unclosed parenthesis, or illegal port declaration.",
        "fix_advice": "Examine the referenced file and line number. Check for missing semicolons, unmatched begin/end pairs, or comma typos in port lists."
    },
    {
        "pattern": r"\[Synth 8-1002\]|unknown identifier|undeclared symbol",
        "category": "Undeclared Identifier / Signal",
        "explanation": "A variable, wire, or parameter is referenced before being declared in the module.",
        "fix_advice": "Declare the signal with `wire [N-1:0] name;` or `reg [N-1:0] name;` before using it in expressions."
    },
    {
        "pattern": r"\[Synth 8-467\]|port width mismatch|width mismatch",
        "category": "Port Bit-Width Mismatch",
        "explanation": "The bit-width of a connected signal does not match the port declaration width of the instantiated sub-module.",
        "fix_advice": "Check the port definitions in the sub-module. Adjust the signal slice or explicitly pad/truncate the connected vector."
    },
    {
        "pattern": r"\[Synth 8-5742\]|illegal part-select|out of bounds",
        "category": "Array Index / Part-Select Out of Bounds",
        "explanation": "An index or bit-slice operation accesses an index outside the declared vector range.",
        "fix_advice": "Verify the declared width `[MSB:LSB]`. Ensure dynamic indexing variables are masked or bounded within valid range."
    },
    {
        "pattern": r"\[Synth 8-690\]|combinatorial loop|combinational loop",
        "category": "Combinational Feedback Loop Detected",
        "explanation": "An output signal loops back to its own input combinational logic without passing through a clocked flip-flop register.",
        "fix_advice": "Break the loop by inserting a clocked register (`always @(posedge clk)`), or restructure intermediate assignments."
    },
    {
        "pattern": r"\[Synth 8-285\]|module instantiation loop|recursive instantiation",
        "category": "Recursive Module Instantiation Loop",
        "explanation": "A module instantiates itself or creates a circular instantiation loop among sub-modules.",
        "fix_advice": "Remove recursive instantiations. In synthesizable Verilog, use `generate` loops instead of recursion."
    },
    {
        "pattern": r"\[Synth 8-196\]|constant overflow|truncated constant",
        "category": "Constant Literal Overflow",
        "explanation": "A constant number literal has more bits than specified by its sized prefix (e.g. `4'd25`).",
        "fix_advice": "Increase the constant bit-width specifier (e.g. change `4'd25` to `8'd25`)."
    },
    {
        "pattern": r"\[Synth 8-2507\]|parameter override error|cannot resolve parameter",
        "category": "Parameter Resolution Error",
        "explanation": "Vivado cannot compute or resolve a constant parameter expression at compile time.",
        "fix_advice": "Ensure parameter values use only compile-time constant mathematical expressions and parameters defined earlier."
    },

    # --- 2. Design Rule Checks (DRC) & Pin Constraints ---
    {
        "pattern": r"\[DRC NSTD-1\]|\[DRC UCIO-1\]|unconstrained I/O|missing pin assignment",
        "category": "Unconstrained I/O Pins",
        "explanation": "Top-level I/O ports lack physical FPGA pin locations (`PACKAGE_PIN`) or voltage standards (`IOSTANDARD`).",
        "fix_advice": "Add `set_property PACKAGE_PIN <PIN> [get_ports <port>]` and `set_property IOSTANDARD LVCMOS33 [get_ports <port>]` to your `.xdc` file."
    },
    {
        "pattern": r"\[DRC CFGBVS-1\]|configuration bank voltage",
        "category": "Configuration Bank Voltage Select (CFGBVS) Missing",
        "explanation": "Vivado needs to know if the configuration bank voltage is 3.3V (VCCO) or 1.8V (GND) to set internal I/O slew rates.",
        "fix_advice": "Add `set_property CFGBVS VCCO [current_design]` and `set_property CONFIG_VOLTAGE 3.3 [current_design]` to your `.xdc` file."
    },
    {
        "pattern": r"\[DRC PLCK-12\]|clock placement|clock buffer required",
        "category": "Clock Placement / Missing Global Buffer (BUFG)",
        "explanation": "A clock signal is driven from non-clock-dedicated pins or standard fabric logic without routing through a BUFG global buffer.",
        "fix_advice": "Route your input clock through a dedicated clock-capable pin (`_CC`), or instantiate an explicit `BUFG` primitive: `BUFG clk_buf (.I(clk_in), .O(clk));`."
    },
    {
        "pattern": r"\[DRC REQP-1\]|DSP primitive mismatch|BRAM cascade rule",
        "category": "Primitive Packing Rule Violation (DSP/BRAM)",
        "explanation": "A block RAM or DSP48 primitive is configured with incompatible pipeline register or cascade settings.",
        "fix_advice": "Check the DSP/BRAM inference templates or instantiation attributes (`USE_MULT`, `PREG`, `RAM_MODE`)."
    },

    # --- 3. Static Timing & Clock Constraints ---
    {
        "pattern": r"\[Timing 38-282\]|unconstrained clock|no clock defined",
        "category": "Unconstrained Clock (Timing Analysis Disabled)",
        "explanation": "Vivado static timing engine has no clock frequency/period defined for timing closure evaluation.",
        "fix_advice": "Add `create_clock -name sys_clk -period 10.000 [get_ports clk]` to your project `.xdc` file."
    },
    {
        "pattern": r"\[Timing 38-91\]|negative slack|setup time violation|WNS < 0",
        "category": "Setup Timing Violation (Negative Slack / WNS)",
        "explanation": "The combinational delay between flip-flops exceeds the clock period constraint.",
        "fix_advice": "Insert pipeline register stages along the critical path, reduce logic levels, or lower the target clock frequency."
    },
    {
        "pattern": r"\[Timing 38-3\]|hold time violation|WHS < 0",
        "category": "Hold Timing Violation (Fast Path Race Condition)",
        "explanation": "Data arrives at the destination flip-flop before the minimum required hold time window.",
        "fix_advice": "Check clock skew across clock domains. If across domains, add a 2-stage synchronizer (`ASYNCREG`). Vivado implementation will insert delay buffers automatically."
    },
    {
        "pattern": r"\[Constraints 18-521\]|clock domain crossing|CDC hazard|unsafe crossing",
        "category": "Unsynchronized Clock Domain Crossing (CDC)",
        "explanation": "Signals cross asynchronously between different clock domains without synchronization registers, risking metastability.",
        "fix_advice": "Use a 2-Flip-Flop synchronizer for 1-bit control signals or an Asynchronous FIFO / Gray code counter for multi-bit data buses."
    },

    # --- 4. Placement, Routing & Optimization ---
    {
        "pattern": r"\[Place 30-574\]|pin placement collision|I/O bank collision",
        "category": "Pin Placement / Bank Conflict",
        "explanation": "Assigned pin locations exceed the I/O bank capacity or mix conflicting voltage standards (e.g. LVCMOS33 with LVDS25 in the same bank).",
        "fix_advice": "Verify that all pins mapped to the same FPGA I/O bank share compatible `IOSTANDARD` voltage levels."
    },
    {
        "pattern": r"\[Place 30-99\]|resource over-utilization|LUT overflow|FF overflow",
        "category": "FPGA Resource Over-Utilization",
        "explanation": "The design requires more LUTs, Flip-Flops, DSPs, or BRAMs than are physically present on the target FPGA chip.",
        "fix_advice": "Run SymRTLO area optimization (`--goal area`), time-multiplex arithmetic operators, or select a larger FPGA part."
    },
    {
        "pattern": r"\[Route 35-39\]|\[Route 35-54\]|unroutable|congestion|unrouted nets",
        "category": "Interconnect Routing Congestion",
        "explanation": "Routing channels are congested due to high fanout nets, wide multiplexers, or tight placement constraints.",
        "fix_advice": "Add pipeline registers to break up large wide multiplexers, run `opt_design`, and insert fanout replication for high-fanout nets."
    },
    {
        "pattern": r"\[Opt 31-67\]|clock buffer limit exceeded|too many BUFG",
        "category": "Global Clock Buffer (BUFG) Limit Exceeded",
        "explanation": "The design instantiates more global clock buffers (BUFG/BUFGCTRL) than the physical FPGA architecture supports (e.g., 32 on 7-series).",
        "fix_advice": "Consolidate clock signals. Use clock enables (`always @(posedge clk) if (clk_en)`) instead of generating gated clocks with separate buffers."
    },

    # --- 5. Bitstream Generation & Hardware Server ---
    {
        "pattern": r"\[Bitstream 40-1\]|unconstrained pins bitstream blocked",
        "category": "Bitstream Generation Blocked (DRC Error)",
        "explanation": "Vivado blocks `.bit` file generation because one or more I/O pins lack physical package pin constraints.",
        "fix_advice": "Ensure all top-level module ports have pin assignments in `.xdc`, or add `set_property SEVERITY {Warning} [get_drc_checks NSTD-1]` for testing."
    },
    {
        "pattern": r"\[Labtool 27-2269\]|\[Labtool 27-3165\]|no target found|cable not connected|JTAG scan failed",
        "category": "Hardware Server / JTAG Connection Error",
        "explanation": "Vivado Hardware Manager cannot detect the USB-JTAG programming cable or FPGA target device.",
        "fix_advice": "Check USB cable connection, verify Digilent/Xilinx cable drivers in Windows Device Manager, and ensure FPGA board power switch is turned ON."
    },

    # --- 6. IP Integrator & Block Design ---
    {
        "pattern": r"\[IP_Flow 19-3664\]|\[BD 41-1273\]|ip locked|ip upgrade required",
        "category": "Locked / Out-of-Date IP Core",
        "explanation": "An IP core was generated in an older Vivado version and must be upgraded before synthesis.",
        "fix_advice": "Run `upgrade_ip [get_ips]` in Vivado Tcl Console or right-click the IP and select 'Upgrade IP'."
    },
    {
        "pattern": r"\[BD 41-237\]|bus interface connection mismatch|AXI clock mismatch",
        "category": "Block Design Interface Mismatch",
        "explanation": "An AXI/AHB bus interface connection in Block Design has mismatched clock domains, bus widths, or active-low reset polarities.",
        "fix_advice": "Ensure both AXI master and slave share the same clock signal and matching reset polarity (e.g. `aresetn` is active-low)."
    }
]

class VivadoLogDiagnoser:
    """Diagnoses errors, critical warnings, and bottlenecks from Vivado log files."""

    def __init__(self, log_content_or_path):
        if os.path.exists(log_content_or_path):
            with open(log_content_or_path, "r", encoding="utf-8", errors="replace") as f:
                self.content = f.read()
            self.source_path = log_content_or_path
        else:
            self.content = log_content_or_path
            self.source_path = "raw_log_input"

    def diagnose(self, use_llm=False):
        """Analyzes log lines and returns structured diagnosis with root causes and fixes."""
        errors = []
        critical_warnings = []
        warnings = []
        
        for line in self.content.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            if re.search(r'\bERROR:\s*\[|\bERROR\b', line_str, re.IGNORECASE):
                if line_str not in errors:
                    errors.append(line_str)
            elif re.search(r'\bCRITICAL WARNING:\s*\[|\bCRITICAL WARNING\b', line_str, re.IGNORECASE):
                if line_str not in critical_warnings:
                    critical_warnings.append(line_str)
            elif re.search(r'\bWARNING:\s*\[Synth|\bWARNING:\s*\[DRC|\bWARNING:\s*\[Timing', line_str):
                if len(warnings) < 15 and line_str not in warnings:
                    warnings.append(line_str)

        matched_diagnoses = []
        all_issues = errors + critical_warnings

        for item in all_issues:
            matched = False
            for kb in VIVADO_ERROR_KB:
                if re.search(kb["pattern"], item, re.IGNORECASE):
                    matched_diagnoses.append({
                        "raw_message": item,
                        "category": kb["category"],
                        "explanation": kb["explanation"],
                        "fix_advice": kb["fix_advice"]
                    })
                    matched = True
                    break
            if not matched:
                matched_diagnoses.append({
                    "raw_message": item,
                    "category": "General Vivado Synthesis Issue",
                    "explanation": "Vivado reported an issue during processing.",
                    "fix_advice": "Check the line and module referenced in the message."
                })

        summary = {
            "total_errors": len(errors),
            "total_critical_warnings": len(critical_warnings),
            "is_successful": (len(errors) == 0),
            "diagnoses": matched_diagnoses,
            "errors": errors,
            "critical_warnings": critical_warnings,
            "sample_warnings": warnings[:5]
        }

        # Optional LLM refinement if API available and requested
        if use_llm and all_issues:
            try:
                llm = get_llm_client()
                if llm:
                    prompt = f"""You are an expert Xilinx Vivado and FPGA engineer.
Analyze these Vivado error messages and explain the root cause and step-by-step fix in 3 concise bullet points:

{json.dumps(all_issues[:5], indent=2)}
"""
                    ai_reply = llm.generate_explanation(prompt)
                    summary["ai_explanation"] = ai_reply
            except Exception:
                pass

        return summary


# =====================================================================
# 3. Timing & Slack Analyzer
# =====================================================================

class TimingSlackAnalyzer:
    """Parses Vivado timing reports (*timing_summary*.rpt) and evaluates slack."""

    def __init__(self, report_path_or_content):
        if os.path.exists(report_path_or_content):
            with open(report_path_or_content, "r", encoding="utf-8", errors="replace") as f:
                self.content = f.read()
            self.report_path = report_path_or_content
        else:
            self.content = report_path_or_content
            self.report_path = "raw_report"

    def analyze(self):
        """Extracts WNS, TNS, WHS, THS and failing paths."""
        results = {
            "wns": 999.0,
            "tns": 0.0,
            "whs": 999.0,
            "ths": 0.0,
            "failing_endpoints": 0,
            "timing_met": True,
            "critical_paths": [],
            "recommendations": []
        }

        # Parse Design Timing Summary table
        lines = self.content.splitlines()
        found_summary = False
        for i, line in enumerate(lines):
            if "Design Timing Summary" in line:
                found_summary = True
                continue
            
            if found_summary and ("WNS(ns)" in line or "WNS" in line):
                for next_line in lines[i+1 : i+10]:
                    stripped = next_line.strip()
                    if not stripped:
                        continue
                    # Skip decorative separator lines (e.g. ------- or | ------)
                    if re.match(r'^[\-\=\|\+\s]+$', stripped):
                        continue
                    parts = stripped.split()
                    if len(parts) >= 6:
                        try:
                            results["wns"] = float(parts[0])
                            results["tns"] = float(parts[1])
                            results["failing_endpoints"] = int(parts[2])
                            results["total_endpoints"] = int(parts[3])
                            results["whs"] = float(parts[4])
                            results["ths"] = float(parts[5])
                            break
                        except (ValueError, IndexError):
                            pass
                break

        # Timing met check
        if results["wns"] < 0.0:
            results["timing_met"] = False

        # Extract failing path summaries if any
        path_matches = re.findall(
            r'Slack\s*\((?:VIOLATED|MET)\)\s*:\s*([-\d\.]+)ns[^\n]*\n'
            r'(?:[^\n]*\n){1,6}?\s*Source:\s*([^\n]+)\n'
            r'\s*Destination:\s*([^\n]+)\n'
            r'(?:[^\n]*\n){1,6}?\s*Data Path Delay:\s*([-\d\.]+)ns',
            self.content, re.IGNORECASE
        )

        for match in path_matches[:3]:
            results["critical_paths"].append({
                "slack": float(match[0]),
                "source": match[1].strip(),
                "destination": match[2].strip(),
                "data_path_delay": float(match[3])
            })

        # Generate actionable advice
        if not results["timing_met"]:
            results["recommendations"].append(
                f"Negative Setup Slack (WNS: {results['wns']} ns). Critical paths exceed clock period."
            )
            results["recommendations"].append(
                "Suggested fix 1: Add a pipeline register stage along the longest combinational data path."
            )
            results["recommendations"].append(
                "Suggested fix 2: Use SymRTLO timing optimization (`--goal timing`) to restructure arithmetic expressions and FSM transitions."
            )
        else:
            results["recommendations"].append(
                f"Timing constraints MET (WNS: {results['wns']} ns). Circuit runs reliably at target clock frequency."
            )

        return results


# =====================================================================
# 4. Project RTL Optimizer & Advisor
# =====================================================================

class VivadoProjectAdvisor:
    """Analyzes all Verilog files in a Vivado project and provides SymRTLO optimization advice."""

    def __init__(self, project_dir):
        self.scanner = VivadoProjectScanner(project_dir)

    def analyze_and_optimize_all(self, goal="area", apply_fixes=False):
        """Scans project files, runs SymRTLO analysis, and outputs optimization potentials."""
        verilog_files = self.scanner.find_all_verilog_files()
        report = {
            "total_files": len(verilog_files),
            "files_analyzed": [],
            "total_rules_suggested": 0
        }

        for v_path in verilog_files:
            try:
                with open(v_path, "r", encoding="utf-8", errors="replace") as f:
                    code = f.read()

                dispatch = dispatch_design(code, goal)
                file_summary = {
                    "file_path": v_path,
                    "file_name": os.path.basename(v_path),
                    "path_recommended": dispatch.get("optimization_path", "data_flow"),
                    "fsm_detected": dispatch.get("fsm_detected", False),
                    "suggested_rules": dispatch.get("suggested_rules", []),
                    "summary": dispatch.get("summary", ""),
                    "optimized_file": None
                }

                if apply_fixes and dispatch.get("suggested_rules"):
                    opt_code = code
                    applied = []
                    if dispatch.get("optimization_path") in ("data_flow", "both"):
                        opt_code, rules = optimize_data_flow(opt_code, goal, dispatch.get("suggested_rules", []))
                        applied.extend(rules)
                    if dispatch.get("optimization_path") in ("control_flow", "both") or dispatch.get("fsm_detected"):
                        opt_code, rules = optimize_fsm(opt_code, goal, dispatch.get("suggested_rules", []))
                        applied.extend(rules)

                    # Verify formal equivalence
                    is_equiv, equiv_msg = verify_equivalence(code, opt_code)
                    if is_equiv:
                        out_path = str(Path(v_path).with_name(f"{Path(v_path).stem}_opt.v"))
                        with open(out_path, "w", encoding="utf-8") as out_f:
                            out_f.write(opt_code)
                        file_summary["optimized_file"] = out_path
                        file_summary["applied_rules"] = applied

                report["files_analyzed"].append(file_summary)
                report["total_rules_suggested"] += len(dispatch.get("suggested_rules", []))

            except Exception as e:
                report["files_analyzed"].append({
                    "file_path": v_path,
                    "file_name": os.path.basename(v_path),
                    "error": str(e)
                })

        return report


# =====================================================================
# 5. Live Project Watcher & Listener Daemon
# =====================================================================

class VivadoLiveWatcher:
    """Continuously monitors an open Vivado project directory for changes in logs and reports."""

    def __init__(self, project_path, on_event_callback=None):
        self.scanner = VivadoProjectScanner(project_path)
        self.callback = on_event_callback
        self.last_timestamps = {}
        self.running = False

    def check_once(self):
        """Checks for new/modified log files and dispatches diagnostics."""
        runs_info = self.scanner.find_latest_vivado_runs()
        events = []

        files_to_check = [
            ("Root Vivado Log", runs_info.get("root_log")),
            ("Synthesis Log", runs_info.get("synth_log")),
            ("Implementation Log", runs_info.get("impl_log")),
            ("Synthesis Timing Report", runs_info.get("synth_timing_rpt")),
            ("Implementation Timing Report", runs_info.get("impl_timing_rpt")),
            ("Synthesis Utilization Report", runs_info.get("synth_util_rpt")),
            ("Implementation Utilization Report", runs_info.get("impl_util_rpt"))
        ]

        for desc, fpath in files_to_check:
            if fpath and os.path.exists(fpath):
                mtime = os.path.getmtime(fpath)
                last_mtime = self.last_timestamps.get(fpath, 0)
                if mtime > last_mtime:
                    self.last_timestamps[fpath] = mtime
                    # Only fire event if this is not the initial baseline scan
                    if last_mtime > 0:
                        event_data = self._process_file_event(desc, fpath)
                        events.append(event_data)
                        if self.callback:
                            self.callback(event_data)
                    else:
                        # Register initial state
                        self.last_timestamps[fpath] = mtime

        return events

    def _process_file_event(self, desc, fpath):
        """Processes a modified file and produces a diagnostic event object."""
        event = {
            "type": desc,
            "file": fpath,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "diagnosis": None,
            "timing": None
        }

        if "Log" in desc:
            diagnoser = VivadoLogDiagnoser(fpath)
            event["diagnosis"] = diagnoser.diagnose()
        elif "Timing" in desc:
            analyzer = TimingSlackAnalyzer(fpath)
            event["timing"] = analyzer.analyze()

        return event

    def start_polling(self, interval_seconds=3.0):
        """Starts continuous polling loop."""
        self.running = True
        print(f"[VivadoLiveWatcher]: Monitoring '{self.scanner.root_path}' every {interval_seconds}s...")
        # Initial scan to record baselines
        self.check_once()
        while self.running:
            try:
                time.sleep(interval_seconds)
                self.check_once()
            except KeyboardInterrupt:
                self.stop()
                break

    def stop(self):
        self.running = False
        print("[VivadoLiveWatcher]: Watcher stopped.")
