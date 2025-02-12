import inspect
import sys
import typing
from typing import Protocol, Any, Optional, Callable, Union, TypeVar, Dict, Tuple

from untypy.error import UntypyTypeError, UntypyAttributeError, Frame, Location, ResponsibilityType
from untypy.impl.any import SelfChecker, AnyChecker
from untypy.interfaces import TypeCheckerFactory, CreationContext, TypeChecker, ExecutionContext, \
    WrappedFunctionContextProvider
from untypy.util import WrappedFunction, ArgumentExecutionContext, ReturnExecutionContext
from untypy.util.condition import FunctionCondition
from untypy.util.typehints import get_type_hints


class ProtocolFactory(TypeCheckerFactory):

    def create_from(self, annotation: Any, ctx: CreationContext) -> Optional[TypeChecker]:
        if isinstance(annotation, type) and Protocol in annotation.mro():
            return ProtocolChecker(annotation, ctx)
        elif hasattr(annotation, '__args__') and hasattr(annotation.__origin__,
                                                         '__mro__') and typing.Protocol in annotation.__origin__.__mro__:
            return ProtocolChecker(annotation, ctx)
        else:
            return None


def _find_bound_typevars(clas: type) -> (type, Dict[TypeVar, Any]):
    if not hasattr(clas, '__args__') or not hasattr(clas, '__origin__'):
        return (clas, dict())
    if not hasattr(clas.__origin__, '__parameters__'):
        return (clas, dict())

    keys = clas.__origin__.__parameters__
    values = clas.__args__

    if len(keys) != len(values):
        raise UntypyAttributeError(f"Some unbound Parameters in {clas.__name__}. "
                                   f"keys={keys} do not match values={values}.",
                                   [Location(
                                       file=inspect.getfile(clas),
                                       line_no=inspect.getsourcelines(clas)[1],
                                       line_span=len(inspect.getsourcelines(clas)[0]))])
    return (clas.__origin__, dict(zip(keys, values)))


def get_proto_members(proto: type, ctx: CreationContext) -> dict[
    str, Tuple[inspect.Signature, dict[str, TypeChecker], FunctionCondition]]:
    blacklist = ['__init__', '__class__', '__delattr__', '__dict__', '__dir__',
                 '__doc__', '__getattribute__', '__getattr__', '__init_subclass__',
                 '__new__', '__setattr__', '__subclasshook__', '__weakref__',
                 '__abstractmethods__', '__class_getitem__']

    member_dict = {}
    for [name, member] in inspect.getmembers(proto):
        if name in blacklist:
            continue

        if inspect.isfunction(member):
            member = WrappedFunction.find_original(member)
            signature = inspect.signature(member)

            is_typed = len(inspect.getfullargspec(member).annotations) != 0

            checkers = {}
            if not is_typed:
                # Use Any for any type
                for key in signature.parameters:
                    if key == 'self':
                        checkers[key] = SelfChecker()
                    else:
                        checkers[key] = AnyChecker()
                checkers['return'] = AnyChecker()
            else:
                annotations = get_type_hints(member, ctx)
                for key in signature.parameters:
                    if key == 'self':
                        checkers[key] = SelfChecker()
                    else:
                        param = signature.parameters[key]
                        if param.annotation is inspect.Parameter.empty:
                            raise ctx.wrap(UntypyAttributeError(
                                f"Missing annotation for argument '{key}' of function {member.__name__} "
                                f"in protocol {proto.__name__}\n"))

                        param_anot = annotations[key]
                        if param_anot is proto:
                            checker = SimpleInstanceOfChecker(proto, None)
                        else:
                            checker = ctx.find_checker(param_anot)
                        if checker is None:
                            raise ctx.wrap(UntypyAttributeError(f"\n\tUnsupported type annotation: {param.annotation}\n"
                                                                f"for argument '{key}' of function {member.__name__} "
                                                                f"in protocol {proto.__name__}.\n"))
                        checkers[key] = checker

                if signature.return_annotation is inspect.Parameter.empty:
                    return_annotation = None
                else:
                    return_annotation = annotations['return']
                if return_annotation is proto:  # Self as Return Type would led to endless recursion
                    return_checker = SimpleInstanceOfChecker(proto, None)
                else:
                    return_checker = ctx.find_checker(return_annotation)

                if return_checker is None:
                    raise ctx.wrap(UntypyAttributeError(f"\n\tUnsupported type annotation: {signature.return_annotation}\n"
                                                        f"for return value of function {member.__name__} "
                                                        f"in protocol-like {proto.__name__}.\n"))
                checkers['return'] = return_checker

            fc = None
            if hasattr(member, '__fc'):
                fc = getattr(member, '__fc')
            member_dict[name] = (signature, checkers, fc)
    return member_dict


