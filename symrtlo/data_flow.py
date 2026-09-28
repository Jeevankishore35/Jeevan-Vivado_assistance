import json
import re
from symrtlo.parser import (
    parse_verilog, ASTNode, ModuleNode, AssignNode, DeclNode, BinaryOpNode,
    ConstantNode, IdentifierNode, TernaryNode, UnaryOpNode, StmtAssignNode, IfNode, CaseNode, BlockNode, PartSelectNode
)

# ==============================================================================
# AST Base Visitor / Transformer
# ==============================================================================

class ASTTransformer:
    def visit(self, node):
        if node is None:
            return None
            
        method_name = f"visit_{type(node).__name__}"
        visitor = getattr(self, method_name, self.generic_visit)
        return visitor(node)
        
    def generic_visit(self, node):
        # By default, do nothing and return node
        return node

    def visit_ModuleNode(self, node):
        new_items = []
        for item in node.items:
            new_item = self.visit(item)
            if new_item:
                new_items.append(new_item)
        node.items = new_items
        return node
        
    def visit_DeclNode(self, node):
        return node
        
    def visit_AssignNode(self, node):
        node.lhs = self.visit(node.lhs)
        node.rhs = self.visit(node.rhs)
        return node
        
    def visit_AlwaysNode(self, node):
        node.statement = self.visit(node.statement)
        return node
        
    def visit_BlockNode(self, node):
        new_stmts = []
        for s in node.statements:
            new_s = self.visit(s)
            if new_s:
                new_stmts.append(new_s)
        node.statements = new_stmts
        return node
        
    def visit_StmtAssignNode(self, node):
        node.lhs = self.visit(node.lhs)
        node.rhs = self.visit(node.rhs)
        return node
        
    def visit_IfNode(self, node):
        node.cond = self.visit(node.cond)
        node.true_stmt = self.visit(node.true_stmt)
        if node.false_stmt:
            node.false_stmt = self.visit(node.false_stmt)
        return node
        
    def visit_CaseNode(self, node):
        node.expr = self.visit(node.expr)
        new_cases = []
        for conds, stmt in node.cases:
            new_conds = [self.visit(c) for c in conds]
            new_stmt = self.visit(stmt)
            new_cases.append((new_conds, new_stmt))
        node.cases = new_cases
        if node.default_stmt:
            node.default_stmt = self.visit(node.default_stmt)
        return node

    def visit_BinaryOpNode(self, node):
        node.left = self.visit(node.left)
        node.right = self.visit(node.right)
        return node
        
    def visit_UnaryOpNode(self, node):
        node.val = self.visit(node.val)
        return node
        
    def visit_TernaryNode(self, node):
        node.cond = self.visit(node.cond)
        node.true_val = self.visit(node.true_val)
        node.false_val = self.visit(node.false_val)
        return node
        
    def visit_IdentifierNode(self, node):
        return node
        
    def visit_ConstantNode(self, node):
        return node
        
    def visit_PartSelectNode(self, node):
        return node

# ==============================================================================
# AST Optimization Templates
# ==============================================================================

class ZeroMultiplicationTransformer(ASTTransformer):
    """Replaces A * 0 or 0 * A with 0."""
    def visit_BinaryOpNode(self, node):
        node.left = self.visit(node.left)
        node.right = self.visit(node.right)
        if node.op == '*':
            left_val = node.left.val if isinstance(node.left, ConstantNode) else None
            right_val = node.right.val if isinstance(node.right, ConstantNode) else None
            # Check if either is zero
            is_left_zero = left_val is not None and re.match(r'^(0|\d+\'[bhod]0+)$', left_val)
            is_right_zero = right_val is not None and re.match(r'^(0|\d+\'[bhod]0+)$', right_val)
            if is_left_zero or is_right_zero:
                return ConstantNode("0")
        return node

def parse_const_int(const_node):
    if not isinstance(const_node, ConstantNode):
        return None
    val_str = str(const_node.val).strip().replace('_', '')
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
            return None
    else:
        try:
            return int(val_str)
        except ValueError:
            return None

