# FIXME: make exceptions nicer
import untypy
import typing
import dataclasses
import inspect
import types

_DEBUG = False
def _debug(s):
    if _DEBUG:
        print('[DEBUG] ' + s)

# Types
Any = typing.Any
Optional = typing.Optional
Union = typing.Union
Iterable = typing.Iterable
Iterator = typing.Iterator
Sequence = typing.Sequence
Generator = typing.Generator
ForwardRef = typing.ForwardRef

Mapping = typing.Mapping

Callable = typing.Callable

dataclass = dataclasses.dataclass

unchecked = untypy.unchecked

intPositive = typing.Annotated[int, lambda i: i > 0, 'intPositive']
nat = typing.Annotated[int, lambda i: i >= 0, 'nat']
intNonNegative = typing.Annotated[int, lambda i: i >= 0, 'intNonNegative']
intNonPositive = typing.Annotated[int, lambda i: i <= 0, 'intNonPositive']
intNegative = typing.Annotated[int, lambda i: i < 0, 'intNegative']

floatPositive = typing.Annotated[float, lambda x: x > 0, 'floatPositive']
floatNonNegative = typing.Annotated[float, lambda x: x >= 0, 'floatNonNegative']
floatNegative = typing.Annotated[float, lambda x: x < 0, 'floatNegative']
floatNonPositive = typing.Annotated[float, lambda x: x <= 0, 'floatNonPositive']

T = typing.TypeVar('T')
U = typing.TypeVar('U')
V = typing.TypeVar('V')


class Literal(types.GenericAlias):
    """
    Behaves like typing.Literal, but allows isinstance checks.
    """
    # Note: Cannot subclass Literal
    # It is also not possible to overwrite '__instancecheck__'
    # We musst inherit from GenericAlias, or else this can not be used
    # as part of other types.

    def __class_getitem__(cls, items):
        # Multiple __class_getitem__ are given as a tuple,
        # but if there is only a single argument, it is not wrapped.
        if not isinstance(items, tuple):
            items = (items,)
        # flattening
        # cannot reuse typing.Literal for flattening,
        # as it does not recognize this type
        args_set = []
        for i in items:
            if hasattr(i, '__origin__') and hasattr(i, '__args__') and i.__origin__ in [typing.Literal]:
                for arg in i.__args__:
                    if arg not in args_set:
                        args_set.append(arg)
            elif i not in args_set:
                args_set.append(i)

        return Literal(cls, tuple(args_set))

    def __instancecheck__(self, value):
        for arg in self.__args__:
            # typing.Literal checks for type(value) == type(arg),
            # however this does not work well with untypy.
            if isinstance(value, type(arg)) and arg == value:
                return True
        return False

    def __getattribute__(self, item):
        # types.GenericAlias does some undocumented subclassing magic,
        # we cannot set '__origin__', so we use __getattribute__
        # __origin__ should be typing.Literal, so it is recognize by untypy
        if item == '__origin__':
            return typing.Literal
        else:
            return types.GenericAlias.__getattribute__(self, item)

    def __eq__(self, other):
        if hasattr(other, '__origin__') and hasattr(other, '__args__') and other.__origin__ in [typing.Literal]:
            return set(self.__args__) == set(other.__args__)
        else:
            return False

    def __hash__(self):
        return hash(frozenset(self.__args__))

def _collectDataClassAttributes(cls):
    result = dict()
    for c in cls.mro():
        if hasattr(c, '__kind') and c.__kind == 'record' and hasattr(c, '__annotations__'):
            result = c.__annotations__ | result
    return result


def _patchDataClass(cls, mutable):
    fieldNames = [f.name for f in dataclasses.fields(cls)]
    setattr(cls, EQ_ATTRS_ATTR, fieldNames)

    if hasattr(cls, '__annotations__'):
        # add annotions for type checked constructor.
        cls.__kind = 'record'
        cls.__init__.__annotations__ = _collectDataClassAttributes(cls)
        cls.__init__.__original = cls # mark class as source of annotation
        cls.__init__ = untypy.typechecked(cls.__init__)

    if mutable:
        # prevent new fields being added
        fields = set(fieldNames)

        checker = {}
        # Note: Partial annotations are disallowed by untypy.typechecked(cls.__init__)
        #       So no handling in this code is required.
        for name in fields:
            if name in cls.__annotations__:
                # This the type is wrapped in an lambda expression to allow for Forward Ref.
                # Would the lambda expression be called at this moment, it may cause an name error
                # untypy.checker fetches the annotation lazily.
                checker[name] = untypy.checker(\
                    lambda cls=cls,name=name: typing.get_type_hints(cls, include_extras=True)[name],
                    cls)

        oldSetattr = cls.__setattr__
        def _setattr(obj, k, v):
            # Note __setattr__ also gets called in the constructor.
            if k in checker:
                oldSetattr(obj, k, checker[k](v))
            elif k in fields:
                oldSetattr(obj, k, v)
            else:
                raise AttributeError(f'Unknown attribute {k} for record {cls.__name__}')
        setattr(cls, "__setattr__", _setattr)
    return cls