class ProtocolChecker(TypeChecker):
    def __init__(self, annotation: type, ctx: CreationContext, *, altname : Optional[str] = None):
        (proto, typevars) = _find_bound_typevars(annotation)
        self.ctx = ctx.with_typevars(typevars)
        self.proto = proto
        self._members = None
        self.typevars = typevars
        self.wrapper_types = dict()
        self.altname = altname

    @property
    def members(self):
        if not self._members:
            self._members = get_proto_members(self.proto, self.ctx)
        return self._members

    def may_change_identity(self) -> bool:
        return True

    def check_and_wrap(self, arg: Any, ctx: ExecutionContext) -> Any:
        if hasattr(arg, '_ProtocolWrappedFunction__inner'):
            # no double wrapping
            arg = getattr(arg, '_ProtocolWrappedFunction__inner')

        if type(arg) in self.wrapper_types:
            return self.wrapper_types[type(arg)](arg, ctx)
        else:
            wrapped_type = ProtocolWrapper(self, arg, self.members, ctx)
            self.wrapper_types[type(arg)] = wrapped_type
            return wrapped_type(arg, ctx)

    def base_type(self) -> list[Any]:
        # Prevent Classes implementing multiple Protocols in one Union by accident.
        return [Protocol]

    def describe(self) -> str:
        if self.altname is not None:
            return self.altname

        desc = set([])
        for name in self.members:
            (sig, binds, cond) = self.members[name]
            for argname in sig.parameters:
                if isinstance(sig.parameters[argname].annotation, TypeVar):
                    desc.add(binds[argname].describe())
            if isinstance(sig.return_annotation, TypeVar):
                desc.add(binds['return'].describe())
        if len(desc) > 0:
            return f"{self.proto.__name__}[" + (', '.join(desc)) + "]"
        else:
            return f"{self.proto.__name__}"

    def protocol_type(self) -> str:
        return f"protocol"

    def protoname(self):
        return self.describe()


def ProtocolWrapper(protocolchecker: ProtocolChecker, originalValue: Any,
                    members: dict[str, Tuple[inspect.Signature, dict[str, TypeChecker], FunctionCondition]],
                    ctx: ExecutionContext):
    list_of_attr = dict()
    original = type(originalValue)
    for fnname in members:
        if not hasattr(original, fnname):
            raise ctx.wrap(UntypyTypeError(
                expected=protocolchecker.describe(),
                given=originalValue
            )).with_header(
                f"{original.__name__} does not meet the requirements of protocol {protocolchecker.proto.__name__}."
            ).with_note(f"It is missing the function '{fnname}'.")

        original_fn = getattr(original, fnname)
        try:
            # fails on built ins - YEAH
            original_fn_signature = inspect.signature(original_fn)
        except:
            original_fn_signature = None

        if hasattr(original_fn, '__wf'):
            original_fn = getattr(original_fn, '__wf')
        (sig, argdict, fc) = members[fnname]

        for param in sig.parameters:
            if original_fn_signature is not None and param not in original_fn_signature.parameters:
                raise ctx.wrap(UntypyTypeError(
                    expected=protocolchecker.describe(),
                    given=originalValue
                )).with_header(
                    f"{original.__name__} does not meet the requirements of protocol {protocolchecker.proto.__name__}."
                 ).with_note(f"The signature of '{fnname}' does not match. Missing required parameter {param}.")

        list_of_attr[fnname] = ProtocolWrappedFunction(original_fn, sig, argdict, protocolchecker, fc).build()

    def constructor(me, inner, ctx):
        me._ProtocolWrappedFunction__inner = inner
        me._ProtocolWrappedFunction__ctx = ctx

    def __getattr__(me, name):
        return getattr(me._ProtocolWrappedFunction__inner, name)

    def __setattr__(me, name, value):
        if name == '_ProtocolWrappedFunction__inner':
            super(type(me), me).__setattr__('_ProtocolWrappedFunction__inner', value)
            return
        if name == '_ProtocolWrappedFunction__ctx':
            super(type(me), me).__setattr__('_ProtocolWrappedFunction__ctx', value)
            return

        return setattr(me._ProtocolWrappedFunction__inner, name, value)

    list_of_attr['__init__'] = constructor
    list_of_attr['__getattr__'] = __getattr__  # allow access of attributes
    list_of_attr['__setattr__'] = __setattr__  # allow access of attributes
    name = f"{protocolchecker.proto.__name__}For{original.__name__}"
    return type(name, (), list_of_attr)