class ConstantFoldingTransformer(ASTTransformer):
    """Evaluates constant sub-expressions (e.g. 3 + 5 -> 8, A + 0 -> A)."""
    def visit_BinaryOpNode(self, node):
        node.left = self.visit(node.left)
        node.right = self.visit(node.right)
        
        left_int = parse_const_int(node.left)
        right_int = parse_const_int(node.right)
        
        # 1. Direct folding if both are constants
        if left_int is not None and right_int is not None:
            op = node.op
            res = None
            if op == '+': res = left_int + right_int
            elif op == '-': res = left_int - right_int
            elif op == '*': res = left_int * right_int
            elif op == '/': res = left_int // right_int if right_int != 0 else None
            elif op == '&': res = left_int & right_int
            elif op == '|': res = left_int | right_int
            elif op == '^': res = left_int ^ right_int
            
            if res is not None:
                return ConstantNode(str(res))
                
        # 2. Identity operations folding
        # A + 0 -> A
        if node.op == '+':
            if right_int == 0: return node.left
            if left_int == 0: return node.right
        # A - 0 -> A
        if node.op == '-':
            if right_int == 0: return node.left
        # A * 1 -> A
        if node.op == '*':
            if right_int == 1: return node.left
            if left_int == 1: return node.right
        # A - A -> 0
        if node.op == '-':
            if node.left.to_verilog() == node.right.to_verilog():
                return ConstantNode("0")
        # A | 0 -> A
        if node.op == '|':
            if right_int == 0: return node.left
            if left_int == 0: return node.right
        # A & 0 -> 0
        if node.op == '&':
            if right_int == 0 or left_int == 0: return ConstantNode("0")
            
        return node

class MuxReductionTransformer(ASTTransformer):
    """Simplifies ternary operators (Sel ? A : A -> A, 1 ? A : B -> A)."""
    def visit_TernaryNode(self, node):
        node.cond = self.visit(node.cond)
        node.true_val = self.visit(node.true_val)
        node.false_val = self.visit(node.false_val)
        
        # 1. If true and false branches are identical
        if node.true_val.to_verilog() == node.false_val.to_verilog():
            return node.true_val
            
        # 2. Constant condition folding
        if isinstance(node.cond, ConstantNode):
            cond_val = node.cond.val
            if cond_val in ('1', "1'b1", "32'd1"):
                return node.true_val
            if cond_val in ('0', "1'b0", "32'd0"):
                return node.false_val
                
        return node

class DeadCodeEliminationTransformer(ASTTransformer):
    """Removes if (0) branches."""
    def visit_IfNode(self, node):
        node.cond = self.visit(node.cond)
        node.true_stmt = self.visit(node.true_stmt)
        if node.false_stmt:
            node.false_stmt = self.visit(node.false_stmt)
            
        # Check if condition is a constant 0 or 1
        if isinstance(node.cond, ConstantNode):
            cond_val = node.cond.val
            if cond_val in ('0', "1'b0", "32'd0"):
                # If false branch exists, return it, else remove statement (return BlockNode([]))
                return node.false_stmt if node.false_stmt else BlockNode([])
            elif cond_val in ('1', "1'b1", "32'd1"):
                return node.true_stmt
                
        return node

def parse_width_to_bits(w_str):
    if not w_str:
        return 1
    w_str = w_str.strip()
    if not w_str:
        return 1
    match = re.match(r'\[\s*(\d+)\s*:\s*(\d+)\s*\]', w_str)
    if match:
        msb = int(match.group(1))
        lsb = int(match.group(2))
        return abs(msb - lsb) + 1
    match_single = re.match(r'\[\s*(\d+)\s*\]', w_str)
    if match_single:
        return 1
    return 1

def max_width_str(w1, w2):
    if not w1:
        return w2
    if not w2:
        return w1
    bits1 = parse_width_to_bits(w1)
    bits2 = parse_width_to_bits(w2)
    if bits1 >= bits2:
        return w1
    return w2

