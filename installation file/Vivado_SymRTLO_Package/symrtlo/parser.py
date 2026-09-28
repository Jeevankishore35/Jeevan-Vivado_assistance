import re

# ==============================================================================
# Verilog Tokenizer
# ==============================================================================

TOKEN_SPEC = [
    ('COMMENT_MULTI', r'/\*[\s\S]*?\*/'),
    ('COMMENT_SINGLE', r'//.*'),
    ('CONST_HEX',     r'\d+\'h[0-9a-fA-F_]+'),
    ('CONST_BIN',     r'\d+\'b[01_]+'),
    ('CONST_DEC_SIZED', r'\d+\'d\d+'),
    ('NUMBER',        r'\d+'),
    ('KEYWORD',       r'\b(module|endmodule|input|output|wire|reg|assign|always|begin|end|if|else|case|endcase|default|posedge|negedge|or|parameter|localparam|inout)\b'),
    ('IDENTIFIER',    r'[a-zA-Z_][a-zA-Z0-9_$]*'),
    ('OP_TERNARY',    r'\?'),
    ('OP_COLON',      r':'),
    ('OP_ASSIGN_NB',  r'<='),
    ('OP_COMP',       r'==|!=|>=|<|>'),
    ('OP_LOGIC',      r'&&|\|\|'),
    ('OP_ASSIGN',     r'='),
    ('OP_ARITH',      r'\+|-|\*|/|%'),
    ('OP_BITWISE',    r'&|\||\^|~'),
    ('LPAREN',        r'\('),
    ('RPAREN',        r'\)'),
    ('LBRACKET',      r'\['),
    ('RBRACKET',      r'\]'),
    ('SEMI',          r';'),
    ('COMMA',         r','),
    ('AT',            r'@'),
    ('EXCLAMATION',   r'!'),
    ('NEWLINE',       r'\n'),
    ('SKIP',          r'[ \t\r]+'),
    ('MISMATCH',      r'.'),
]

class Token:
    def __init__(self, type_, value, line, column):
        self.type = type_
        self.value = value
        self.line = line
        self.column = column
    
    def __repr__(self):
        return f"Token({self.type}, {repr(self.value)}, line={self.line}, col={self.column})"

def tokenize(code):
    tok_regex = '|'.join(f'(?P<{name}>{pattern})' for name, pattern in TOKEN_SPEC)
    line_num = 1
    line_start = 0
    tokens = []
    
    for mo in re.finditer(tok_regex, code):
        kind = mo.lastgroup
        value = mo.group(kind)
        column = mo.start() - line_start
        
        if kind == 'NEWLINE':
            line_num += 1
            line_start = mo.end()
        elif kind == 'SKIP' or kind == 'COMMENT_SINGLE' or kind == 'COMMENT_MULTI':
            pass
        elif kind == 'MISMATCH':
            raise SyntaxError(f"Unexpected character {repr(value)} at line {line_num}, col {column}")
        else:
            tokens.append(Token(kind, value, line_num, column))
            
    return tokens

# ==============================================================================
# AST Nodes
# ==============================================================================

class ASTNode:
    def to_verilog(self):
        raise NotImplementedError()

class ModuleNode(ASTNode):
    def __init__(self, name, ports, items):
        self.name = name
        self.ports = ports  # List of strings or Port objects
        self.items = items  # List of declaration / statement nodes
        
    def to_verilog(self):
        port_str = ", ".join(self.ports)
        items_lines = []
        for item in self.items:
            item_code = item.to_verilog()
            indented_item = "\n".join("  " + line for line in item_code.split("\n"))
            items_lines.append(indented_item)
        items_str = "\n".join(items_lines)
        return f"module {self.name} ({port_str});\n{items_str}\nendmodule"

