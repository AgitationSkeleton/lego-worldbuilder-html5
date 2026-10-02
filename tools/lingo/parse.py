"""A parser for Lingo as ProjectorRays writes it out (dot syntax, one statement a line).

It accepts the forms ProjectorRays' decompiler can produce (its ast.cpp is the
reference), and gives back a tree of plain tuples:

    expressions   ('int', n) ('float', x) ('str', s) ('sym', name) ('void',) ('const', name)
                  ('list', [e]) ('plist', [(k, v)]) ('var', name) ('the', prop)
                  ('theof', prop, e) ('count', chunk, e) ('last', chunk, e)
                  ('chunk', type, first, last, e) ('member', kind, e, castlib|None)
                  ('call', name, [args]) ('mcall', obj, name, [args]) ('prop', obj, name)
                  ('index', obj, e) ('pindex', obj, name, e, e2|None)
                  ('neg', e) ('not', e) ('bin', op, a, b)
                  ('intersects', a, b) ('within', a, b)
    statements    ('assign', target, e) ('put', e) ('putinto', mode, e, target)
                  ('delete', chunk) ('call', ...) ('mcall', ...) ('return', e|None)
                  ('exit',) ('exitrepeat',) ('nextrepeat',) ('if', cond, then, else)
                  ('while', cond, body) ('repeatto', var, start, end, up, body)
                  ('repeatin', var, list, body) ('case', e, [(values, body)], otherwise)
                  ('global', [names]) ('sound', cmd, [args]) ('play', [args]) ('hilite', chunk)
"""

import re

TOKEN = re.compile(r'''
    (?P<ws>[ \t]+)
  | (?P<comment>--.*)
  | (?P<str>"[^"\r\n]*")
  | (?P<num>\d+\.(?!\.)\d*(?:[eE][+-]?\d+)?|\d+(?:[eE][+-]?\d+)?)
  | (?P<sym>\#[A-Za-z_][A-Za-z0-9_]*)
  | (?P<id>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>&&|<=|>=|<>|\.\.|[-+*/&<>=()\[\],:.])
''', re.X)

CHUNKS = ('char', 'word', 'item', 'line')
CONSTS = {'void': ('void',), 'empty': ('str', ''), 'return': ('str', '\r'), 'tab': ('str', '\t'),
          'quote': ('str', '"'), 'enter': ('str', '\x03'), 'backspace': ('str', '\x08'),
          'space': ('str', ' '), 'pi': ('const', 'pi'), 'true': ('int', 1), 'false': ('int', 0)}


class ParseError(Exception):
    pass


def tokenize(line):
    out = []
    pos = 0
    while pos < len(line):
        m = TOKEN.match(line, pos)
        if not m:
            raise ParseError('bad character %r in %r' % (line[pos], line))
        pos = m.end()
        kind = m.lastgroup
        if kind in ('ws', 'comment'):
            continue
        out.append((kind, m.group()))
    return out


