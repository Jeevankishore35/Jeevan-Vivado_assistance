#!/usr/bin/env python
import argparse
import os
import sys

from symrtlo.dispatcher import dispatch_design
from symrtlo.data_flow import optimize_data_flow
from symrtlo.control_flow import optimize_fsm
from symrtlo.verifier import verify_equivalence
from symrtlo.vivado_runner import VivadoRunner

def main():
    parser = argparse.ArgumentParser(description="SymRTLO: Neuron-Symbolic RTL Optimizer")
    parser.add_argument("--input", help="Path to input Verilog file")
    parser.add_argument("--goal", choices=["area", "power", "timing"], default="area", help="Optimization goal (default: area)")
    parser.add_argument("--output", help="Path to write optimized Verilog file (defaults to <input_basename>_opt.v)")
    parser.add_argument("--vivado", action="store_true", help="Enable physical synthesis verification using Vivado CLI")
    parser.add_argument("--part", default="xc7a35tcsg324-1", help="Target FPGA part for Vivado synthesis (default: xc7a35tcsg324-1)")
    parser.add_argument("--vivado-path", help="Direct path to the Vivado executable")
    parser.add_argument("--top", help="Top-level module name for Vivado synthesis (overrides automatic detection)")
    parser.add_argument("--clear-cache", action="store_true", help="Clear the local synthesis cache database")
    
    args = parser.parse_args()
    
    if args.clear_cache:
        from symrtlo.cache_db import SymRTLOCache
        cache = SymRTLOCache()
        if cache.clear():
            print("Successfully cleared the synthesis cache database.")
        else:
            print("No cache database found or failed to clear.")
        sys.exit(0)
        
    if not args.input:
        parser.error("the following arguments are required: --input")
    
    if not os.path.exists(args.input):
        print(f"Error: Input file '{args.input}' does not exist.")
        sys.exit(1)
        
    with open(args.input, "r", encoding="utf-8") as f:
        original_code = f.read()
        
    print("======================================================================")
    print("                SymRTLO: Neuron-Symbolic RTL Optimizer                ")
    print("======================================================================")
    print(f"Target Design : {args.input}")
    print(f"Goal          : {args.goal}")
    print("----------------------------------------------------------------------")
    
    runner = None
    baseline_ppa = None
    if args.vivado:
        runner = VivadoRunner(target_part=args.part, vivado_path=args.vivado_path)
        if not runner.is_available():
            print("Error: Vivado executable could not be found.")
            print("Please make sure Vivado is installed and on your PATH, or specify it using --vivado-path.")
            sys.exit(1)
        print("Step 0: Running baseline Vivado physical synthesis...")
        baseline_ppa = runner.run_synthesis(original_code, top_module=args.top, goal=args.goal)
        if baseline_ppa and baseline_ppa.get("success"):
            if baseline_ppa.get("cached"):
                print("  [CACHE HIT] Loaded baseline PPA metrics from database.")
            print("  Baseline PPA Metrics:")
            print(f"    - LUTs: {baseline_ppa['luts']}")
            print(f"    - FFs:  {baseline_ppa['ffs']}")
            print(f"    - DSPs: {baseline_ppa['dsps']}")
            print(f"    - BRAMs: {baseline_ppa['brams']}")
            print(f"    - WNS:  {baseline_ppa['wns']} ns")
        else:
            print("  [ERROR] Baseline physical synthesis failed:")
            errors = baseline_ppa.get("errors", []) if baseline_ppa else ["Synthesis run returned empty result"]
            for err in errors:
                print(f"    * {err}")
            baseline_ppa = None
        print("----------------------------------------------------------------------")
    
    # Step 1: Dispatcher Analysis
    print("Step 1: Dispatcher Analysis...")
    dispatch_results = dispatch_design(original_code, args.goal)
    path = dispatch_results.get("optimization_path", "data_flow")
    suggested_rules = dispatch_results.get("suggested_rules", [])
    fsm_detected = dispatch_results.get("fsm_detected", False)
    
    print(f"  - Optimization Path Recommended: {path.upper()}")
    print(f"  - FSM Detected: {fsm_detected}")
    print(f"  - Suggested Rules: {', '.join(suggested_rules)}")
    print(f"  - Summary: {dispatch_results.get('summary', '')}")
    print("----------------------------------------------------------------------")
    
    # Step 2: Optimization
    print("Step 2: Performing Optimizations...")
    intermediate_code = original_code
    applied_rules = []
    
    # Run Data Flow Optimization if needed
    if path in ("data_flow", "both"):
        print("  - Running Data Flow Optimization (RAG rules + AST templates)...")
        opt_df, df_rules = optimize_data_flow(intermediate_code, args.goal, suggested_rules)
        intermediate_code = opt_df
        applied_rules.extend(df_rules)
        print(f"    * Applied Data Flow Rules: {', '.join(df_rules)}")
        
    # Run Control Flow FSM Optimization if needed
    if path in ("control_flow", "both") or fsm_detected:
        print("  - Running Control Flow (FSM State Minimization) Optimization...")
        opt_fsm, fsm_rules = optimize_fsm(intermediate_code, args.goal)
        intermediate_code = opt_fsm
        applied_rules.extend(fsm_rules)
        print(f"    * Applied Control Flow Mergers: {', '.join(fsm_rules)}")
        
    print("----------------------------------------------------------------------")
    
    # Step 3: Verification
    print("Step 3: Verification & Equivalence Checking...")
    eq_verified, msg = verify_equivalence(original_code, intermediate_code)
    if eq_verified:
        print("  [SUCCESS] Functional Equivalence Verified successfully!")
        print(f"  Detail: {msg}")
        
        # Step 3.5: Physical Synthesis Validation
        if runner and intermediate_code != original_code:
            print("----------------------------------------------------------------------")
            print("Step 3.5: Running physical synthesis validation on optimized RTL...")
            opt_ppa = runner.run_synthesis(intermediate_code, top_module=args.top, goal=args.goal)
            if opt_ppa and opt_ppa.get("success"):
                if opt_ppa.get("cached"):
                    print("  [CACHE HIT] Loaded optimized PPA metrics from database.")
                print("  Optimized PPA Metrics:")
                print(f"    - LUTs: {opt_ppa['luts']}")
                print(f"    - FFs:  {opt_ppa['ffs']}")
                print(f"    - DSPs: {opt_ppa['dsps']}")
                print(f"    - BRAMs: {opt_ppa['brams']}")
                print(f"    - WNS:  {opt_ppa['wns']} ns")
                
                if baseline_ppa:
                    print("  Physical Delta Comparison:")
                    lut_diff = opt_ppa['luts'] - baseline_ppa['luts']
                    ff_diff = opt_ppa['ffs'] - baseline_ppa['ffs']
                    wns_diff = opt_ppa['wns'] - baseline_ppa['wns']
                    
                    lut_pct = (lut_diff / baseline_ppa['luts'] * 100) if baseline_ppa['luts'] > 0 else 0.0
                    ff_pct = (ff_diff / baseline_ppa['ffs'] * 100) if baseline_ppa['ffs'] > 0 else 0.0
                    
                    print(f"    - LUTs Change: {lut_diff:+} ({lut_pct:+.1f}%) [{baseline_ppa['luts']} -> {opt_ppa['luts']}]")
                    print(f"    - FFs Change:  {ff_diff:+} ({ff_pct:+.1f}%) [{baseline_ppa['ffs']} -> {opt_ppa['ffs']}]")
                    print(f"    - WNS Change:  {wns_diff:+.3f} ns [{baseline_ppa['wns']:.3f} ns -> {opt_ppa['wns']:.3f} ns]")
                    
                    is_acceptable = True
                    if args.goal == "area" and lut_diff > 0:
                        print("  [WARNING] Optimized code uses more LUTs than baseline. Discarding optimization.")
                        is_acceptable = False
                    elif args.goal == "timing" and wns_diff < -0.05:
                        print("  [WARNING] Optimized code has worse timing (WNS). Discarding optimization.")
                        is_acceptable = False
                        
                    if not is_acceptable:
                        print("  Reverting to original code to maintain baseline physical quality.")
                        intermediate_code = original_code
            else:
                print("  [WARNING] Physical synthesis of optimized code failed. Discarding optimized code for safety.")
                errors = opt_ppa.get("errors", []) if opt_ppa else ["Synthesis run returned empty result"]
                for err in errors:
                    print(f"    * {err}")
                intermediate_code = original_code
    else:
        print("  [WARNING] Equivalence check failed or raised warning!")
        print(f"  Detail: {msg}")
        print("  Discarding optimized code to maintain functional safety.")
        intermediate_code = original_code
        
    print("----------------------------------------------------------------------")
    
    # Step 4: Write Output
    output_path = args.output
    if not output_path:
        base, ext = os.path.splitext(args.input)
        output_path = f"{base}_opt{ext}"
        
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(intermediate_code)
        
    print("Step 4: Writing Results...")
    print(f"  - Saved Optimized Verilog to: {output_path}")
    print("======================================================================")
    print("                        SymRTLO Job Completed                         ")
    print("======================================================================")

if __name__ == "__main__":
    main()