class SubexpressionEliminationTransformer(ASTTransformer):
    """Finds repeated binary expressions and extracts them to intermediate wires."""
    def __init__(self):
        super().__init__()
        self.expr_counts = {}
        self.expr_widths = {}
        self.sub_var_count = 0
        self.replacements = {}
        self.new_decls = []
        self.new_assigns = []
        self.var_widths = {}
        
    def get_expr_width(self, node):
        if isinstance(node, ConstantNode):
            val = node.val
            if "'" in val:
                parts = val.split("'")
                try:
                    size = int(parts[0])
                    return f"[{size-1}:0]"
                except ValueError:
                    pass
            return None
        elif isinstance(node, IdentifierNode):
            return self.var_widths.get(node.name, None)
        elif isinstance(node, PartSelectNode):
            try:
                msb_val = parse_const_int(node.msb) if isinstance(node.msb, ConstantNode) else None
                lsb_val = parse_const_int(node.lsb) if isinstance(node.lsb, ConstantNode) else None
                if msb_val is not None:
                    if lsb_val is not None:
                        return f"[{abs(msb_val - lsb_val)}:0]"
                    else:
                        return ""
            except Exception:
                pass
            return None
        elif isinstance(node, BinaryOpNode):
            if node.op in ('==', '!=', '<', '>', '<=', '>=', '&&', '||'):
                return ""
            w_left = self.get_expr_width(node.left)
            w_right = self.get_expr_width(node.right)
            return max_width_str(w_left, w_right)
        elif isinstance(node, UnaryOpNode):
            if node.op == '!':
                return ""
            return self.get_expr_width(node.val)
        elif isinstance(node, TernaryNode):
            w_true = self.get_expr_width(node.true_val)
            w_false = self.get_expr_width(node.false_val)
            return max_width_str(w_true, w_false)
        return None

    def collect_expressions(self, node, current_width=None):
        if node is None:
            return
            
        # Track wire width context
        if isinstance(node, (AssignNode, StmtAssignNode)):
            lhs = node.lhs
            if isinstance(lhs, IdentifierNode):
                current_width = self.var_widths.get(lhs.name, None)
            elif isinstance(lhs, PartSelectNode):
                try:
                    msb_val = parse_const_int(lhs.msb) if isinstance(lhs.msb, ConstantNode) else None
                    lsb_val = parse_const_int(lhs.lsb) if isinstance(lhs.lsb, ConstantNode) else None
                    if msb_val is not None:
                        if lsb_val is not None:
                            current_width = f"[{abs(msb_val - lsb_val)}:0]"
                        else:
                            current_width = ""
                except Exception:
                    current_width = None
            
        if isinstance(node, BinaryOpNode):
            # Only count expressions with at least one variable to avoid basic constant folding duplication
            has_var = not (isinstance(node.left, ConstantNode) and isinstance(node.right, ConstantNode))
            if has_var:
                expr_str = node.to_verilog()
                self.expr_counts[expr_str] = self.expr_counts.get(expr_str, 0) + 1
                
                natural_width = self.get_expr_width(node)
                effective_width = max_width_str(current_width, natural_width)
                
                existing_width = self.expr_widths.get(expr_str, None)
                self.expr_widths[expr_str] = max_width_str(existing_width, effective_width)
            
        # Recurse children
        for name, value in vars(node).items():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, ASTNode):
                        self.collect_expressions(item, current_width)
            elif isinstance(value, ASTNode):
                self.collect_expressions(value, current_width)

    def visit_BinaryOpNode(self, node):
        node.left = self.visit(node.left)
        node.right = self.visit(node.right)
        expr_str = node.to_verilog()
        if expr_str in self.replacements:
            return IdentifierNode(self.replacements[expr_str])
        return node

    def optimize_module(self, module_node):
        # 0. Collect all variable widths
        self.var_widths = {}
        for item in module_node.items:
            if isinstance(item, DeclNode):
                for name, _ in item.decl_list:
                    self.var_widths[name] = item.width
                    
        # 1. Collect expression occurrences
        self.collect_expressions(module_node)
        
        # Pick repeated expressions
        repeated = {expr: count for expr, count in self.expr_counts.items() if count >= 2}
        
        # 2. Build replacements
        for expr_str in repeated:
            var_name = f"symrtlo_sub_{self.sub_var_count}"
            self.sub_var_count += 1
            self.replacements[expr_str] = var_name
            
            # Determine width
            width = self.expr_widths.get(expr_str, None)
            if width == "":
                width = None
                
            # Find the original sub-expression node tree to build assign logic
            # For simplicity, we parse the expression string back to node tree
            temp_module = parse_verilog(f"module temp (); assign dummy = {expr_str}; endmodule")
            expr_node = temp_module.items[0].rhs
            
            self.new_decls.append(DeclNode("wire", [(var_name, None)], width))
            self.new_assigns.append(AssignNode(IdentifierNode(var_name), expr_node))
            
        # 3. Apply replacements
        module_node = self.visit(module_node)
        
        # 4. Insert new declarations & assignments at module level
        # Insert them right after port declarations
        insert_idx = 0
        for idx, item in enumerate(module_node.items):
            if isinstance(item, DeclNode):
                insert_idx = idx + 1
                
        for decl in reversed(self.new_decls):
            module_node.items.insert(insert_idx, decl)
        for assign in reversed(self.new_assigns):
            module_node.items.insert(insert_idx + len(self.new_decls), assign)
            
        return module_node

