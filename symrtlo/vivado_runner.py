import os
import re
import subprocess
import shutil
import tempfile
import sys
from symrtlo.parser import parse_verilog
from symrtlo.cache_db import SymRTLOCache

def find_vivado_executable():
    """
    Search for the Vivado executable in the system.
    Returns the absolute path to the executable, or None if not found.
    """
    # 1. Check if it's already in the PATH
    vivado_path = shutil.which("vivado")
    if vivado_path:
        return vivado_path

    # 2. Check environment variables
    env_vars = ["XILINX_VIVADO", "VIVADO_PATH"]
    for var in env_vars:
        val = os.environ.get(var)
        if val:
            # Check common subfolders
            for bin_name in ["vivado.bat", "vivado", "bin/vivado.bat", "bin/vivado"]:
                full_path = os.path.join(val, bin_name)
                if os.path.exists(full_path):
                    return os.path.abspath(full_path)

    # 3. Check common installation directories on Windows
    if sys.platform.startswith("win"):
        common_roots = [r"C:\Xilinx\Vivado", r"D:\Xilinx\Vivado"]
        for root in common_roots:
            if os.path.exists(root):
                # Versions are folder names like 2020.1, 2022.2, etc.
                versions = []
                try:
                    versions = os.listdir(root)
                except Exception:
                    continue
                # Sort versions descending to get the latest
                versions.sort(reverse=True)
                for ver in versions:
                    bat_path = os.path.join(root, ver, "bin", "vivado.bat")
                    if os.path.exists(bat_path):
                        return os.path.abspath(bat_path)

    # 4. Check common installation directories on Linux
    else:
        common_roots = ["/opt/Xilinx/Vivado", "/tools/Xilinx/Vivado"]
        for root in common_roots:
            if os.path.exists(root):
                versions = []
                try:
                    versions = os.listdir(root)
                except Exception:
                    continue
                versions.sort(reverse=True)
                for ver in versions:
                    sh_path = os.path.join(root, ver, "bin", "vivado")
                    if os.path.exists(sh_path):
                        return os.path.abspath(sh_path)

    return None

def get_top_module(code):
    """
    Tries to parse the module name from Verilog code.
    First uses the AST parser, then falls back to regex.
    """
    try:
        module_ast = parse_verilog(code)
        if hasattr(module_ast, 'name'):
            return module_ast.name
    except Exception:
        pass

    # Regex fallback
    match = re.search(r'\bmodule\s+([a-zA-Z_][a-zA-Z0-9_]*)\b', code)
    if match:
        return match.group(1)
    return "top"

def detect_clock_port(code):
    """
    Scans the input Verilog code for ports that look like clocks.
    """
    # Look for inputs: e.g. input clk, input sys_clk, input wire clk_in
    inputs = re.findall(r'\binput\s+(?:wire\s+|reg\s+)?(?:\[[^\]]+\]\s*)?([a-zA-Z_][a-zA-Z0-9_]*)\b', code)
    # Check for exact matches first
    clk_names = {"clk", "clock", "sys_clk", "mclk", "sysclk", "clk_in", "clkin", "clk_100", "clk_50"}
    for inp in inputs:
        if inp.lower() in clk_names:
            return inp
    # Check for containing clk or clock
    for inp in inputs:
        if "clk" in inp.lower() or "clock" in inp.lower():
            return inp
    return None

def parse_vivado_diagnostics(stdout, stderr):
    """
    Scans stdout and stderr for Xilinx Vivado errors and critical warnings.
    """
    diagnostics = []
    lines = (stdout or "").splitlines() + (stderr or "").splitlines()
    for line in lines:
        line_strip = line.strip()
        # Capture error and critical warnings
        if re.search(r'\b(ERROR|CRITICAL WARNING)\b', line_strip):
            if line_strip not in diagnostics:
                diagnostics.append(line_strip)
    return diagnostics

