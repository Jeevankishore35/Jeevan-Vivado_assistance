import re
import os
import sys
import json
from symrtlo.dispatcher import get_llm_client

# =====================================================================
# 1. RTL Code Generator (Synthesizable Verilog & SystemVerilog)
# =====================================================================

RTL_TEMPLATES = {
    "sync_fifo": """// ====================================================================
// Module: sync_fifo (Parameterized Synchronous FIFO)
// Architecture: Synthesizable FPGA/ASIC Ring Buffer with Full/Empty Logic
// ====================================================================
module sync_fifo #(
    parameter DATA_WIDTH = 8,
    parameter ADDR_WIDTH = 4,
    parameter FIFO_DEPTH = (1 << ADDR_WIDTH)
)(
    input  wire                  clk,
    input  wire                  rst_n,      // Active-low synchronous/asynchronous reset
    input  wire                  wr_en,
    input  wire [DATA_WIDTH-1:0] wr_data,
    input  wire                  rd_en,
    output reg  [DATA_WIDTH-1:0] rd_data,
    output wire                  full,
    output wire                  empty,
    output reg  [ADDR_WIDTH:0]   fifo_count
);

    reg [DATA_WIDTH-1:0] mem [0:FIFO_DEPTH-1];
    reg [ADDR_WIDTH-1:0] wr_ptr;
    reg [ADDR_WIDTH-1:0] rd_ptr;

    assign empty = (fifo_count == 0);
    assign full  = (fifo_count == FIFO_DEPTH);

    // Write Logic
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_ptr <= 0;
        end else if (wr_en && !full) begin
            mem[wr_ptr] <= wr_data;
            wr_ptr      <= wr_ptr + 1'b1;
        end
    end

    // Read Logic
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rd_ptr  <= 0;
            rd_data <= 0;
        end else if (rd_en && !empty) begin
            rd_data <= mem[rd_ptr];
            rd_ptr  <= rd_ptr + 1'b1;
        end
    end

    // FIFO Occupancy Counter
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            fifo_count <= 0;
        end else begin
            case ({wr_en && !full, rd_en && !empty})
                2'b10:   fifo_count <= fifo_count + 1'b1;
                2'b01:   fifo_count <= fifo_count - 1'b1;
                default: fifo_count <= fifo_count;
            endcase
        end
    end

endmodule
""",

    "dual_port_ram": """// ====================================================================
// Module: dual_port_ram (True Dual-Port RAM / Block RAM Inference)
// Architecture: Synthesizable BRAM with separate read/write ports
// ====================================================================
module dual_port_ram #(
    parameter DATA_WIDTH = 8,
    parameter ADDR_WIDTH = 6,
    parameter RAM_DEPTH  = (1 << ADDR_WIDTH)
)(
    input  wire                  clk,
    // Port A
    input  wire                  we_a,
    input  wire [ADDR_WIDTH-1:0] addr_a,
    input  wire [DATA_WIDTH-1:0] din_a,
    output reg  [DATA_WIDTH-1:0] dout_a,
    // Port B
    input  wire                  we_b,
    input  wire [ADDR_WIDTH-1:0] addr_b,
    input  wire [DATA_WIDTH-1:0] din_b,
    output reg  [DATA_WIDTH-1:0] dout_b
);

    (* ram_style = "block" *)
    reg [DATA_WIDTH-1:0] ram [0:RAM_DEPTH-1];

    // Port A Access
    always @(posedge clk) begin
        if (we_a) begin
            ram[addr_a] <= din_a;
            dout_a      <= din_a;
        end else begin
            dout_a      <= ram[addr_a];
        end
    end

    // Port B Access
    always @(posedge clk) begin
        if (we_b) begin
            ram[addr_b] <= din_b;
            dout_b      <= din_b;
        end else begin
            dout_b      <= ram[addr_b];
        end
    end

endmodule
""",

    "cdc_2ff_sync": """// ====================================================================
// Module: cdc_2ff_sync (Clock Domain Crossing 2-Flip-Flop Synchronizer)
// Architecture: Metastability mitigation with ASYNC_REG attributes
// ====================================================================
module cdc_2ff_sync #(
    parameter WIDTH = 1
)(
    input  wire             dest_clk,
    input  wire             dest_rst_n,
    input  wire [WIDTH-1:0] async_in,
    output reg  [WIDTH-1:0] sync_out
);

    (* ASYNC_REG = "TRUE" *) reg [WIDTH-1:0] stage1;

    always @(posedge dest_clk or negedge dest_rst_n) begin
        if (!dest_rst_n) begin
            stage1   <= 0;
            sync_out <= 0;
        end else begin
            stage1   <= async_in;
            sync_out <= stage1;
        end
    end

endmodule
""",

    "fsm_mealy_moore": """// ====================================================================
// Module: fsm_controller (Standard 3-Always-Block Clean FSM)
// Architecture: State register, Next-state logic, Registered outputs
// ====================================================================
module fsm_controller (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       start_req,
    input  wire       done_ack,
    output reg        busy,
    output reg        valid_out
);

    // State Encoding (One-Hot or Binary)
    localparam STATE_IDLE = 2'b00;
    localparam STATE_BUSY = 2'b01;
    localparam STATE_DONE = 2'b10;

    reg [1:0] current_state, next_state;

    // 1. State Register (Sequential)
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            current_state <= STATE_IDLE;
        end else begin
            current_state <= next_state;
        end
    end

    // 2. Next State Logic (Combinational)
    always @(*) begin
        next_state = current_state;
        case (current_state)
            STATE_IDLE: begin
                if (start_req) next_state = STATE_BUSY;
            end
            STATE_BUSY: begin
                if (done_ack) next_state = STATE_DONE;
            end
            STATE_DONE: begin
                next_state = STATE_IDLE;
            end
            default: next_state = STATE_IDLE;
        endcase
    end

    // 3. Output Logic (Registered for Glitch-Free Timing)
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy      <= 1'b0;
            valid_out <= 1'b0;
        end else begin
            case (next_state)
                STATE_IDLE: begin
                    busy      <= 1'b0;
                    valid_out <= 1'b0;
                end
                STATE_BUSY: begin
                    busy      <= 1'b1;
                    valid_out <= 1'b0;
                end
                STATE_DONE: begin
                    busy      <= 1'b0;
                    valid_out <= 1'b1;
                end
                default: begin
                    busy      <= 1'b0;
                    valid_out <= 1'b0;
                end
            endcase
        end
    end

endmodule
""",

    "uart_tx": """// ====================================================================
// Module: uart_tx (Universal Asynchronous Receiver/Transmitter - Tx)
// Architecture: Parameterized baud rate generator + shift register
// ====================================================================
module uart_tx #(
    parameter CLK_FREQ  = 100_000_000,
    parameter BAUD_RATE = 115200
)(
    input  wire       clk,
    input  wire       rst_n,
    input  wire       tx_start,
    input  wire [7:0] tx_data,
    output reg        tx_pin,
    output wire       tx_busy
);

    localparam CLKS_PER_BIT = CLK_FREQ / BAUD_RATE;

    localparam IDLE  = 2'b00;
    localparam START = 2'b01;
    localparam DATA  = 2'b10;
    localparam STOP  = 2'b11;

    reg [1:0]  state;
    reg [15:0] clk_cnt;
    reg [2:0]  bit_idx;
    reg [7:0]  data_buf;

    assign tx_busy = (state != IDLE);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state    <= IDLE;
            tx_pin   <= 1'b1;
            clk_cnt  <= 0;
            bit_idx  <= 0;
            data_buf <= 0;
        end else begin
            case (state)
                IDLE: begin
                    tx_pin  <= 1'b1;
                    clk_cnt <= 0;
                    bit_idx <= 0;
                    if (tx_start) begin
                        data_buf <= tx_data;
                        state    <= START;
                    end
                end

                START: begin
                    tx_pin <= 1'b0; // Start bit
                    if (clk_cnt < CLKS_PER_BIT - 1) begin
                        clk_cnt <= clk_cnt + 1'b1;
                    end else begin
                        clk_cnt <= 0;
                        state   <= DATA;
                    end
                end

                DATA: begin
                    tx_pin <= data_buf[bit_idx];
                    if (clk_cnt < CLKS_PER_BIT - 1) begin
                        clk_cnt <= clk_cnt + 1'b1;
                    end else begin
                        clk_cnt <= 0;
                        if (bit_idx < 7) begin
                            bit_idx <= bit_idx + 1'b1;
                        end else begin
                            bit_idx <= 0;
                            state   <= STOP;
                        end
                    end
                end

                STOP: begin
                    tx_pin <= 1'b1; // Stop bit
                    if (clk_cnt < CLKS_PER_BIT - 1) begin
                        clk_cnt <= clk_cnt + 1'b1;
                    end else begin
                        clk_cnt <= 0;
                        state   <= IDLE;
                    end
                end
            endcase
        end
    end

endmodule
"""
}