class DeclNode(ASTNode):
    def __init__(self, type_, decl_list, width=None):
        self.type = type_  # 'input', 'output', 'wire', 'reg', 'parameter'
        self.decl_list = decl_list  # List of tuples (name, init_val)
        self.width = width # e.g. '[7:0]' or None
        
    def to_verilog(self):
        width_str = f" {self.width}" if self.width else ""
        items = []
        for name, init in self.decl_list:
            if init:
                init_val = init.to_verilog() if hasattr(init, 'to_verilog') else str(init)
                items.append(f"{name} = {init_val}")
            else:
                items.append(name)
        return f"{self.type}{width_str} {', '.join(items)};"

class AssignNode(ASTNode):
    def __init__(self, lhs, rhs):
        self.lhs = lhs     # ASTNode or string
        self.rhs = rhs     # ASTNode representing the expression
        
    def to_verilog(self):
        return f"assign {self.lhs.to_verilog()} = {self.rhs.to_verilog()};"

class AlwaysNode(ASTNode):
    def __init__(self, sensitivity, statement):
        self.sensitivity = sensitivity # list of strings or sensitivity expressions
        self.statement = statement     # Statement ASTNode (Block, If, Case, etc.)
        
    def to_verilog(self):
        sens_str = " or ".join(self.sensitivity)
        return f"always @({sens_str}) {self.statement.to_verilog()}"

class BlockNode(ASTNode):
    def __init__(self, statements):
        self.statements = statements
        
    def to_verilog(self):
        if not self.statements:
            return "begin end"
        inner = "\n".join(f"  {s.to_verilog()}" for s in self.statements)
        # Indent inner lines
        indented_inner = "\n".join("  " + line for line in inner.split("\n"))
        return f"begin\n{indented_inner}\nend"

class StmtAssignNode(ASTNode):
    def __init__(self, lhs, rhs, is_nonblocking=False):
        self.lhs = lhs
        self.rhs = rhs
        self.is_nonblocking = is_nonblocking
        
    def to_verilog(self):
        op = "<=" if self.is_nonblocking else "="
        return f"{self.lhs.to_verilog()} {op} {self.rhs.to_verilog()};"

class IfNode(ASTNode):
    def __init__(self, cond, true_stmt, false_stmt=None):
        self.cond = cond
        self.true_stmt = true_stmt
        self.false_stmt = false_stmt
        
    def to_verilog(self):
        cond_str = self.cond.to_verilog()
        # Helper to format statements correctly in blocks
        def format_branch(stmt):
            return stmt.to_verilog()
            
        true_str = format_branch(self.true_stmt)
        res = f"if ({cond_str}) {true_str}"
        if self.false_stmt:
            false_str = format_branch(self.false_stmt)
            res += f" else {false_str}"
        return res

class CaseNode(ASTNode):
    def __init__(self, expr, cases, default_stmt=None):
        self.expr = expr
        self.cases = cases          # list of (cond_expr_list, stmt)
        self.default_stmt = default_stmt
        
    def to_verilog(self):
        expr_str = self.expr.to_verilog()
        case_lines = []
        for conds, stmt in self.cases:
            conds_str = ", ".join(c.to_verilog() for c in conds)
            stmt_str = stmt.to_verilog()
            if isinstance(stmt, BlockNode):
                lines = stmt_str.split("\n")
                first_line = lines[0]
                other_lines = "\n".join("    " + line for line in lines[1:])
                case_lines.append(f"    {conds_str}: {first_line}\n{other_lines}")
            else:
                indented_stmt = "\n".join("      " + line for line in stmt_str.split("\n"))
                case_lines.append(f"    {conds_str}:\n{indented_stmt}")
        if self.default_stmt:
            stmt_str = self.default_stmt.to_verilog()
            if isinstance(self.default_stmt, BlockNode):
                lines = stmt_str.split("\n")
                first_line = lines[0]
                other_lines = "\n".join("    " + line for line in lines[1:])
                case_lines.append(f"    default: {first_line}\n{other_lines}")
            else:
                indented_stmt = "\n".join("      " + line for line in stmt_str.split("\n"))
                case_lines.append(f"    default:\n{indented_stmt}")
        cases_str = "\n".join(case_lines)
        return f"case ({expr_str})\n{cases_str}\nendcase"