def parse_utilization_report(rpt_path):
    """
    Parses utilization.rpt and extracts resource usage.
    """
    metrics = {
        "luts": 0,
        "ffs": 0,
        "dsps": 0,
        "brams": 0
    }
    if not os.path.exists(rpt_path):
        return metrics

    with open(rpt_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Regex patterns for Xilinx Vivado utilization tables
    lut_match = re.search(r'Slice LUTs\s*\*?\s*\|\s*(\d+)', content, re.IGNORECASE)
    ff_match = re.search(r'Slice Registers\s*\|\s*(\d+)', content, re.IGNORECASE)
    dsp_match = re.search(r'DSPs\s*\|\s*(\d+)', content, re.IGNORECASE)
    # Check RAMB18 and RAMB36 for block RAMs
    ramb18_match = re.search(r'RAMB18[^\d|]*\|\s*(\d+)', content, re.IGNORECASE)
    ramb36_match = re.search(r'RAMB36[^\d|]*\|\s*(\d+)', content, re.IGNORECASE)

    if lut_match:
        metrics["luts"] = int(lut_match.group(1))
    if ff_match:
        metrics["ffs"] = int(ff_match.group(1))
    if dsp_match:
        metrics["dsps"] = int(dsp_match.group(1))
        
    b18 = int(ramb18_match.group(1)) if ramb18_match else 0
    b36 = int(ramb36_match.group(1)) if ramb36_match else 0
    metrics["brams"] = b36 + 0.5 * b18

    return metrics

def parse_timing_report(rpt_path):
    """
    Parses timing.rpt and extracts Worst Negative Slack (WNS).
    """
    wns = 999.0  # default large positive slack if timing passes easily
    if not os.path.exists(rpt_path):
        return wns

    with open(rpt_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    found_summary = False
    for i, line in enumerate(lines):
        if "Design Timing Summary" in line:
            found_summary = True
            continue
        
        if found_summary and "WNS(ns)" in line:
            # The values are usually 2 or 3 lines down
            # Look for the first line containing numbers after the WNS header
            for next_line in lines[i+1 : i+6]:
                stripped = next_line.strip()
                if not stripped or stripped.startswith("-"):
                    continue
                # Split and get the first floating point value
                parts = stripped.split()
                if parts:
                    try:
                        val = float(parts[0])
                        return val
                    except ValueError:
                        pass
            break

    return wns

class VivadoRunner:
    def __init__(self, target_part="xc7a35tcsg324-1", vivado_path=None):
        self.target_part = target_part
        self.vivado_path = vivado_path or find_vivado_executable()
        self.cache = SymRTLOCache()

    def is_available(self):
        return self.vivado_path is not None

    def run_synthesis(self, code, top_module=None, goal="area"):
        """
        Runs Vivado synthesis on the provided verilog code in batch mode.
        Returns a dictionary of PPA metrics: {luts, ffs, dsps, brams, wns} or None if failed.
        """
        # Check cache first
        cached_result = self.cache.get_cached_run(code, self.target_part, goal)
        if cached_result:
            return cached_result

        if not self.is_available():
            raise RuntimeError("Vivado executable not found. Make sure it is installed and on your PATH, or set the VIVADO_PATH environment variable.")

        # Resolve top module name if not provided
        if not top_module:
            top_module = get_top_module(code)

        # Create temporary working directory inside workspace
        workspace_dir = os.getcwd()
        temp_dir = tempfile.mkdtemp(dir=workspace_dir, prefix=".vivado_temp_")
        
        try:
            # Write Verilog code to a temporary file
            verilog_path = os.path.join(temp_dir, f"{top_module}.v")
            with open(verilog_path, "w", encoding="utf-8") as f:
                f.write(code)

            # Detect clock port for timing analysis
            clk_port = detect_clock_port(code)
            clk_tcl_command = ""
            if clk_port:
                clk_tcl_command = f"create_clock -name {clk_port} -period 10.000 [get_ports {clk_port}]"

            # Generate Tcl synthesis script
            tcl_path = os.path.join(temp_dir, "run_synth.tcl")
            util_rpt = os.path.join(temp_dir, "utilization.rpt")
            timing_rpt = os.path.join(temp_dir, "timing.rpt")
            
            # Normalize paths for Tcl (using forward slashes)
            verilog_tcl_path = verilog_path.replace("\\", "/")
            util_tcl_rpt = util_rpt.replace("\\", "/")
            timing_tcl_rpt = timing_rpt.replace("\\", "/")

            tcl_content = f"""
create_project -in_memory -part {{{self.target_part}}}
read_verilog {{{verilog_tcl_path}}}

if {{[catch {{synth_design -top {top_module} -part {{{self.target_part}}}}} err]}} {{
    puts "ERROR_SYNTH_FAILED: $err"
    exit 1
}}

if {{{ "1" if clk_tcl_command else "0" }}} {{
    {clk_tcl_command}
}}

report_utilization -file {{{util_tcl_rpt}}}
report_timing_summary -file {{{timing_tcl_rpt}}}
exit 0
"""
            with open(tcl_path, "w", encoding="utf-8") as f:
                f.write(tcl_content)

            # Execute Vivado in batch mode
            # We run it from the temp directory to keep the workspace clean
            cmd = [self.vivado_path, "-mode", "batch", "-source", "run_synth.tcl", "-nojournal", "-nolog"]
            
            # Run the process
            result = subprocess.run(
                cmd,
                cwd=temp_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300 # 5 minutes timeout
            )

            if result.returncode != 0:
                errors = parse_vivado_diagnostics(result.stdout, result.stderr)
                metrics = {
                    "success": False,
                    "errors": errors or [f"Vivado failed with return code {result.returncode}"]
                }
                self.cache.save_run(code, self.target_part, goal, metrics)
                return metrics

            # Parse reports
            util_metrics = parse_utilization_report(util_rpt)
            wns = parse_timing_report(timing_rpt)
            
            metrics = {
                **util_metrics,
                "wns": wns,
                "success": True,
                "errors": []
            }
            self.cache.save_run(code, self.target_part, goal, metrics)
            return metrics

        except subprocess.TimeoutExpired:
            metrics = {
                "success": False,
                "errors": ["Vivado synthesis timed out after 5 minutes."]
            }
            self.cache.save_run(code, self.target_part, goal, metrics)
            return metrics
        except Exception as e:
            metrics = {
                "success": False,
                "errors": [f"Error during Vivado synthesis execution: {e}"]
            }
            self.cache.save_run(code, self.target_part, goal, metrics)
            return metrics
        finally:
            # Clean up temporary directory
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