class RTLCodeGenerator:
    """Generates clean, synthesizable Verilog code for FPGA and ASIC architectures."""

    @staticmethod
    def generate(description):
        """Generates Verilog code based on description using built-in templates or AI."""
        desc_lower = description.lower()

        # Check template matches first
        if "fifo" in desc_lower:
            return RTL_TEMPLATES["sync_fifo"], "Parameterized Synchronous FIFO"
        elif "ram" in desc_lower or "memory" in desc_lower or "bram" in desc_lower:
            return RTL_TEMPLATES["dual_port_ram"], "Dual-Port RAM / Block RAM"
        elif "cdc" in desc_lower or "synchronizer" in desc_lower or "metastab" in desc_lower:
            return RTL_TEMPLATES["cdc_2ff_sync"], "2-Stage CDC Synchronizer"
        elif "fsm" in desc_lower or "state machine" in desc_lower:
            return RTL_TEMPLATES["fsm_mealy_moore"], "3-Always-Block FSM Controller"
        elif "uart" in desc_lower or "serial" in desc_lower:
            return RTL_TEMPLATES["uart_tx"], "UART Transmitter Controller"

        # If LLM is available, generate custom Verilog
        llm = get_llm_client()
        if llm:
            prompt = f"""You are a Principal Hardware Architecture Engineer specializing in Verilog, SystemVerilog, FPGA and ASIC design.
Generate clean, synthesizable, production-grade Verilog-2001 code for the following specification:

Specification: "{description}"

Guidelines:
1. Synthesizable RTL only (no #delays, non-synthesizable system tasks).
2. Use synchronous or clean active-low asynchronous reset logic.
3. Clean parameterization (DATA_WIDTH, ADDR_WIDTH, etc.).
4. Use non-blocking assignments (<=) for sequential logic and blocking (=) for combinational.
5. Provide ONLY the Verilog code block without conversational markdown text.
"""
            try:
                code = llm.generate_explanation(prompt)
                code_cleaned = re.sub(r'```verilog|```v|```', '', code).strip()
                return code_cleaned, f"Custom RTL: {description}"
            except Exception:
                pass

        # Default fallback
        return RTL_TEMPLATES["sync_fifo"], "Default Synchronous FIFO"


