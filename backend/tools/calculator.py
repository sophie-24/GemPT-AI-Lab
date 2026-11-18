"""A deliberately small, bounded arithmetic expression evaluator."""

import ast
import math
import operator


MAX_EXPRESSION_LENGTH = 128
MAX_AST_NODES = 64
MAX_ABS_VALUE = 1e100
MAX_EXPONENT = 100

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class CalculatorError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _bounded(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CalculatorError("invalid_number", "Only real numbers are supported.")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or abs(value) > MAX_ABS_VALUE:
        raise CalculatorError("result_out_of_range", "The result is outside the allowed range.")
    return value


def _evaluate(node):
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return _bounded(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise CalculatorError("complexity_limit", "Exponent magnitude may not exceed 100.")
        try:
            return _bounded(_BINARY[type(node.op)](left, right))
        except ZeroDivisionError:
            raise CalculatorError("division_by_zero", "Division by zero is not allowed.") from None
        except (OverflowError, ValueError):
            raise CalculatorError("result_out_of_range", "The operation is outside the allowed range.") from None
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _bounded(_UNARY[type(node.op)](_evaluate(node.operand)))
    raise CalculatorError("unsupported_syntax", "Only numeric literals and +, -, *, /, //, %, ** are supported.")


def calculate(expression: str) -> dict:
    if not isinstance(expression, str):
        return {"ok": False, "error": {"code": "invalid_argument", "message": "expression must be a string."}}
    if not expression.strip() or len(expression) > MAX_EXPRESSION_LENGTH:
        code = "empty_expression" if not expression.strip() else "complexity_limit"
        return {"ok": False, "error": {"code": code, "message": "Expression must contain 1 to 128 characters."}}
    try:
        tree = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
            raise CalculatorError("complexity_limit", "Expression is too complex.")
        value = _evaluate(tree.body)
        return {"ok": True, "result": value}
    except SyntaxError:
        error = CalculatorError("invalid_expression", "Expression could not be parsed.")
    except CalculatorError as exc:
        error = exc
    return {"ok": False, "error": {"code": error.code, "message": str(error)}}