class Expr:
    """Expression parser over one line's tokens."""

    def __init__(self, toks, line):
        self.t = toks
        self.p = 0
        self.line = line

    def peek(self, k=0):
        i = self.p + k
        return self.t[i] if i < len(self.t) else (None, None)

    def at(self, val, k=0):
        kind, v = self.peek(k)
        if kind == 'id':
            return v.lower() == val
        return v == val

    def take(self, val=None):
        tok = self.peek()
        if tok[0] is None:
            raise ParseError('unexpected end of line: %s' % self.line)
        if val is not None and not self.at(val):
            raise ParseError('expected %r, got %r in: %s' % (val, tok[1], self.line))
        self.p += 1
        return tok

    def done(self):
        return self.p >= len(self.t)

    # precedence: or < and < comparison < concat < additive < multiplicative < unary < postfix
    def expr(self):
        return self.or_()

    def or_(self):
        a = self.and_()
        while self.at('or'):
            self.take()
            a = ('bin', 'or', a, self.and_())
        return a

    def and_(self):
        a = self.cmp()
        while self.at('and'):
            self.take()
            a = ('bin', 'and', a, self.cmp())
        return a

    def cmp(self):
        a = self.concat()
        while True:
            k, v = self.peek()
            if k == 'op' and v in ('=', '<>', '<', '<=', '>', '>='):
                self.take()
                a = ('bin', v, a, self.concat())
            elif self.at('contains') or self.at('starts'):
                op = self.take()[1].lower()
                a = ('bin', op, a, self.concat())
            else:
                return a

    def concat(self):
        a = self.add()
        while True:
            k, v = self.peek()
            if k == 'op' and v in ('&', '&&'):
                self.take()
                a = ('bin', v, a, self.add())
            else:
                return a

    def add(self):
        a = self.mul()
        while True:
            k, v = self.peek()
            if k == 'op' and v in ('+', '-'):
                self.take()
                a = ('bin', v, a, self.mul())
            else:
                return a

    def mul(self):
        a = self.unary()
        while True:
            k, v = self.peek()
            if k == 'op' and v in ('*', '/'):
                self.take()
                a = ('bin', v, a, self.unary())
            elif self.at('mod'):
                self.take()
                a = ('bin', 'mod', a, self.unary())
            else:
                return a

    def unary(self):
        k, v = self.peek()
        if k == 'op' and v == '-':
            self.take()
            e = self.unary()
            if e[0] == 'int':
                return ('int', -e[1])
            if e[0] == 'float':
                return ('float', -e[1])
            return ('neg', e)
        if self.at('not'):
            self.take()
            return ('not', self.unary())
        return self.postfix(self.primary())

    def args(self, close=')'):
        out = []
        if self.at(close):
            self.take()
            return out
        while True:
            out.append(self.expr())
            if self.at(','):
                self.take()
                continue
            self.take(close)
            return out

    def postfix(self, e):
        while True:
            if self.at('.'):
                self.take()
                k, name = self.take()
                if k != 'id':
                    raise ParseError('expected a name after "." in: %s' % self.line)
                if self.at('('):
                    self.take()
                    e = ('mcall', e, name, self.args())
                elif self.at('['):
                    self.take()
                    i1 = self.expr()
                    i2 = None
                    if self.at('..'):
                        self.take()
                        i2 = self.expr()
                    self.take(']')
                    e = ('pindex', e, name, i1, i2)
                else:
                    e = ('prop', e, name)
            elif self.at('['):
                self.take()
                i = self.expr()
                self.take(']')
                e = ('index', e, i)
            else:
                return e

    def simple(self):
        """An operand written without parentheses after a keyword: no binary operators."""
        return self.unary()

    def primary(self):
        k, v = self.peek()
        if k == 'num':
            self.take()
            if re.fullmatch(r'\d+', v):
                return ('int', int(v))
            return ('float', float(v))
        if k == 'str':
            self.take()
            return ('str', v[1:-1])
        if k == 'sym':
            self.take()
            return ('sym', v[1:])
        if k == 'op' and v == '(':
            self.take()
            e = self.expr()
            self.take(')')
            return e
        if k == 'op' and v == '[':
            self.take()
            return self.list_literal()
        if k != 'id':
            raise ParseError('unexpected %r in: %s' % (v, self.line))
        lv = v.lower()
        if lv == 'the':
            return self.the()
        if lv in CHUNKS and not self.at('(', 1) and not self.at('.', 1) and not self.at('=', 1) \
                and self.peek(1)[0] is not None and not (self.peek(1)[0] == 'op' and self.peek(1)[1] in (')', ',', ']')):
            return self.chunk()
        if lv in ('member', 'cast', 'script', 'castlib', 'window') and not self.at('(', 1) \
                and self.peek(1)[0] is not None and not (self.peek(1)[0] == 'op'
                                                         and self.peek(1)[1] in (')', ',', ']', '.', '=')):
            self.take()
            e = self.simple()
            cl = None
            if self.at('of') and self.at('castlib', 1):
                self.take()
                self.take()
                cl = self.simple()
            return ('member', lv, e, cl)
        if lv == 'sprite' and not self.at('(', 1) and self.peek(1)[0] is not None:
            self.take()
            a = self.simple()
            if self.at('intersects'):
                self.take()
                return ('intersects', a, self.simple())
            if self.at('within'):
                self.take()
                return ('within', a, self.simple())
            raise ParseError('sprite expression: %s' % self.line)
        if lv in CONSTS and not self.at('(', 1):
            self.take()
            return CONSTS[lv]
        self.take()
        if self.at('('):
            self.take()
            return ('call', v, self.args())
        return ('var', v)

    def list_literal(self):
        if self.at(':') and self.at(']', 1):
            self.take()
            self.take()
            return ('plist', [])
        if self.at(']'):
            self.take()
            return ('list', [])
        first = self.expr()
        if self.at(':'):
            self.take()
            items = [(first, self.expr())]
            while self.at(','):
                self.take()
                k = self.expr()
                self.take(':')
                items.append((k, self.expr()))
            self.take(']')
            return ('plist', items)
        items = [first]
        while self.at(','):
            self.take()
            items.append(self.expr())
        self.take(']')
        return ('list', items)

    def chunk(self):
        ctype = self.take()[1].lower()
        first = self.simple()
        last = None
        if self.at('to'):
            self.take()
            last = self.simple()
        self.take('of')
        # The string is verbose: it may itself be a bigger chunk, or "the text of member x".
        s = self.simple()
        return ('chunk', ctype, first, last, s)

    def the(self):
        self.take('the')
        k, v = self.take()
        lv = v.lower()
        if lv == 'number' and self.at('of'):
            self.take()
            k2, what = self.take()
            what_l = what.lower()
            if what_l.rstrip('s') in CHUNKS and self.at('in'):
                self.take()
                return ('count', what_l.rstrip('s'), self.simple())
            if self.at('of'):
                self.take()
                return ('theof', 'number of ' + what_l, self.simple())
            return ('the', 'number of ' + what_l)
        if lv == 'last' and self.peek()[1] and self.peek()[1].lower() in CHUNKS:
            ctype = self.take()[1].lower()
            self.take('in')
            return ('last', ctype, self.simple())
        if self.at('of') and self.peek(1)[0] is not None:
            self.take()
            obj = self.simple()
            return ('theof', v, obj)
        return ('the', v)