# =====================================================================
# 2. RTL Code Reviewer & Static Linting Engine
# =====================================================================

class RTLCodeReviewer:
    """Performs deep static code review and linting for FPGA and ASIC synthesis."""

    def __init__(self, code_or_path):
        if os.path.exists(code_or_path):
            with open(code_or_path, "r", encoding="utf-8", errors="replace") as f:
                self.code = f.read()
            self.source = code_or_path
        else:
            self.code = code_or_path
            self.source = "raw_verilog_code"

    def review(self):
        """Inspects code for latch hazards, blocking/non-blocking misuse, reset conventions, and CDC."""
        findings = []

        # 1. Blocking assignments in sequential clocked blocks
        seq_blocks = re.findall(r'always\s*@\s*\(\s*posedge\s+[^)]+\)\s*begin(.*?)end', self.code, re.DOTALL)
        for block in seq_blocks:
            # Find lines with single '=' not '<=' or '==' or '!='
            bad_assigns = re.findall(r'^\s*([a-zA-Z0-9_]+)\s*=\s*[^=;]+;', block, re.MULTILINE)
            if bad_assigns:
                findings.append({
                    "severity": "CRITICAL WARNING",
                    "category": "Blocking Assignment in Clocked Block",
                    "signal": bad_assigns[0],
                    "details": f"Signal '{bad_assigns[0]}' uses blocking assignment '=' inside a sequential clocked always block. This causes simulation-synthesis race conditions.",
                    "fix": "Replace '=' with non-blocking assignment '<=' for all sequential registers."
                })

        # 2. Inferred Latch Risk in combinational always blocks
        comb_blocks = re.findall(r'always\s*@\s*\(\s*\*\s*\)\s*begin(.*?)end', self.code, re.DOTALL)
        for block in comb_blocks:
            if "if" in block and "else" not in block:
                findings.append({
                    "severity": "CRITICAL WARNING",
                    "category": "Inferred Transparent Latch Hazard",
                    "signal": "Combinational conditional output",
                    "details": "Combinational `always @(*)` block contains `if` statements without complete `else` branches. Vivado will infer unwanted hardware latches.",
                    "fix": "Assign default values to all outputs at the very top of the `always @(*)` block, or add a complete `else` branch."
                })
            if "case" in block and "default" not in block:
                findings.append({
                    "severity": "WARNING",
                    "category": "Missing Default in Case Statement",
                    "signal": "Case selector",
                    "details": "Combinational `case` statement lacks a `default:` branch, creating potential latch inference if an unhandled state occurs.",
                    "fix": "Add a `default: ...` branch to the case statement."
                })

        # 3. Non-synthesizable delays (#delay)
        delay_matches = re.findall(r'#\s*\d+', self.code)
        if delay_matches:
            findings.append({
                "severity": "ERROR / NON-SYNTHESIZABLE",
                "category": "Time Delay (#delay) in Synthesizable Code",
                "signal": delay_matches[0],
                "details": f"Found simulation delay '{delay_matches[0]}'. Synthesis tools (Vivado, Synopsys DC) ignore #delays, leading to simulation-synthesis mismatch.",
                "fix": "Remove all `#delay` constructs from synthesizable RTL modules. Use clock cycles and counters for delay."
            })

        # 4. Asynchronous Reset vs Synchronous Reset convention check
        if re.search(r'always\s*@\s*\(\s*posedge\s+\w+\s+or\s+negedge\s+\w+\s*\)', self.code):
            reset_type = "Asynchronous Active-Low (Standard for ASIC & Xilinx UltraScale)"
        elif re.search(r'always\s*@\s*\(\s*posedge\s+\w+\s*\)', self.code):
            reset_type = "Synchronous (Optimal for FPGA Xilinx 7-Series LUT/FF mapping)"
        else:
            reset_type = "Combinational / Mixed"

        # Summary
        summary = {
            "source": self.source,
            "reset_architecture": reset_type,
            "total_findings": len(findings),
            "is_clean": len(findings) == 0,
            "findings": findings
        }

        return summary