# --- Expression Nodes ---

class ExpNode(ASTNode):
    pass

class IdentifierNode(ExpNode):
    def __init__(self, name):
        self.name = name
    def to_verilog(self):
        return self.name

class PartSelectNode(ExpNode):
    def __init__(self, name, msb, lsb=None):
        self.name = name
        self.msb = msb
        self.lsb = lsb
    def to_verilog(self):
        if self.lsb is not None:
            return f"{self.name}[{self.msb.to_verilog()}:{self.lsb.to_verilog()}]"
        return f"{self.name}[{self.msb.to_verilog()}]"

class ConstantNode(ExpNode):
    def __init__(self, val):
        self.val = val
    def to_verilog(self):
        return self.val

class BinaryOpNode(ExpNode):
    def __init__(self, left, op, right):
        self.left = left
        self.op = op
        self.right = right
    def to_verilog(self):
        # We can add selective parens if needed for precedence, default to adding them for clarity
        return f"({self.left.to_verilog()} {self.op} {self.right.to_verilog()})"

class UnaryOpNode(ExpNode):
    def __init__(self, op, val):
        self.op = op
        self.val = val
    def to_verilog(self):
        return f"{self.op}{self.val.to_verilog()}"

class TernaryNode(ExpNode):
    def __init__(self, cond, true_val, false_val):
        self.cond = cond
        self.true_val = true_val
        self.false_val = false_val
    def to_verilog(self):
        return f"({self.cond.to_verilog()} ? {self.true_val.to_verilog()} : {self.false_val.to_verilog()})"

# ==============================================================================
# Parser
# ==============================================================================

