# SymRTLO: Universal Vivado AI Assistant & RTL / ASIC / FPGA Co-Pilot

A comprehensive AI & symbolic engineering assistant for **Xilinx Vivado, Verilog/SystemVerilog RTL coding, and FPGA/ASIC hardware design**.

---

## 🚀 Setup & Launch

1. **Prerequisites**: Python 3.10+ installed and added to PATH.
2. **1-Click Setup**: Double-click `install_vivado_assistant.bat`.
3. **Launch Console**: Double-click `run_vivado_assistant.bat` or run:
   ```powershell
   python vivado_assistant_cli.py
   ```

---

## ⚡ Text Prompts & Capabilities

| Prompt / Command | Description | Example |
| :--- | :--- | :--- |
| **`generate <spec>`** | Generates clean synthesizable Verilog/SystemVerilog modules | `generate synchronous fifo` / `generate uart` |
| **`review <file.v>`** | Static linting for latches, comb loops, blocking race conditions & CDC | `review my_design.v` |
| **`optimize <file.v>`** | Optimizes RTL for Area/Power/Timing with formal Z3 verification | `optimize adder.v for area` |
| **`scan <folder>`** | Project-wide RTL optimization scan | `scan examples/` |
| **`diagnose <log_file>`** | Diagnoses all Vivado errors (`[Synth 8-xxx]`, `[DRC xxx]`, `[Timing 38-xxx]`) | `diagnose vivado.log` |
| **`timing <report>`** | Evaluates clock slack (WNS/TNS) and failing critical paths | `timing timing_summary.rpt` |
| **`explain <error/topic>`**| Explains Vivado error codes or ASIC/FPGA hardware topics | `explain [Synth 8-3352]` / `explain cdc` |
| **`watch <folder>`** | Real-time live background watcher for active Vivado synthesis runs | `watch .` |
| **`voice on / voice off`**| Toggles optional spoken voice feedback | `voice on` |