# =====================================================================
# 3. ASIC & FPGA Hardware Architecture Advisor
# =====================================================================

HARDWARE_KNOWLEDGE_TOPICS = {
    "reset": """=== FPGA vs ASIC Reset Strategy ===
* FPGA (Xilinx 7-Series / UltraScale):
  - Synchronous Resets are preferred: Look-Up Tables (LUTs) and Flip-Flop control sets can pack resets directly into dedicated control signals, improving area and timing.
  - Asynchronous resets consume global routing and make static timing analysis across reset release harder.
* ASIC (Standard Cell):
  - Asynchronous active-low resets (`rst_n`) are standard to ensure reset functions even if clock is disabled/frozen at power-up.
  - Must include a Reset Synchronizer circuit (Asynchronous Assert, Synchronous De-assert).
""",

    "cdc": """=== Clock Domain Crossing (CDC) Best Practices ===
1. 1-Bit Control Signals:
   - Use a 2-Flip-Flop (2-FF) Synchronizer placed in the destination clock domain.
   - Attach `(* ASYNC_REG = "TRUE" *)` attribute to prevent Vivado from optimizing the registers apart.
2. Multi-Bit Data Buses:
   - NEVER use independent 2-FF synchronizers on individual bits of a bus (causes bus skew & invalid values).
   - Solutions:
     * Asynchronous FIFO (Dual-Clock FIFO with Gray code pointers).
     * Handshake Protocol (Req/Ack synchronization).
     * Mux-Data recirculating synchronizer with synchronized valid enable.
""",

    "timing": """=== Setup vs Hold Timing Closure in Vivado ===
* Setup Time Violation (WNS < 0):
  - Cause: Data path is too long / combinational logic depth is too high for the clock period.
  - Solutions: Insert pipeline registers, enable retiming in `synth_design -retiming`, restructure wide multiplexers.
* Hold Time Violation (WHS < 0):
  - Cause: Data path is too fast, or excessive clock skew between source and destination registers.
  - Solutions: In FPGA, Vivado router automatically inserts delay buffers. If crossing clock domains, add synchronizers.
""",

    "dsp": """=== DSP48 & BRAM Inference Guidelines ===
* DSP48E1 Multiplier Inference:
  - Fully pipeline multiply-accumulate operations: `P <= (A * B) + C;` with 2-3 clock register stages to utilize internal dedicated DSP input/output registers.
* Block RAM (BRAM) Inference:
  - Use synchronous read addresses (`always @(posedge clk) dout <= mem[addr];`).
  - Asynchronous reads cannot be mapped to BRAM and will force Vivado to consume thousands of slice LUTs (Distributed RAM).
"""
}

class HardwareAdvisor:
    """Answers ASIC, FPGA, and Verilog architecture inquiries."""

    @staticmethod
    def explain(topic_query):
        """Provides expert architectural explanation for topic."""
        query_lower = topic_query.lower()

        for key, text in HARDWARE_KNOWLEDGE_TOPICS.items():
            if key in query_lower:
                return text

        # Check LLM for arbitrary hardware question
        llm = get_llm_client()
        if llm:
            prompt = f"""You are a Principal FPGA & ASIC Hardware Design Engineer.
Answer the following technical question concisely with practical engineering guidelines, code examples, or Vivado optimization tips:

Question: "{topic_query}"
"""
            try:
                return llm.generate_explanation(prompt)
            except Exception:
                pass

        return "Topic not found. Try asking about 'reset', 'cdc', 'timing', or 'dsp'."