# ==============================================================================
# RAG Rules Search & Elbow Cutoff Selection
# ==============================================================================

def compute_similarity(code, goal, rule, dispatcher_suggestions):
    """Computes a similarity score between 0.0 and 1.0 for a rule."""
    score = 0.0
    
    # 1. Check if suggested by dispatcher
    if dispatcher_suggestions and rule["name"] in dispatcher_suggestions:
        score += 0.4
        
    # 2. Goal alignment
    goals = [g.strip().lower() for g in rule["objective_improvement"].split(",")]
    if goal.lower() in goals:
        score += 0.4
        
    # 3. Word overlap with Verilog code
    desc_words = set(re.findall(r'\b\w+\b', rule["description"].lower()))
    code_words = set(re.findall(r'\b\w+\b', code.lower()))
    overlap = len(desc_words.intersection(code_words)) / max(len(desc_words), 1)
    score += overlap * 0.2
    
    return score

def select_rules_elbow(code, goal, dispatcher_suggestions, rules_path="symrtlo/rules_library.json"):
    """Loads rules, calculates similarity, and filters using the Elbow Method."""
    with open(rules_path, "r") as f:
        rules = json.load(f)
        
    scored_rules = []
    for r in rules:
        score = compute_similarity(code, goal, r, dispatcher_suggestions)
        scored_rules.append((score, r))
        
    # Sort descending
    scored_rules.sort(key=lambda x: x[0], reverse=True)
    
    M = len(scored_rules)
    if M < 2:
        return [r for score, r in scored_rules]
        
    # Elbow: find index i that maximizes (s_i - s_{i+1})
    max_diff = -1.0
    elbow_idx = 0
    for i in range(M - 1):
        diff = scored_rules[i][0] - scored_rules[i+1][0]
        if diff > max_diff:
            max_diff = diff
            elbow_idx = i
            
    # Cutoff threshold
    tau_elbow = scored_rules[elbow_idx][0]
    
    # Select rules with score >= tau_elbow
    selected = [r for score, r in scored_rules if score >= tau_elbow]
    return selected

# ==============================================================================
# Main Data Flow Optimizer Entrypoint
# ==============================================================================

def optimize_data_flow(code, goal, dispatcher_suggestions):
    """Parses Verilog code, selects rules, and applies AST transformations."""
    # 1. Select rules
    selected_rules = select_rules_elbow(code, goal, dispatcher_suggestions)
    selected_names = [r["name"] for r in selected_rules]
    
    # 2. Parse code to AST
    ast = parse_verilog(code)
    
    # 3. Apply AST templates sequentially
    if "ZeroMultiplication" in selected_names:
        ast = ZeroMultiplicationTransformer().visit(ast)
        
    if "ConstantFolding" in selected_names:
        ast = ConstantFoldingTransformer().visit(ast)
        
    if "MuxReduction" in selected_names:
        ast = MuxReductionTransformer().visit(ast)
        
    if "DeadCodeElimination" in selected_names:
        ast = DeadCodeEliminationTransformer().visit(ast)
        
    if "SubexpressionElimination" in selected_names:
        ast = SubexpressionEliminationTransformer().optimize_module(ast)
        
    return ast.to_verilog(), selected_names
