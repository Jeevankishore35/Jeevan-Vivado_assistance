import re
import os
import json
from symrtlo.dispatcher import get_llm_client
from symrtlo.parser import (
    parse_verilog, ASTNode, CaseNode, DeclNode, IdentifierNode
)
from symrtlo.data_flow import ASTTransformer

# Helper to recursively find a CaseNode in the AST
def find_case_node(node):
    if isinstance(node, CaseNode):
        return node
    for name, value in vars(node).items():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, ASTNode):
                    res = find_case_node(item)
                    if res: return res
        elif isinstance(value, ASTNode):
            res = find_case_node(value)
            if res: return res
    return None

class ASTStateReplacer(ASTTransformer):
    """Replaces state identifiers in AST (e.g. S3 -> S2)."""
    def __init__(self, old, new):
        super().__init__()
        self.old = old
        self.new = new
        
    def visit_IdentifierNode(self, node):
        if node.name == self.old:
            return IdentifierNode(self.new)
        return node

def heuristic_fsm_minimize(code, goal):
    """
    AST-based FSM state minimizer. Parses FSM Verilog into AST,
    identifies states with identical branch statements, merges them,
    and returns the optimized code.
    """
    try:
        module_ast = parse_verilog(code)
    except Exception as e:
        # Fallback to original code if parsing fails
        return code, False
        
    # 1. Find the FSM CaseNode
    case_node = find_case_node(module_ast)
    if not case_node:
        return code, False
        
    # 2. Extract state parameters and list of states
    state_params = {}
    for item in module_ast.items:
        if isinstance(item, DeclNode) and item.type == 'parameter':
            for name, val in item.decl_list:
                val_str = val.to_verilog() if hasattr(val, 'to_verilog') else str(val)
                state_params[name] = val_str
                
    if not state_params:
        return code, False
        
    # 3. Analyze case branches to find equivalent ones
    # Maps normalized branch verilog -> list of state names
    behavior_map = {}
    for branch in case_node.cases:
        conds, stmt = branch
        if not conds:
            continue
        state_name = conds[0].name if isinstance(conds[0], IdentifierNode) else str(conds[0])
        # Serialize branch statement to compare behaviors
        branch_verilog = stmt.to_verilog()
        # Normalize whitespace
        normalized = re.sub(r'\s+', ' ', branch_verilog).strip()
        behavior_map.setdefault(normalized, []).append(state_name)
        
    # Find equivalent states to merge
    merges = {}
    states_to_remove = set()
    for behavior, equiv_states in behavior_map.items():
        if len(equiv_states) >= 2:
            target_state = equiv_states[0]
            for redundant_state in equiv_states[1:]:
                merges[redundant_state] = target_state
                states_to_remove.add(redundant_state)
                
    if not merges:
        return code, False
        
    # 4. Apply replacements to all expressions in the module AST
    for old_state, new_state in merges.items():
        replacer = ASTStateReplacer(old_state, new_state)
        module_ast = replacer.visit(module_ast)
        
    # 5. Clean up FSM parameters
    # Remove merged parameters
    for item in module_ast.items:
        if isinstance(item, DeclNode) and item.type == 'parameter':
            new_decl_list = [(name, val) for name, val in item.decl_list if name not in states_to_remove]
            item.decl_list = new_decl_list
            
    # Clean up empty parameter declarations
    module_ast.items = [item for item in module_ast.items if not (isinstance(item, DeclNode) and item.type == 'parameter' and not item.decl_list)]
    
    # 6. Remove redundant case branches from the CaseNode
    # Reload case node from updated AST
    case_node = find_case_node(module_ast)
    if case_node:
        new_cases = []
        seen_states = set()
        for conds, stmt in case_node.cases:
            if conds:
                state_name = conds[0].name if isinstance(conds[0], IdentifierNode) else str(conds[0])
                if state_name not in seen_states:
                    seen_states.add(state_name)
                    new_cases.append((conds, stmt))
            else:
                new_cases.append((conds, stmt))
        case_node.cases = new_cases
        
    # Serialize back to Verilog
    optimized_code = module_ast.to_verilog()
    return optimized_code, True

def optimize_fsm(code, goal):
    """
    Optimizes the FSM in Verilog code by merging redundant states.
    Uses LLM if key is available, else falls back to heuristic minimization.
    """
    llm_info = get_llm_client()
    if not llm_info:
        opt_code, changed = heuristic_fsm_minimize(code, goal)
        return opt_code, ["HeuristicStateMerging"] if changed else []
        
    provider, client = llm_info
    prompt = f"""
You are a hardware engineering agent. Optimize the Finite State Machine (FSM) in the following Verilog code for the goal "{goal}".
Specifically, minimize states by identifying and merging equivalent states (states with identical output behaviors and transitions for all inputs).
Your output must be the complete, syntactically correct optimized Verilog code. Do not include explanation or markdown formatting, just return the code block.

Verilog Code:
{code}
"""

    try:
        if provider == "openai":
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}]
            )
            resp_content = response.choices[0].message.content
        elif provider == "gemini":
            model = client.GenerativeModel("gemini-1.5-pro")
            response = model.generate_content(prompt)
            resp_content = response.text
            
        # Extract code block if LLM returned markdown blocks
        code_match = re.search(r'```(?:verilog)?([\s\S]+?)```', resp_content, re.IGNORECASE)
        if code_match:
            return code_match.group(1).strip(), ["LLMStateMinimization"]
        return resp_content.strip(), ["LLMStateMinimization"]
        
    except Exception as e:
        opt_code, changed = heuristic_fsm_minimize(code, goal)
        return opt_code, ["HeuristicStateMerging"] if changed else []
