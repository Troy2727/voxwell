"""The tools a voice agent may use: a fixed allowlist, all read-only and free of side effects.

The model can only name one of these; nothing it writes is ever executed as code.
"""

import ast
import math
import operator
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from voxwell import voices


class ToolError(ValueError):
    """A tool could not run; `user_message` (written here, never an exception's own text) goes back
    to the model and is shown in the tool call."""

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


MAX_EXPRESSION = 200
MAX_NODES = 60
MAX_BITS = 4096  # integer results beyond this (about 1200 digits) are refused before computing them
MAX_EXPONENT = 1000

_BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _number(value) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolError("Only plain numbers are allowed.")
    return value


def _check_size(op, left, right) -> None:
    """Refuse integer operations whose result would be huge, before Python spends time on them."""
    if not (isinstance(left, int) and isinstance(right, int)):
        return
    if op is ast.Pow:
        if right > MAX_EXPONENT or (abs(left) > 1 and abs(left).bit_length() * right > MAX_BITS):
            raise ToolError("The result would be too large.")
    elif op is ast.Mult and left.bit_length() + right.bit_length() > MAX_BITS:
        raise ToolError("The result would be too large.")


def _eval(node: ast.AST) -> int | float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        return _number(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _eval(node.left), _eval(node.right)
        _check_size(type(node.op), left, right)
        try:
            result = _BINARY[type(node.op)](left, right)
        except ZeroDivisionError:
            raise ToolError("Division by zero.")
        except OverflowError:
            raise ToolError("The result would be too large.")
        if isinstance(result, complex):
            raise ToolError("The result is not a real number.")
        if isinstance(result, float) and not math.isfinite(result):
            raise ToolError("The result would be too large.")
        return result
    raise ToolError("Only numbers, + - * / // % ** and parentheses are allowed.")


def calculate(expression: str) -> str:
    """Arithmetic on numbers only, parsed with `ast` (never eval): no names, calls or attributes."""
    if not isinstance(expression, str) or not expression.strip():
        raise ToolError("Give an expression, e.g. 12 * (3 + 4).")
    if len(expression) > MAX_EXPRESSION:
        raise ToolError(f"The expression is too long ({MAX_EXPRESSION} characters max).")
    try:
        tree = ast.parse(expression.replace("^", "**"), mode="eval")
    except SyntaxError:
        raise ToolError("That is not a valid arithmetic expression.")
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise ToolError("The expression is too long.")
    result = _eval(tree)
    if isinstance(result, float) and result.is_integer() and abs(result) < 1e15:
        result = int(result)
    return str(result)


def current_time() -> str:
    return datetime.now().astimezone().strftime("%A %d %B %Y, %H:%M (%Z)")


def list_saved_voices() -> str:
    names = [v.name for v in voices.list_voices()]
    return ", ".join(names) if names else "No saved voices."


@dataclass(frozen=True)
class Tool:
    name: str
    description: str  # for the model's instructions and the UI
    arguments: str  # how to call it, shown to the model
    run: Callable[[dict], str]


def _no_arguments(fn: Callable[[], str]) -> Callable[[dict], str]:
    return lambda args: fn()


TOOLS = {
    t.name: t
    for t in (
        Tool("current_time", "The current local date and time.", "{}", _no_arguments(current_time)),
        Tool("calculator", "Exact arithmetic (+ - * / // % ** and parentheses).", '{"expression": "12 * (3 + 4)"}',
             lambda args: calculate(args.get("expression", ""))),
        Tool("list_voices", "The names of the voices saved in Voxwell.", "{}", _no_arguments(list_saved_voices)),
    )
}


def run(name: str, arguments, enabled: list[str]) -> str:
    """Run an allowlisted, enabled tool. ToolError (for the model) when the call is not allowed or fails."""
    if name not in TOOLS or name not in enabled:
        allowed = ", ".join(enabled) or "none"
        raise ToolError(f"There is no tool called '{name}'. Tools you can use: {allowed}.")
    if not isinstance(arguments, dict):
        raise ToolError("arguments must be a JSON object.")
    return TOOLS[name].run(arguments)