class Parser:
    def __init__(self, text, name=''):
        self.name = name
        self.lines = []
        for raw in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
            toks = tokenize(raw)
            if toks:
                self.lines.append((raw.strip(), toks))
        self.i = 0

    def script(self):
        props, globals_, handlers = [], [], []
        while self.i < len(self.lines):
            raw, toks = self.lines[self.i]
            head = toks[0][1].lower()
            if head == 'property':
                props += [v for k, v in toks[1:] if k == 'id']
                self.i += 1
            elif head == 'global':
                globals_ += [v for k, v in toks[1:] if k == 'id']
                self.i += 1
            elif head in ('on', 'method'):
                handlers.append(self.handler())
            else:
                raise ParseError('%s: unexpected line outside a handler: %s' % (self.name, raw))
        return dict(props=props, globals=globals_, handlers=handlers)

    def handler(self):
        raw, toks = self.lines[self.i]
        self.i += 1
        name = toks[1][1]
        params = [v for k, v in toks[2:] if k == 'id']
        body = self.block(('end',))
        self.i += 1  # end
        return dict(name=name, params=params, body=body)

    def block(self, enders):
        out = []
        while self.i < len(self.lines):
            raw, toks = self.lines[self.i]
            h = toks[0][1].lower() if toks[0][0] == 'id' else None
            if h in enders and self.ends(toks, enders):
                return out
            out.append(self.statement())
        raise ParseError('%s: block not closed (%s)' % (self.name, enders))

    def ends(self, toks, enders):
        h = toks[0][1].lower()
        if h == 'end':
            return True
        if h == 'else':
            return 'else' in enders
        if h == 'otherwise':
            return 'otherwise' in enders
        return False

    def statement(self):
        raw, toks = self.lines[self.i]
        e = Expr(toks, raw)
        h = toks[0][1].lower() if toks[0][0] == 'id' else None
        if h == 'if' and toks[-1][1].lower() == 'then':
            self.i += 1
            e.take()
            cond = e.expr()
            e.take('then')
            then = self.block(('else', 'end'))
            raw2, toks2 = self.lines[self.i]
            other = []
            if toks2[0][1].lower() == 'else':
                self.i += 1
                other = self.block(('end',))
            self.i += 1  # end if
            return ('if', cond, then, other)
        if h == 'repeat':
            self.i += 1
            e.take()
            if e.at('while'):
                e.take()
                cond = e.expr()
                body = self.block(('end',))
                self.i += 1
                return ('while', cond, body)
            e.take('with')
            var = e.take()[1]
            if e.at('in'):
                e.take()
                lst = e.expr()
                body = self.block(('end',))
                self.i += 1
                return ('repeatin', var, lst, body)
            e.take('=')
            start = e.expr()
            up = True
            if e.at('down'):
                e.take()
                up = False
            e.take('to')
            end = e.expr()
            body = self.block(('end',))
            self.i += 1
            return ('repeatto', var, start, end, up, body)
        if h == 'case' and toks[-1][1].lower() == 'of':
            self.i += 1
            e.take()
            val = e.expr()
            e.take('of')
            labels = []
            otherwise = None
            while True:
                raw2, toks2 = self.lines[self.i]
                hh = toks2[0][1].lower()
                if hh == 'end':
                    self.i += 1
                    break
                if hh == 'otherwise':
                    self.i += 1
                    otherwise = self.block(('end',))
                    continue
                le = Expr(toks2, raw2)
                values = [le.expr()]
                while le.at(','):
                    le.take()
                    values.append(le.expr())
                le.take(':')
                self.i += 1
                body = self.case_block()
                labels.append((values, body))
            return ('case', val, labels, otherwise)
        self.i += 1
        st = self.simple_statement(e, h)
        if not e.done():
            raise ParseError('%s: trailing tokens in: %s' % (self.name, raw))
        return st

    def case_block(self):
        """Statements under a case label run until the next label, otherwise or end case.
        A label line is an expression list followed by a colon at the end of the line."""
        out = []
        while True:
            raw, toks = self.lines[self.i]
            hh = toks[0][1].lower() if toks[0][0] == 'id' else None
            if hh in ('end', 'otherwise') and (hh == 'otherwise' or len(toks) == 2):
                if hh == 'otherwise' or toks[1][1].lower() == 'case':
                    return out
            if toks[-1] == ('op', ':') and self.is_label(toks):
                return out
            out.append(self.statement())

    def is_label(self, toks):
        try:
            le = Expr(toks, '')
            le.expr()
            while le.at(','):
                le.take()
                le.expr()
            return le.at(':') and le.p == len(toks) - 1
        except ParseError:
            return False

    def simple_statement(self, e, h):
        if h == 'global':
            e.take()
            names = [e.take()[1]]
            while e.at(','):
                e.take()
                names.append(e.take()[1])
            return ('global', names)
        if h == 'exit':
            e.take()
            if e.at('repeat'):
                e.take()
                return ('exitrepeat',)
            return ('exit',)
        if h == 'next' and e.at('repeat', 1):
            e.take()
            e.take()
            return ('nextrepeat',)
        if h == 'return':
            e.take()
            if e.done():
                return ('return', None)
            return ('return', e.expr())
        if h == 'put' and not e.at('(', 1):
            e.take()
            v = e.expr()
            if e.done():
                return ('put', v)
            mode = e.take()[1].lower()
            target = e.expr()
            return ('putinto', mode, v, target)
        if h == 'delete' and not e.at('(', 1):
            e.take()
            return ('delete', e.expr())
        if h == 'hilite' and not e.at('(', 1):
            e.take()
            return ('hilite', e.expr())
        if h == 'set' and not e.at('(', 1) and not e.at('=', 1):
            e.take()
            target = e.expr_until_to()
            e.take('to')
            return ('assign', target, e.expr())
        if h == 'sound' and e.peek(1)[0] == 'id' and not e.at('(', 1):
            e.take()
            cmd = e.take()[1]
            args = []
            if not e.done():
                args.append(e.expr())
                while e.at(','):
                    e.take()
                    args.append(e.expr())
            return ('sound', cmd, args)
        if h == 'play' and not e.at('(', 1):
            e.take()
            rest = []
            while not e.done():
                rest.append(e.take())
            return ('play', rest)
        lhs = e.unary()
        if e.at('='):
            e.take()
            return ('assign', lhs, e.expr())
        if lhs[0] in ('call', 'mcall'):
            return lhs
        if lhs[0] == 'var':
            # a command written without parentheses or arguments: "nothing", "updateStage"
            return ('call', lhs[1], [])
        raise ParseError('%s: not a statement: %s' % (self.name, e.line))


def _expr_until_to(self):
    # "set <target> to <value>": the target is an expression that stops at "to".
    start = self.p
    depth = 0
    for j in range(self.p, len(self.t)):
        k, v = self.t[j]
        if v in ('(', '['):
            depth += 1
        elif v in (')', ']'):
            depth -= 1
        elif depth == 0 and k == 'id' and v.lower() == 'to':
            sub = Expr(self.t[start:j], self.line)
            target = sub.expr()
            self.p = j
            return target
    raise ParseError('set without to: %s' % self.line)


Expr.expr_until_to = _expr_until_to


def parse(text, name=''):
    return Parser(text, name).script()