class ProtocolWrappedFunction(WrappedFunction):

    def __init__(self, inner: Union[Callable, WrappedFunction], signature: inspect.Signature,
                 checker: Dict[str, TypeChecker],
                 protocol: ProtocolChecker,
                 fc: FunctionCondition):
        self.inner = inner
        self.signature = signature
        self.checker = checker
        self.protocol = protocol
        self.fc = fc

    def build(self):
        fn = WrappedFunction.find_original(self.inner)

        fn_of_protocol = getattr(self.protocol.proto, fn.__name__)
        if hasattr(fn_of_protocol, '__wf'):
            fn_of_protocol = getattr(fn_of_protocol, '__wf')

        def wrapper(me, *args, **kwargs):
            inner_object = me.__inner
            inner_ctx = me.__ctx

            caller = sys._getframe(1)
            (args, kwargs, bind1) = self.wrap_arguments(lambda n: ArgumentExecutionContext(fn_of_protocol, caller, n),
                                                        (inner_object, *args), kwargs)
            if isinstance(self.inner, WrappedFunction):
                (args, kwargs, bind2) = self.inner.wrap_arguments(lambda n:
                                                                  ProtocolArgumentExecutionContext(self, n,
                                                                                                   inner_object,
                                                                                                   inner_ctx),
                                                                  args, kwargs)
            ret = fn(*args, **kwargs)
            if isinstance(self.inner, WrappedFunction):
                ret = self.inner.wrap_return(ret, bind2, ProtocolReturnExecutionContext(self,
                                                                                        ResponsibilityType.IN,
                                                                                        inner_object,
                                                                                        inner_ctx))
            return self.wrap_return(ret, bind1, ProtocolReturnExecutionContext(self,
                                                                               ResponsibilityType.OUT, inner_object,
                                                                               inner_ctx))

        async def async_wrapper(*args, **kwargs):
            raise AssertionError("Not correctly implemented see wrapper")

        if inspect.iscoroutine(self.inner):
            w = async_wrapper
        else:
            w = wrapper

        setattr(w, '__wrapped__', fn)
        setattr(w, '__name__', fn.__name__)
        setattr(w, '__signature__', self.signature)
        setattr(w, '__wf', self)
        return w

    def get_original(self):
        return self.inner

    def wrap_arguments(self, ctxprv: WrappedFunctionContextProvider, args, kwargs):
        try:
            bindings = self.signature.bind(*args, **kwargs)
        except TypeError as e:
            err = UntypyTypeError(header=str(e))
            if "self" not in self.signature.parameters:
                err = err.with_note("Hint: 'self'-parameter was omitted in declaration.")
            raise ctxprv("").wrap(err)

        bindings.apply_defaults()
        if self.fc is not None:
            self.fc.prehook(bindings, ctxprv)
        for name in bindings.arguments:
            check = self.checker[name]
            ctx = ctxprv(name)
            bindings.arguments[name] = check.check_and_wrap(bindings.arguments[name], ctx)
        return bindings.args, bindings.kwargs, bindings

    def wrap_return(self, ret, bindings, ctx: ExecutionContext):
        check = self.checker['return']
        if self.fc is not None:
            self.fc.posthook(ret, bindings, ctx)
        return check.check_and_wrap(ret, ctx)

    def describe(self) -> str:
        fn = WrappedFunction.find_original(self.inner)
        return f"{fn.__name__}" + str(self.signature)

    def checker_for(self, name: str) -> TypeChecker:
        return self.checker[name]

    def declared(self) -> Location:
        fn = WrappedFunction.find_original(self.inner)
        return WrappedFunction.find_location(getattr(self.protocol.proto, fn.__name__))


