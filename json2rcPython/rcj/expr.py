"""ExpressionParser — infix→RPN compiler, byte-identical port of the Java ExpressionParser.

Compiles an expression string ("windowWidth / 2", "50 + sin(time) * 10") into a FloatExpression
op (ANIMATED_FLOAT, opcode 81) and returns the result as a NaN-encoded id (carried as raw int32
BITS, never as a Python float — NaN payloads must not be canonicalized).

RPN float array element encodings (AnimatedFloatExpression):
  - number literal  -> float32 raw bits
  - variable        -> asNan(varId)              (system or user)
  - operator        -> asNan(OFFSET + opId)
  - function        -> asNan(OFFSET + funcId)
asNan(v) bits = v | 0xFF800000.  OFFSET = 0x310000.
"""

from __future__ import annotations

OFFSET = 0x310000


def as_nan_bits(v: int) -> int:
    """Raw int32 bits of Utils.asNan(v) = intBitsToFloat(v | 0xFF800000)."""
    return (v | 0xFF800000) & 0xFFFFFFFF


def float_to_raw_int_bits(f: float) -> int:
    import struct
    return struct.unpack(">I", struct.pack(">f", f))[0]


OPERATORS = {"+": 1, "-": 2, "*": 3, "/": 4, "%": 5, "u-": 73}
PRECEDENCE = {"+": 1, "-": 1, "*": 2, "/": 2, "%": 2, "u-": 3}
RAND_SEED_OP = 40      # AnimatedFloatExpression.OFFSET + 40

FUNCTIONS = {
    # No opcode: RAND_SEED is emitted positionally, see the parser.
    "seed": None,
    "seed_2arg": None,
    "sin": 18, "cos": 19, "tan": 20, "asin": 21, "acos": 22, "atan": 23, "atan2": 24,
    "sqrt": 9, "abs": 10, "pow": 8, "min": 6, "max": 7, "floor": 14, "ceil": 31,
    "log": 15, "ln": 16, "sign": 11, "round": 17, "lerp": 49, "step": 44,
    "smooth_step": 50, "clamp": 27, "ifElse": 26, "mad": 25, "ping_pong": 54,
    "fract": 53, "exp": 13, "hypot": 47, "square": 45, "rand": 39,
    "arrayMin": 34, "arrayMax": 33, "arrayLength": 37, "arraySum": 35,
    "arraySumSqr": 78, "arraySumXY": 77, "arrayGet": 32, "spline": 38,
    "arraySpline": 38, "splineLoop": 75, "anim": 256,
}
# System variable token -> absolute id passed to asNan (getVariableNan).
#
# Mirrors ExpressionParser's resolution switch as of androidx-main 2026-08-09, which added
# every system variable and a set of aliases for each ("improvements to json parser. Fixed
# magic number constants, add support for all the system variables"). Ids are the
# RemoteContext.ID_* constants; the aliases are the parser's, so a document that builds
# through the Java oracle also converts here rather than silently falling back to it.
SYSTEM_VARS = {
    # time
    "time": 1, "continuousSec": 1, "continuousSec()": 1,
    "seconds": 2, "timeInSec": 2, "timeInSec()": 2,
    "timeInMin": 3, "timeInMin()": 3,
    "timeInHr": 4, "timeInHr()": 4,
    "animationTime": 30, "animationTime()": 30, "animTime": 30,
    # Frame interval. Needed by anything integrating: without it a document has to keep a
    # previous-time particle variable and difference it by hand.
    "deltaTime": 31, "deltaTime()": 31, "delta_time": 31, "dt": 31,
    "animationDeltaTime": 31, "animationDeltaTime()": 31,
    "epochSecond": 32, "epochSecond()": 32,
    # calendar
    "calendarMonth": 9, "calendarMonth()": 9, "month": 9,
    "offsetToUtc": 10, "offsetToUtc()": 10, "utcOffset": 10,
    "weekDay": 11, "weekDay()": 11, "weekday": 11, "dayOfWeek": 11,
    "dayOfMonth": 12, "dayOfMonth()": 12, "day": 12,
    "dayOfYear": 34, "dayOfYear()": 34,
    "year": 35, "year()": 35,
    # geometry and environment
    "windowWidth": 5, "windowWidth()": 5, "windowHeight": 6, "windowHeight()": 6,
    "density": 27, "density()": 27,
    "apiLevel": 28, "apiLevel()": 28,
    "fontSize": 33, "fontSize()": 33,
    # touch
    "touchX": 13, "touchX()": 13, "touchPosX": 13, "touchPositionX": 13,
    "touchY": 14, "touchY()": 14, "touchPosY": 14, "touchPositionY": 14,
    "touchVelX": 15, "touchVelX()": 15, "touchVelocityX": 15,
    "touchVelY": 16, "touchVelY()": 16, "touchVelocityY": 16,
    "touchTime": 29, "touchTime()": 29, "touchEventTime": 29, "touchEventTime()": 29,
    # sensors. Naming one is all it takes to subscribe to it: FloatExpression calls
    # context.listensTo for every id it references, and the player registers a listener for
    # anything in the 17..26 range. All of them are sampled at SENSOR_DELAY_NORMAL (5 Hz)
    # and a document cannot ask for more.
    "accelX": 17, "accelX()": 17, "accelerationX": 17, "accelerationX()": 17,
    "accelY": 18, "accelY()": 18, "accelerationY": 18, "accelerationY()": 18,
    "accelZ": 19, "accelZ()": 19, "accelerationZ": 19, "accelerationZ()": 19,
    "gyroX": 20, "gyroX()": 20, "gyroRotX": 20, "gyroRotX()": 20, "gyroRotationX": 20,
    "gyroY": 21, "gyroY()": 21, "gyroRotY": 21, "gyroRotY()": 21, "gyroRotationY": 21,
    "gyroZ": 22, "gyroZ()": 22, "gyroRotZ": 22, "gyroRotZ()": 22, "gyroRotationZ": 22,
    "magneticX": 23, "magneticX()": 23,
    "magneticY": 24, "magneticY()": 24,
    "magneticZ": 25, "magneticZ()": 25,
    "light": 26, "light()": 26, "lightLevel": 26,
    # operators that read as variables
    "rand": OFFSET + 39, "rand()": OFFSET + 39,
    "a[0]": OFFSET + 70, "a[1]": OFFSET + 71, "a[2]": OFFSET + 72,
}
# Component-value variables: resolved via the writer (emit a COMPONENT_VALUE op).
COMPONENT_WIDTH_VARS = {"width", "componentWidth", "componentWidth()"}
COMPONENT_HEIGHT_VARS = {"height", "componentHeight", "componentHeight()"}
# Everything ExpressionParser recognises is now handled; kept so callers can still ask.
UNSUPPORTED_VARS: set[str] = set()