class VerilogParser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
    
    def peek(self, offset=0):
        if self.pos + offset < len(self.tokens):
            return self.tokens[self.pos + offset]
        return None
    
    def consume(self, expected_type=None, expected_val=None):
        tok = self.peek()
        if not tok:
            raise SyntaxError(f"Unexpected end of tokens, expected type={expected_type}, val={expected_val}")
        if expected_type and tok.type != expected_type:
            raise SyntaxError(f"Expected token type {expected_type}, got {tok.type} '{tok.value}' at line {tok.line}")
        if expected_val and tok.value != expected_val:
            raise SyntaxError(f"Expected token value {expected_val}, got '{tok.value}' at line {tok.line}")
        self.pos += 1
        return tok

    def parse_module(self):
        self.consume('KEYWORD', 'module')
        name_tok = self.consume('IDENTIFIER')
        ports = []
        if self.peek() and self.peek().type == 'LPAREN':
            self.consume('LPAREN')
            while self.peek() and self.peek().type != 'RPAREN':
                tok = self.consume('IDENTIFIER')
                ports.append(tok.value)
                if self.peek() and self.peek().type == 'COMMA':
                    self.consume('COMMA')
            self.consume('RPAREN')
        self.consume('SEMI')
        
        items = []
        while self.peek() and not (self.peek().type == 'KEYWORD' and self.peek().value == 'endmodule'):
            tok = self.peek()
            if tok.type == 'KEYWORD':
                if tok.value in ('input', 'output', 'wire', 'reg', 'parameter', 'localparam', 'inout'):
                    items.append(self.parse_declaration())
                elif tok.value == 'assign':
                    items.append(self.parse_assign())
                elif tok.value == 'always':
                    items.append(self.parse_always())
                else:
                    # Skip or throw
                    raise SyntaxError(f"Unhandled module-level keyword '{tok.value}' at line {tok.line}")
            else:
                raise SyntaxError(f"Unexpected token in module item: {tok}")
                
        self.consume('KEYWORD', 'endmodule')
        return ModuleNode(name_tok.value, ports, items)

    def parse_declaration(self):
        types = []
        while self.peek() and self.peek().type == 'KEYWORD' and self.peek().value in ('input', 'output', 'inout', 'wire', 'reg', 'parameter', 'localparam'):
            types.append(self.consume().value)
        type_str = " ".join(types)
        
        width = None
        if self.peek() and self.peek().type == 'LBRACKET':
            self.consume('LBRACKET')
            width_tokens = []
            while self.peek() and self.peek().type != 'RBRACKET':
                width_tokens.append(self.consume().value)
            self.consume('RBRACKET')
            width = "[" + "".join(width_tokens) + "]"
        
        decl_list = []
        while True:
            name_tok = self.consume('IDENTIFIER')
            init = None
            if self.peek() and self.peek().type == 'OP_ASSIGN' and self.peek().value == '=':
                self.consume('OP_ASSIGN', '=')
                init = self.parse_expression()
            decl_list.append((name_tok.value, init))
            
            if self.peek() and self.peek().type == 'COMMA':
                self.consume('COMMA')
            else:
                break
                
        self.consume('SEMI')
        return DeclNode(type_str, decl_list, width)

    def parse_assign(self):
        self.consume('KEYWORD', 'assign')
        lhs = self.parse_primary() # Can be identifier or part-select
        self.consume('OP_ASSIGN', '=')
        rhs = self.parse_expression()
        self.consume('SEMI')
        return AssignNode(lhs, rhs)

    def parse_always(self):
        self.consume('KEYWORD', 'always')
        self.consume('AT')
        self.consume('LPAREN')
        sensitivity = []
        sens_tokens = []
        while self.peek() and self.peek().type != 'RPAREN':
            tok = self.consume()
            if tok.value in ('or', ','):
                if sens_tokens:
                    sensitivity.append(" ".join(sens_tokens))
                    sens_tokens = []
            else:
                sens_tokens.append(tok.value)
        if sens_tokens:
            sensitivity.append(" ".join(sens_tokens))
        self.consume('RPAREN')
        
        stmt = self.parse_statement()
        return AlwaysNode(sensitivity, stmt)

    def parse_statement(self):
        tok = self.peek()
        if not tok:
            raise SyntaxError("Expected statement, got EOF")
            
        if tok.type == 'KEYWORD':
            if tok.value == 'begin':
                self.consume('KEYWORD', 'begin')
                stmts = []
                while self.peek() and not (self.peek().type == 'KEYWORD' and self.peek().value == 'end'):
                    stmts.append(self.parse_statement())
                self.consume('KEYWORD', 'end')
                return BlockNode(stmts)
                
            elif tok.value == 'if':
                self.consume('KEYWORD', 'if')
                self.consume('LPAREN')
                cond = self.parse_expression()
                self.consume('RPAREN')
                true_stmt = self.parse_statement()
                false_stmt = None
                if self.peek() and self.peek().type == 'KEYWORD' and self.peek().value == 'else':
                    self.consume('KEYWORD', 'else')
                    false_stmt = self.parse_statement()
                return IfNode(cond, true_stmt, false_stmt)
                
            elif tok.value == 'case':
                self.consume('KEYWORD', 'case')
                self.consume('LPAREN')
                expr = self.parse_expression()
                self.consume('RPAREN')
                cases = []
                default_stmt = None
                while self.peek() and not (self.peek().type == 'KEYWORD' and self.peek().value == 'endcase'):
                    ctok = self.peek()
                    if ctok.type == 'KEYWORD' and ctok.value == 'default':
                        self.consume('KEYWORD', 'default')
                        self.consume('OP_COLON')
                        default_stmt = self.parse_statement()
                    else:
                        conds = []
                        while True:
                            conds.append(self.parse_expression())
                            if self.peek() and self.peek().type == 'COMMA':
                                self.consume('COMMA')
                            else:
                                break
                        self.consume('OP_COLON')
                        stmt = self.parse_statement()
                        cases.append((conds, stmt))
                self.consume('KEYWORD', 'endcase')
                return CaseNode(expr, cases, default_stmt)
        
        # Fallback to assignment inside always block
        lhs = self.parse_primary()
        op_tok = self.consume()
        if op_tok.type not in ('OP_ASSIGN', 'OP_ASSIGN_NB'):
            raise SyntaxError(f"Expected assignment operator, got {op_tok} at line {op_tok.line}")
        rhs = self.parse_expression()
        self.consume('SEMI')
        return StmtAssignNode(lhs, rhs, is_nonblocking=(op_tok.type == 'OP_ASSIGN_NB'))

    # --- Expression Parsing with Precedence ---

    def parse_expression(self):
        return self.parse_ternary()

    def parse_ternary(self):
        expr = self.parse_logical_or()
        if self.peek() and self.peek().type == 'OP_TERNARY':
            self.consume('OP_TERNARY')
            true_val = self.parse_expression()
            self.consume('OP_COLON')
            false_val = self.parse_expression()
            return TernaryNode(expr, true_val, false_val)
        return expr

    def parse_logical_or(self):
        expr = self.parse_logical_and()
        while self.peek() and self.peek().type == 'OP_LOGIC' and self.peek().value == '||':
            op = self.consume().value
            right = self.parse_logical_and()
            expr = BinaryOpNode(expr, op, right)
        return expr

    def parse_logical_and(self):
        expr = self.parse_comp()
        while self.peek() and self.peek().type == 'OP_LOGIC' and self.peek().value == '&&':
            op = self.consume().value
            right = self.parse_comp()
            expr = BinaryOpNode(expr, op, right)
        return expr

    def parse_comp(self):
        expr = self.parse_bitwise()
        while self.peek() and (self.peek().type == 'OP_COMP' or (self.peek().type == 'OP_ASSIGN_NB' and self.peek().value == '<=')):
            op = self.consume().value
            right = self.parse_bitwise()
            expr = BinaryOpNode(expr, op, right)
        return expr

    def parse_bitwise(self):
        expr = self.parse_arith()
        while self.peek() and self.peek().type == 'OP_BITWISE':
            op = self.consume().value
            right = self.parse_arith()
            expr = BinaryOpNode(expr, op, right)
        return expr

    def parse_arith(self):
        expr = self.parse_term()
        while self.peek() and self.peek().type == 'OP_ARITH' and self.peek().value in ('+', '-'):
            op = self.consume().value
            right = self.parse_term()
            expr = BinaryOpNode(expr, op, right)
        return expr

    def parse_term(self):
        expr = self.parse_factor()
        while self.peek() and self.peek().type == 'OP_ARITH' and self.peek().value in ('*', '/', '%'):
            op = self.consume().value
            right = self.parse_factor()
            expr = BinaryOpNode(expr, op, right)
        return expr

    def parse_factor(self):
        tok = self.peek()
        if tok and tok.type in ('EXCLAMATION', 'OP_BITWISE') and tok.value in ('!', '~'):
            op = self.consume().value
            val = self.parse_factor()
            return UnaryOpNode(op, val)
        return self.parse_primary()

    def parse_primary(self):
        tok = self.peek()
        if not tok:
            raise SyntaxError("Expected expression, got EOF")
            
        if tok.type == 'LPAREN':
            self.consume('LPAREN')
            expr = self.parse_expression()
            self.consume('RPAREN')
            return expr
            
        if tok.type in ('NUMBER', 'CONST_HEX', 'CONST_BIN', 'CONST_DEC_SIZED'):
            self.consume()
            return ConstantNode(tok.value)
            
        if tok.type == 'IDENTIFIER':
            self.consume()
            # Check for part select: name[5:0] or name[3]
            if self.peek() and self.peek().type == 'LBRACKET':
                self.consume('LBRACKET')
                msb = self.parse_expression()
                lsb = None
                if self.peek() and self.peek().type == 'OP_COLON':
                    self.consume('OP_COLON')
                    lsb = self.parse_expression()
                self.consume('RBRACKET')
                return PartSelectNode(tok.value, msb, lsb)
            return IdentifierNode(tok.value)
            
        raise SyntaxError(f"Unexpected token in expression: {tok}")

def parse_verilog(code):
    tokens = tokenize(code)
    parser = VerilogParser(tokens)
    return parser.parse_module()
