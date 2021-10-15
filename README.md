[![Python CI](https://github.com/skogsbaer/write-your-python-program/actions/workflows/github-action-test-python.yml/badge.svg)](https://github.com/skogsbaer/write-your-python-program/actions/workflows/github-action-test-python.yml)
[![Node.js CI](https://github.com/skogsbaer/write-your-python-program/actions/workflows/github-action-test-js.yml/badge.svg)](https://github.com/skogsbaer/write-your-python-program/actions/workflows/github-action-test-js.yml)

# Write Your Python Program

A user-friendly python programming environment for beginners.

The ideas of this environment are based on the great ideas from
[Schreib dein Programm!](https://www.deinprogramm.de/sdp/).

## Quick start

* Step 1. Install **Python 3.9.x.**
* Step 2. Install the **write-your-python-program** extension. You need at least Visual Studio Code
  version 1.49.0.
* Step 3. Open or create a Python file. The "RUN" button in the taskbar at the bottom will
  run your file with the teaching language provided by write-your-python-program.

### Troubleshooting

- By default, the Visual Studio Code extension uses the Python interpreter of the regular
  Python extension. If
  this is not Python version 3.9.x, you have to configure it explicitly. Configuration
  can be done either by selecting the desired Python version in the left corner of the status
  bar (at the bottom of the window), or by setting the path the the python
  executable in the settings of the plugin.
- The extension disables linting of Python code when activated. This is well-suited for beginners
  but might cause unwanted effects when you rely on linting. In such cases, you have to
  deactivate the extension.

### Usage without Visual Studio Code

Write Your Python Program can be installed outside of Visual Studio Code via pip:

```default
pip3 install wypp
```

This needs Python 3.9.x. After installation, you can use the `wypp` command
for running your python files, making all features explained below available.
Run `wypp --help` for usage information.

## What's new?

Here is the [Changelog](ChangeLog.md).

* **Breaking change** in version 0.12.0 (2021-09-28): type annotations are now checked
  dynamically when the code is executed.
  This behavior can be deactivated in the settings of the extension.
* **Breaking change** in version 0.11.0 (2021-03-11): wypp is no longer automatically imported.
You need an explicit import statement such as `from wypp import *`.

## Features

Here is a screen shot:

![Screenshot](screenshot.jpg)

When hitting the RUN button, the vscode extension saves the current file, opens
a terminal and executes the file with Python, staying in interactive mode after
all definitions have been executed.

The file being executed should contain the following import statement in the first line:

~~~python
from wypp import*
~~~

Running the file with the RUN button makes the following features available:

### Type Definitions

You can define enums, records and union data types and the use them with the
[type hints](https://www.python.org/dev/peps/pep-0484/) of
Python 3. Type hints are checked for correctness dynamically, i.e. violations
are detected only at the moment when a function is applied to an argument not matching
its type hint or when a function returns a value not matching the return type hint.
(This approach is similar to
[contract checking in racket](https://users.cs.northwestern.edu/~robby/pubs/papers/ho-contracts-icfp2002.pdf))


#### Enums

~~~python
Color = Literal['red', 'green', 'blue']
~~~

#### Records

~~~python
@record
class Point:
    x: float
    y: float

@record
class Square:
    center: Point
    width: float

@record
class Circle:
    center: Point
    radius: float
~~~

You work with a record like this:

~~~python
p = Point(2, 3) # point at x=2, y=3
print(p.x)      # Prints 2
~~~

Fields of records are immutable by default. You get mutable fields with `@record(mutable=True)`.

#### Mixed Data Types

~~~python
PrimitiveShape = Union[Circle, Square]
~~~

To use recursive types, you need to write a forward reference to the yet undefined type
as a string:

~~~python
Shape = Union[Circle, Square, 'Overlay']

@record
class Overlay:
    top: Shape
    bottom: Shape
~~~

Case distinction works like this:

~~~python
def workOnShape(s: Shape) -> None:
    if isinstance(s, Square):
        # s is a Square, do something with it
        pass
    elif isinstance(s, Circle):
        # s is a Circle, do something with it
        pass
    elif isinstance(s, Overlay):
        # s is an Overlay, do something with it
        pass
~~~

The body of `workOnShape` can safely assume that `s` is indeed one `Square`, `Circle`, or
`Overlay` because the type hint `Shape` for argument `s` is checked dynamically. Here is
what happens if you apply `workOnShape` to, say, a string, that is `workOnShape('foo')`.

~~~default
Traceback (most recent call last):
  File "test.py", line 42, in <module>
    workOnShape("foo")
WyppTypeError: got value of wrong type
given:    'foo'
expected: value of type Union[Circle, Square, Overlay]

context: workOnShape(s: Union[Circle, Square, Overlay]) -> None
                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
declared at: test.py:31
caused by: test.py:42
  | workOnShape("foo")
~~~

### Tests

Tests are defined via `check`. The first argument of check is the actual result,
then second argument the expected result.

~~~python
check(factorial(4), 24)
~~~

## Annotations

All python types (builtin or from the `typing` module) can be used as annotations.
Also, you can use every class as a type. In addition, WYPP comes with the following
predefined types:

* `floatNegative`
* `floatNonNegative`
* `floatNonPositive`
* `floatPositive`
* `intNegative`
* `intNonNegative`
* `intNonPositive`
* `intPositive`
* `nat`

The code is run with `from __future__ import annotations`
(see [PEP 563](https://www.python.org/dev/peps/pep-0563/)), which will be
the default from python 3.10 on. This means that you can use a type as an annotation
before the type being defined, for example to define recursive types or as
the type of `self` inside of classes. In fact, there is no check at all to make sure
that anotations refer to existing types.

## Module name and current working directory

When executing a python file with the RUN button, the current working directory is set to
the directory of the file being executed. The `__name__` attribute is set to the value
`'__wypp__'`.

## Bugs & Problems

Please report them in the [issue tracker](https://github.com/skogsbaer/write-your-python-program/issues).

## Hacking

You can debug the extension from Visual Studio Code:

* Open the main folder of the plugin with vscode.
* Open the file `extension.ts`.
* Choose "Run" from the menu, then "Start Debugging".