class ExpressionError(Exception):
    pass


def is_variable_ref(s: str) -> bool:
    return len(s) >= 2 and (s.startswith("$") or s.startswith("@"))


def variable_name_from_ref(s: str) -> str:
    if s.startswith("$vars.") or s.startswith("@vars."):
        return s[6:]
    return s[1:]


class ExpressionParser:
    def __init__(self, writer, variables: dict[str, int]) -> None:
        self.writer = writer
        self.variables = variables  # name -> NaN-id bits

    # ── public ───────────────────────────────────────────────────────────────

    def parse_expression(self, value) -> int:
        """Compile `value` into a FloatExpression op; return its asNan(id) bits.

        str -> plain expression; dict {"value": expr, "anim": duration} -> animated (cubic easing).
        """
        if isinstance(value, str):
            return self.writer.float_expression(self.infix_to_rpn(value))
        if isinstance(value, dict):
            ops = self.infix_to_rpn(str(value["value"]))
            duration = float(value.get("anim", 1.0))
            # anim(duration), EASING_CUBIC_STANDARD, no spec/init/wrap -> [duration] (or none if 1.0)
            anim = [duration] if duration != 1.0 else None
            return self.writer.float_expression(ops, anim)
        raise ExpressionError(f"expression value type {type(value)} not supported")

    def is_variable(self, token: str) -> bool:
        if is_variable_ref(token):
            name = variable_name_from_ref(token)
            if not name:
                return False
            return all(c.isalnum() or c in "_." for c in name)
        if token in self.variables:
            return True
        return (token in SYSTEM_VARS or token in UNSUPPORTED_VARS
                or token in COMPONENT_WIDTH_VARS or token in COMPONENT_HEIGHT_VARS)

    def variable_nan_bits(self, token: str) -> int:
        if token in SYSTEM_VARS:
            return as_nan_bits(SYSTEM_VARS[token])
        if token in COMPONENT_WIDTH_VARS:
            return self.writer.add_component_width_value()
        if token in COMPONENT_HEIGHT_VARS:
            return self.writer.add_component_height_value()
        if token in UNSUPPORTED_VARS:
            raise ExpressionError(f"system variable {token!r} (touch) not yet supported")
        if is_variable_ref(token):
            name = variable_name_from_ref(token)
            if name in self.variables:
                return self.variables[name]
            raise ExpressionError(f"Variable not found: {name}")
        if token in self.variables:
            return self.variables[token]
        raise ExpressionError(f"Unknown variable: {token}")

    # ── compiler ─────────────────────────────────────────────────────────────

    @staticmethod
    def _is_number(token: str) -> bool:
        try:
            float(token)
            return True
        except ValueError:
            return False

    def infix_to_rpn(self, expression: str, extra_functions: dict | None = None) -> list[int]:
        """Shunting-yard → list of RPN element BITS (numbers/vars/ops/funcs).

        `extra_functions` adds opcodes for this call only. It exists so a vector expression can
        use vec3/dot/cross/normalize without those names leaking into scalar expressions, where
        the scalar evaluator has no such opcodes and would fail at *runtime* rather than here.
        """
        FUNCS = FUNCTIONS if not extra_functions else {**FUNCTIONS, **extra_functions}
        output: list[int] = []
        stack: list[str] = []
        tokens = self._tokenize(expression)
        last_was_operator = True

        def emit_op(op: str) -> None:
            if op in OPERATORS:
                output.append(as_nan_bits(OFFSET + OPERATORS[op]))
            elif op in FUNCS and FUNCS[op] is not None:
                output.append(as_nan_bits(OFFSET + FUNCS[op]))

        for token in tokens:
            if self._is_number(token):
                output.append(float_to_raw_int_bits(float(token)))
                last_was_operator = False
            elif self.is_variable(token):
                output.append(self.variable_nan_bits(token))
                last_was_operator = False
            elif token in FUNCS:
                stack.append(token)
                last_was_operator = True
            elif token == ",":
                while stack and stack[-1] != "(":
                    emit_op(stack.pop())
                # seed(a, b): RAND_SEED is emitted at the comma, between its two
                # operands, and the entry is renamed so the closing paren emits nothing
                # more. seed(a) takes the one-arg path at ")" instead.
                if stack and stack[-1] == "(" and len(stack) >= 2 and stack[-2] == "seed":
                    output.append(as_nan_bits(OFFSET + RAND_SEED_OP))
                    stack[-2] = "seed_2arg"
                last_was_operator = True
            elif token in OPERATORS or token == "-":
                if token == "-" and last_was_operator:
                    stack.append("u-")
                else:
                    while stack and stack[-1] in OPERATORS:
                        p1 = PRECEDENCE.get(stack[-1], 0)
                        p2 = PRECEDENCE.get(token, 0)
                        if p1 > p2 or (p1 == p2 and token != "u-"):
                            emit_op(stack.pop())
                        else:
                            break
                    stack.append(token)
                last_was_operator = True
            elif token == "(":
                stack.append(token)
                last_was_operator = True
            elif token == ")":
                while stack and stack[-1] != "(":
                    emit_op(stack.pop())
                if not stack:
                    raise ExpressionError("Mismatched parentheses")
                stack.pop()
                if stack and stack[-1] in FUNCS:
                    fn = stack.pop()
                    if fn == "seed":
                        output.append(as_nan_bits(OFFSET + RAND_SEED_OP))
                        output.append(float_to_raw_int_bits(1.0))
                    elif fn != "seed_2arg":
                        emit_op(fn)
                last_was_operator = False
            else:
                raise ExpressionError(f"Unknown token in expression: {token}")

        while stack:
            op = stack.pop()
            if op == "seed":
                output.append(as_nan_bits(OFFSET + RAND_SEED_OP))
                output.append(float_to_raw_int_bits(1.0))
            elif op != "seed_2arg":
                emit_op(op)
        return output

    def _tokenize(self, expression: str) -> list[str]:
        tokens: list[str] = []
        sb: list[str] = []
        i = 0
        n = len(expression)
        while i < n:
            c = expression[i]
            if c.isspace():
                i += 1
                continue
            if c.isalnum() or c in "_.$@[]":
                sb.append(c)
            elif c == "(":
                if i + 1 < n and expression[i + 1] == ")":
                    sb.append("()")
                    i += 1
                else:
                    if sb:
                        tokens.append("".join(sb)); sb.clear()
                    tokens.append("(")
            else:
                if sb:
                    tokens.append("".join(sb)); sb.clear()
                tokens.append(c)
            i += 1
        if sb:
            tokens.append("".join(sb))

        # Merge a unary "-" with a following numeric literal into one negative literal.
        merged: list[str] = []
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t == "-" and i + 1 < len(tokens) and self._is_number(tokens[i + 1]):
                prev = merged[-1] if merged else None
                is_unary = (prev is None or prev == "(" or prev == ","
                            or (len(prev) == 1 and (prev in OPERATORS)))
                if is_unary:
                    merged.append("-" + tokens[i + 1])
                    i += 2
                    continue
            merged.append(t)
            i += 1
        return merged
