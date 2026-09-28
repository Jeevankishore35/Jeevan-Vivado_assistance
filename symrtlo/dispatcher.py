import os
import re
import json

def get_llm_client():
    """Check environment variables and return an active LLM client wrapper or None."""
    # Try OpenAI
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        try:
            from openai import OpenAI
            return ("openai", OpenAI(api_key=openai_key))
        except ImportError:
            pass
            
    # Try Gemini
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            return ("gemini", genai)
        except ImportError:
            pass
            
    return None

def heuristic_dispatch(code, goal):
    """Fallback local analysis when no LLM key is available."""
    summary_lines = ["Local Heuristic Analysis:"]
    
    # 1. FSM Detection
    fsm_keywords = ["state", "next", "current_state", "nxt_state"]
    has_fsm_vars = any(kw in code.lower() for kw in fsm_keywords)
    has_case = "case" in code.lower()
    has_always_clk = "always" in code.lower() and ("clk" in code.lower() or "clock" in code.lower())
    
    fsm_detected = (has_fsm_vars or has_always_clk) and has_case
    if fsm_detected:
        summary_lines.append("- Detected FSM structure (clocked block with case transitions).")
        path = "both"
    else:
        summary_lines.append("- No clear clocked FSM structures found. Selecting Data Flow optimization.")
        path = "data_flow"
        
    # 2. Rule matching
    suggested_rules = []
    
    # Zero multiplication
    if re.search(r'\*\s*0|0\s*\*|multiplier', code.lower()):
        suggested_rules.append("ZeroMultiplication")
        summary_lines.append("- Found potential multiplication by zero or multiplier blocks.")
        
    # Constant folding
    if re.search(r'\d+\s*[\+\-\*\/]\s*\d+|\+\s*0|\*\s*1', code):
        suggested_rules.append("ConstantFolding")
        summary_lines.append("- Found arithmetic operations on constant literals.")
        
    # MUX reduction
    if "?" in code:
        suggested_rules.append("MuxReduction")
        summary_lines.append("- Found ternary operator (MUX) constructs.")
        
    # Subexpression elimination
    # Simple regex to check for repeated subexpressions like A+B
    terms = re.findall(r'\b[a-zA-Z_]\w*\s*[\+\-\&\|\^]\s*[a-zA-Z_]\w*\b', code)
    if len(terms) != len(set(terms)) and len(terms) > 0:
        suggested_rules.append("SubexpressionElimination")
        summary_lines.append("- Found repeated subexpressions (e.g. redundant arithmetic operations).")
    else:
        # Fallback to general suggestion
        suggested_rules.append("SubexpressionElimination")
        
    if "if" in code:
        suggested_rules.append("DeadCodeElimination")
        
    return {
        "fsm_detected": fsm_detected,
        "optimization_path": path,
        "suggested_rules": suggested_rules,
        "summary": " ".join(summary_lines)
    }

def dispatch_design(code, goal):
    """
    Analyzes the Verilog code and target goal. Returns:
    {
        "fsm_detected": bool,
        "optimization_path": "data_flow" | "control_flow" | "both",
        "suggested_rules": list of rule names,
        "summary": description of analysis
    }
    """
    llm_info = get_llm_client()
    if not llm_info:
        return heuristic_dispatch(code, goal)
        
    provider, client = llm_info
    prompt = f"""
Analyze the following Verilog code for the optimization goal "{goal}".
Provide the analysis in strict JSON format with the following keys:
- "fsm_detected": boolean, true if the code contains a Finite State Machine (FSM).
- "optimization_path": string, one of "data_flow", "control_flow", or "both".
- "suggested_rules": array of strings listing applicable rules from: ["ZeroMultiplication", "SubexpressionElimination", "ConstantFolding", "MuxReduction", "DeadCodeElimination"].
- "summary": string, summarizing your findings and structural features.

Verilog Code:
```verilog
{code}
```
"""

    try:
        if provider == "openai":
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
            
        elif provider == "gemini":
            model = client.GenerativeModel("gemini-1.5-pro")
            response = model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            return json.loads(response.text)
            
    except Exception as e:
        # If API call fails, fall back to heuristic method
        return heuristic_dispatch(code, goal)