def record(cls=None, mutable=False):
    def wrap(cls):
        newCls = dataclasses.dataclass(cls, frozen=not mutable)
        return _patchDataClass(newCls, mutable)
    # See if we're being called as @record or @record().
    if cls is None:
        # We're called with parens.
        return wrap
    else:
        # We're called as @dataclass without parens.
        return wrap(cls)

# Tests

_die = False

def setDieOnCheckFailures(b):
    _die = b

def _dieOnCheckFailures():
    return _die

_testCount = {'total': 0, 'failing': 0}
_checksEnabled = True

def initModule(enableChecks=True, quiet=False):
    global _checksEnabled
    _checksEnabled = enableChecks
    resetTestCount()

def resetTestCount():
    global _testCount
    _testCount = {'total': 0, 'failing': 0}

def printTestResults(prefix=''):
    total = _testCount['total']
    failing = _testCount['failing']
    if total == 0:
        pass
    elif failing == 0:
        print(f'{prefix}{total} Tests, alle erfolgreich :-)')
    else:
        print(f'{prefix}{total} Tests, {failing} Fehler :-(')
    return {'total': total, 'failing': failing}

def checkEq(actual, expected):
    return check(actual, expected, structuralObjEq=False)

def check(actual, expected, structuralObjEq=True, floatEqWithDelta=True):
    if not _checksEnabled:
        return
    global _testCount
    flags = {'structuralObjEq': structuralObjEq, 'floatEqWithDelta': floatEqWithDelta}
    matches = deepEq(actual, expected, **flags)
    _testCount = {
        'total': _testCount['total'] + 1,
        'failing': _testCount['failing'] + (0 if matches else 1)
    }
    if not matches:
        stack = inspect.stack()
        caller = stack[1] if len(stack) > 1 else None
        def fmt(x):
            if type(x) == str:
                return repr(x)
            else:
                return str(x)
        msg = f"{caller.filename}:{caller.lineno}: Erwartet wird {fmt(expected)}, aber das " \
            f"Ergebnis ist {fmt(actual)}"
        if _dieOnCheckFailures():
            raise Exception(msg)
        else:
            print("FEHLER in " + msg)

def uncoveredCase():
    stack = inspect.stack()
    caller = stack[1] if len(stack) > 1 else None
    raise Exception(f"{caller.filename}, Zeile {caller.lineno}: ein Fall ist nicht abgedeckt")

#
# Deep equality
#
def _isNumber(x):
    t = type(x)
    return (t is int or t is float)

def _seqEq(seq1, seq2, flags):
    if len(seq1) != len(seq2):
        return False
    for i, x in enumerate(seq1):
        y = seq2[i]
        if not deepEq(x, y, **flags):
            return False
    return True

def _dictEq(d1, d2, flags):
    ks1 = sorted(d1.keys())
    ks2 = sorted(d2.keys())
    if ks1 != ks2: # keys should be exactly equal
        return False
    for k in ks1:
        if not deepEq(d1[k], d2[k], **flags):
            return False
    return True

def _objToDict(o):
    d = {}
    attrs = dir(o)
    useAll = False
    if hasattr(o, EQ_ATTRS_ATTR):
        useAll = True
        attrs = getattr(o, EQ_ATTRS_ATTR)
    for n in attrs:
        if not useAll and n and n[0] == '_':
            continue
        x = getattr(o, n)
        d[n] = x
    #print(d)
    return d

def _objEq(o1, o2, flags):
    return _dictEq(_objToDict(o1), _objToDict(o2), flags)

_EPSILON = 0.00001
EQ_ATTRS_ATTR = '__eqAttrs__'

def _useFloatEqWithDelta(flags):
    return flags.get('floatEqWithDelta', False)

def _useStructuralObjEq(flags):
    return flags.get('structuralObjEq', False)

# Supported flags:
# - structuralObjEq: causes objects to be compared as dictionaries. The keys are by default
#   taken from dir(obj), if obj as the attribute __eqAttrs__, then the names listed there
#   are taken. Defaults to False.
# - floatEqWithDelta: compares floats by checking whether the difference is smaller than a
#   small delta. Setting this to True loses transitivity of eq.
def deepEq(v1, v2, **flags):
    """
    Computes deep equality of v1 and v2. With structuralObjEq=False, objects are compared
    by __eq__. Otherwise, objects are compared attribute-wise, only those attributes
    returned by dir that do not start with an underscore are compared.
    """
    # print(f'deepEq: v1={v1}, v2={v2}, flags={flags}')
    if v1 == v2:
        return True
    if _isNumber(v1) and _isNumber(v2) and _useFloatEqWithDelta(flags):
        diff = v1 - v2
        if abs(diff) < _EPSILON:
            return True
        else:
            return False
    if isinstance(v1, list):
        return isinstance(v2, list) and _seqEq(v1, v2, flags)
    if isinstance(v1, tuple):
        return isinstance(v2, tuple) and _seqEq(v1, v2, flags)
    if isinstance(v1, dict):
        return isinstance(v2, dict) and _dictEq(v1, v2, flags)
    if type(v1) == str:
        return False
    if hasattr(v1, '__class__'):
        if _useStructuralObjEq(flags):
            return _objEq(v1, v2, flags)
        else:
            return False # v1 == v2 already checked
    return False

# Additional functions and aliases

import math as moduleMath

math = moduleMath


