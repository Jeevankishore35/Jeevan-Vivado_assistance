import random
from symrtlo.parser import (
    parse_verilog, ASTNode, DeclNode, AssignNode, AlwaysNode, BlockNode,
    StmtAssignNode, IfNode, CaseNode, ConstantNode, IdentifierNode, BinaryOpNode, UnaryOpNode, TernaryNode, PartSelectNode
)

# ==============================================================================
# Helper to convert Verilog constant strings to Python ints
# ==============================================================================

def get_const_int(val_str):
    val_str = str(val_str).strip().replace('_', '')
    if "'" in val_str:
        parts = val_str.split("'")
        base_part = parts[1].lower()
        try:
            if base_part.startswith('d'):
                return int(base_part[1:])
            elif base_part.startswith('h'):
                return int(base_part[1:], 16)
            elif base_part.startswith('b'):
                return int(base_part[1:], 2)
            elif base_part.startswith('o'):
                return int(base_part[1:], 8)
        except ValueError:
            return 0
    else:
        try:
            return int(val_str)
        except ValueError:
            return 0

# ==============================================================================
# AST Evaluator
# ==============================================================================

def evaluate_expr(node, env):
    if isinstance(node, ConstantNode):
        return get_const_int(node.val)
    elif isinstance(node, IdentifierNode):
        return env.get(node.name, 0)
    elif isinstance(node, BinaryOpNode):
        left = evaluate_expr(node.left, env)
        right = evaluate_expr(node.right, env)
        op = node.op
        if op == '+': return left + right
        elif op == '-': return left - right
        elif op == '*': return left * right
        elif op == '/': return left // right if right != 0 else 0
        elif op == '%': return left % right if right != 0 else 0
        elif op == '&': return left & right
        elif op == '|': return left | right
        elif op == '^': return left ^ right
        elif op == '==': return int(left == right)
        elif op == '!=': return int(left != right)
        elif op == '<': return int(left < right)
        elif op == '>': return int(left > right)
        elif op == '<=': return int(left <= right)
        elif op == '>=': return int(left >= right)
        elif op == '&&': return int(left != 0 and right != 0)
        elif op == '||': return int(left != 0 or right != 0)
    elif isinstance(node, UnaryOpNode):
        val = evaluate_expr(node.val, env)
        op = node.op
        if op == '!': return int(not val)
        elif op == '~': return ~val
    elif isinstance(node, TernaryNode):
        cond = evaluate_expr(node.cond, env)
        if cond:
            return evaluate_expr(node.true_val, env)
        else:
            return evaluate_expr(node.false_val, env)
    elif isinstance(node, PartSelectNode):
        val = env.get(node.name, 0)
        try:
            msb = evaluate_expr(node.msb, env)
            if node.lsb is not None:
                lsb = evaluate_expr(node.lsb, env)
                high = max(msb, lsb)
                low = min(msb, lsb)
                mask = (1 << (high - low + 1)) - 1
                return (val >> low) & mask
            else:
                return (val >> msb) & 1
        except Exception:
            return val
    return 0

def write_env_var(lhs_node, value, env, pending=None):
    target = pending if pending is not None else env
    if isinstance(lhs_node, IdentifierNode):
        target[lhs_node.name] = value
    elif isinstance(lhs_node, PartSelectNode):
        var_name = lhs_node.name
        curr_val = env.get(var_name, 0)
        try:
            msb = evaluate_expr(lhs_node.msb, env)
            if lhs_node.lsb is not None:
                lsb = evaluate_expr(lhs_node.lsb, env)
                high = max(msb, lsb)
                low = min(msb, lsb)
                mask = ((1 << (high - low + 1)) - 1) << low
                curr_val &= ~mask
                val_masked = (value & ((1 << (high - low + 1)) - 1)) << low
                curr_val |= val_masked
            else:
                mask = 1 << msb
                curr_val &= ~mask
                if value & 1:
                    curr_val |= mask
            target[var_name] = curr_val
        except Exception:
            target[var_name] = value
    else:
        target[lhs_node.to_verilog()] = value

def execute_statement(stmt, env, pending_assigns):
    if isinstance(stmt, BlockNode):
        for s in stmt.statements:
            execute_statement(s, env, pending_assigns)
    elif isinstance(stmt, StmtAssignNode):
        rhs_val = evaluate_expr(stmt.rhs, env)
        if stmt.is_nonblocking:
            write_env_var(stmt.lhs, rhs_val, env, pending_assigns)
        else:
            write_env_var(stmt.lhs, rhs_val, env)
    elif isinstance(stmt, IfNode):
        cond = evaluate_expr(stmt.cond, env)
        if cond:
            execute_statement(stmt.true_stmt, env, pending_assigns)
        elif stmt.false_stmt:
            execute_statement(stmt.false_stmt, env, pending_assigns)
    elif isinstance(stmt, CaseNode):
        expr_val = evaluate_expr(stmt.expr, env)
        matched = False
        for conds, s in stmt.cases:
            for c in conds:
                if evaluate_expr(c, env) == expr_val:
                    execute_statement(s, env, pending_assigns)
                    matched = True
                    break
            if matched:
                break
        if not matched and stmt.default_stmt:
            execute_statement(stmt.default_stmt, env, pending_assigns)