class ProtocolReturnExecutionContext(ExecutionContext):
    def __init__(self, wf: ProtocolWrappedFunction, invert: ResponsibilityType, me: Any, ctx: ExecutionContext):
        self.wf = wf
        self.invert = invert
        self.me = me
        self.ctx = ctx

    def wrap(self, err: UntypyTypeError) -> UntypyTypeError:
        err = ReturnExecutionContext(self.wf).wrap(err)

        if err.responsibility_type is self.invert:
            return err

        responsable = WrappedFunction.find_location(self.wf)
        (decl, ind) = err.next_type_and_indicator()
        err = err.with_inverted_responsibility_type()
        err = err.with_frame(Frame(
            decl,
            ind,
            declared=self.wf.declared(),
            responsable=responsable
        ))

        inner = self.wf.inner
        if isinstance(inner, WrappedFunction):
            err = err.with_note(
                f"The return value of method '{WrappedFunction.find_original(self.wf).__name__}' does violate the {self.wf.protocol.protocol_type()} '{self.wf.protocol.proto.__name__}'.")
            err = err.with_note(
                f"The annotation '{inner.checker_for('return').describe()}' is incompatible with the {self.wf.protocol.protocol_type()}'s annotation '{self.wf.checker_for('return').describe()}'\nwhen checking against the following value:")

        previous_chain = UntypyTypeError(
            self.me,
            f"{self.wf.protocol.protoname()}"
        ).with_header(
            f"{type(self.me).__name__} does not implement {self.wf.protocol.protocol_type()} {self.wf.protocol.protoname()} correctly.")

        previous_chain = self.ctx.wrap(previous_chain)
        return err.with_previous_chain(previous_chain)


class ProtocolArgumentExecutionContext(ExecutionContext):
    def __init__(self, wf: ProtocolWrappedFunction, arg_name: str, me: Any, ctx: ExecutionContext):
        self.wf = wf
        self.arg_name = arg_name
        self.me = me
        self.ctx = ctx

    def wrap(self, err: UntypyTypeError) -> UntypyTypeError:
        (original_expected, _ind) = err.next_type_and_indicator()
        err = ArgumentExecutionContext(self.wf, None, self.arg_name).wrap(err)

        responsable = WrappedFunction.find_location(self.wf)

        (decl, ind) = err.next_type_and_indicator()
        err = err.with_frame(Frame(
            decl,
            ind,
            declared=self.wf.declared(),
            responsable=responsable
        ))

        err = err.with_note(
            f"Argument {self.arg_name} of method {WrappedFunction.find_original(self.wf).__name__} violates the type declared by the {self.wf.protocol.protocol_type()} {self.wf.protocol.proto.__name__}.")
        err = err.with_note(
            f"Annotation {original_expected} is incompatible with the {self.wf.protocol.protocol_type()}'s annotation {self.wf.checker_for(self.arg_name).describe()}.")

        previous_chain = UntypyTypeError(
            self.me,
            f"{self.wf.protocol.protoname()}"
        ).with_header(
            f"{type(self.me).__name__} does not implement {self.wf.protocol.protocol_type()} {self.wf.protocol.protoname()} correctly.")

        previous_chain = self.ctx.wrap(previous_chain)
        # err = err.with_inverted_responsibility_type()

        return err.with_previous_chain(previous_chain)


class SimpleInstanceOfChecker(TypeChecker):
    def __init__(self, annotation: type, ctx: CreationContext):
        self.annotation = annotation

    def check_and_wrap(self, arg: Any, ctx: ExecutionContext) -> Any:
        if isinstance(arg, self.annotation):
            return arg
        else:
            raise ctx.wrap(UntypyTypeError(arg, self.describe()))

    def describe(self) -> str:
        return self.annotation.__name__

    def base_type(self) -> Any:
        return [self.annotation]
