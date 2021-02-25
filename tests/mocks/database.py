import sys
import collections
import datetime
from functools import wraps
from dataclasses import dataclass

import unittest.mock


from typing import Optional, List, Union, get_origin, get_args


#from bot.cogs.utils import db
from asyncpg.protocol.protocol import _create_record as Record

"""

def MockDatabase():
    database = db.Database(MockPool())

    tables = [table for table in vars(database).values() if isinstance(table, db.Table)]
    for table in tables:
        for attr in dir(table):
            if attr.startswith('_'):
                continue

            if attr in ['prepare', 'prepare_one', 'prepare_from_message']:
                continue

            setattr(table, attr, unittest.mock.AsyncMock())

    return database
"""

class Field:
    __slots__ = ('name', 'type', 'default')

    def __init__(self, default):
        self.name = None
        self.type = None
        self.default = default

    def __repr__(self):
        return ('Field('
                f'name={self.name!r},'
                f'type={self.type!r},'
                f'default={self.default!r}'
                ')')

def record(cls=None, /, *, new=True):
    """
    @record decorator
    this decorator generates a new __new__ function that
    returns a valid Record instance with the fields
    specified in the decorated class

    This decorator has been inspired by the
    @dataclass decorator
    """

    def wrap(cls):
        return _process_class(cls, new)

    if cls is None:
        # We're called with parens.
        return wrap

    # We're called as @record without parens.
    return wrap(cls)


def _process_class(cls, new):
    if cls.__module__ in sys.modules:
        globals = sys.modules[cls.__module__].__dict__
    else:
        globals = {}

    # Annotated fields defined in this class will be used
    # to generate internal functions
    cls_annotations = cls.__dict__.get('__annotations__', {})

    # Now find fields in our class.  While doing so, validate some
    # things, and set the default values (as class attributes) where
    # we can.
    cls_fields = [_get_field(cls, name, type)
                  for name, type in cls_annotations.items()]

    if new:
        # The name to use for the "cls"
        # param in __new__.  Use "cls"
        # if possible.
        cls_name = '__dataclass_cls__' if 'cls' in cls_fields else 'cls'

        # create __new__ function that returns a record
        setattr(cls, '__new__', _new_fn(cls_name, cls_fields, globals=globals))

    return cls

def _get_field(cls, a_name, a_type):
    default = getattr(cls, a_name, None)
    if isinstance(default, Field):
        field = default
    else:
        field = Field(default)

    field.name = a_name
    field.type = a_type

    return field

def _new_fn(cls_name, fields, *, globals=None):
    """
    create a __new__ function that has cls as first arguemnt
    and fields as required-keyword arguments
    return a Record instance from asyncpg module
    """

    body_lines = []

    body_lines.append("mapping = collections.OrderedDict({" + ", ".join(f"'{f.name}': {i}" for i, f in enumerate(fields)) + "})")
    body_lines.append('elems = (' + ", ".join(f.name for f in fields) + ')')
    body_lines.append("return Record(mapping, elems)")

    return _create_fn('__new__', cls_name, fields, body_lines, globals=globals)


def _create_fn(name, cls_name, fields, body_lines, *, return_type=None, globals=None):

    if not body_lines:
        body_lines = ["pass"]

    args = ', '.join(f"{field.name}: {f_type(field)}" for field in fields)
    body = '\n'.join(f'  {b}' for b in body_lines)

    txt = f'def {name}({cls_name}, {args}) -> {return_type}:\n{body}'

    if 'typing' not in globals:
        globals['typing'] = sys.modules.get('typing')

    ns = {}
    exec(txt, globals, ns)
    return ns[name]


def f_type(field):
    if field.type.__module__ == 'typing':
        return field.type
    else:
        return field.type.__qualname__


def _is_classvar(a_type, typing):
    # This test uses a typing internal class, but it's the best way to
    # test if this is a ClassVar.
    return (a_type is typing.ClassVar
            or (type(a_type) is typing._GenericAlias
                and a_type.__origin__ is typing.ClassVar))



class MockPool(unittest.mock.MagicMock):
    pass


@record
@dataclass
class MockLeaderboardRecord:
    row_number: int
    author_id: int
    author: str
    sent_total: int


@record
@dataclass
class MockSubjectRecord:
    faculty: str
    code: str
    name: str
    url: str
    terms: List[str]
    created_at: datetime.datetime
    edited_at: Optional[datetime.datetime] = None
    deleted_at: Optional[datetime.datetime] = None


@record
@dataclass
class MockSubjectRegisteredRecord:
    faculty: str
    code: str
    guild_id: int
    member_ids: List[int]


@record
@dataclass
class MockSubjectServerRecord:
    faculty: str
    code: str
    guild_id: int
    category_id: Optional[int]
    channel_id: int
    voice_channel_id: Optional[int]