# ==============================================================================
# Simulation Runner
# ==============================================================================

def simulate_design(module_ast, cycles, test_vectors):
    """
    Simulates the Verilog AST cycle-by-cycle using the provided test_vectors.
    Returns:
      outputs_history: list of dicts mapping output name -> value at each cycle.
    """
    # 1. Inspect design variables
    inputs = set()
    outputs = set()
    regs = set()
    params = {}
    
    for item in module_ast.items:
        if isinstance(item, DeclNode):
            # Resolve type
            types = [t.strip() for t in item.type.split()]
            names = [name for name, _ in item.decl_list]
            
            if 'parameter' in types:
                for name, init in item.decl_list:
                    params[name] = get_const_int(init.val) if init else 0
            else:
                if 'input' in types:
                    inputs.update(names)
                if 'output' in types:
                    outputs.update(names)
                if 'reg' in types:
                    regs.update(names)
                    
    # Initialize environment
    env = {}
    env.update(params)
    for reg in regs:
        env[reg] = 0
    for out in outputs:
        env[out] = 0
        
    outputs_history = []
    
    # 2. Simulate cycle-by-cycle
    for cycle in range(cycles):
        # Set inputs for this cycle
        cycle_inputs = test_vectors[cycle]
        env.update(cycle_inputs)
        
        # Clocked always blocks (state updates)
        pending = {}
        for item in module_ast.items:
            if isinstance(item, AlwaysNode):
                # Clocked trigger posedge/negedge clk
                is_clocked = any('clk' in s or 'clock' in s or 'posedge' in s for s in item.sensitivity)
                if is_clocked:
                    # Run transition block using inputs (like reset or clk triggers)
                    execute_statement(item.statement, env, pending)
                    
        # Apply pending clocked register updates
        env.update(pending)
        
        # Combinational evaluation relaxation loops (resolving assign & always @(*))
        for relaxation in range(10):
            changed = False
            
            # Evaluate assign statement nodes
            for item in module_ast.items:
                if isinstance(item, AssignNode):
                    var_name = item.lhs.name if hasattr(item.lhs, 'name') else item.lhs.to_verilog()
                    old_var_val = env.get(var_name, 0)
                    new_val = evaluate_expr(item.rhs, env)
                    write_env_var(item.lhs, new_val, env)
                    new_var_val = env.get(var_name, 0)
                    if old_var_val != new_var_val:
                        changed = True
                        
            # Evaluate always @(*) nodes
            for item in module_ast.items:
                if isinstance(item, AlwaysNode):
                    is_clocked = any('clk' in s or 'clock' in s or 'posedge' in s for s in item.sensitivity)
                    if not is_clocked:
                        # Combinational block, updates immediately
                        old_env = dict(env)
                        execute_statement(item.statement, env, {})
                        if any(env[k] != old_env[k] for k in env):
                            changed = True
                            
            if not changed:
                break
                
        # Record output signals
        cycle_outputs = {out: env.get(out, 0) for out in outputs}
        outputs_history.append(cycle_outputs)
        
    return outputs_history

# ==============================================================================
# Equivalence Checker
# ==============================================================================

def verify_equivalence(original_code, optimized_code, cycles=50):
    """
    Parses both designs, generates input stimulus, simulates them, and checks outputs.
    """
    try:
        orig_ast = parse_verilog(original_code)
        opt_ast = parse_verilog(optimized_code)
    except Exception as e:
        return False, f"Syntax or parse error during equivalence check: {e}"
        
    # Get inputs of original design
    inputs = set()
    for item in orig_ast.items:
        if isinstance(item, DeclNode):
            types = [t.strip() for t in item.type.split()]
            if 'input' in types:
                names = [name for name, _ in item.decl_list]
                inputs.update(names)
                
    # Remove clock and reset from random stimulus list since we manage clk/rst separately
    stimulus_inputs = [inp for inp in inputs if inp not in ('clk', 'clock', 'rst', 'reset')]
    
    # Generate test vectors
    test_vectors = []
    for cycle in range(cycles):
        vector = {}
        # Apply reset in first 2 cycles
        if cycle < 2:
            vector['rst'] = 1
            vector['reset'] = 1
        else:
            vector['rst'] = 0
            vector['reset'] = 0
            
        vector['clk'] = 1
        vector['clock'] = 1
        
        # Random inputs
        for inp in stimulus_inputs:
            vector[inp] = random.choice([0, 1, 5, 10, 255]) # mix of bit values
        test_vectors.append(vector)
        
    try:
        orig_outputs = simulate_design(orig_ast, cycles, test_vectors)
        opt_outputs = simulate_design(opt_ast, cycles, test_vectors)
    except Exception as e:
        return False, f"Simulation error: {e}"
        
    # Compare outputs cycle-by-cycle
    for cycle in range(cycles):
        orig_out = orig_outputs[cycle]
        opt_out = opt_outputs[cycle]
        
        # Check that all keys in original outputs match optimized
        for key in orig_out:
            if orig_out[key] != opt_out.get(key, None):
                return False, f"Mismatch at cycle {cycle}: signal {key} original={orig_out[key]}, optimized={opt_out.get(key)}"
                
    return True, "All cycles matched successfully."
