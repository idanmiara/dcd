import copy
from dataclasses import is_dataclass
from itertools import zip_longest
from typing import TypeVar, Type, Optional, Mapping, Any

from dacite.config import Config
from dacite.data import Data, DictData
from dacite.dataclasses import get_default_value_for_field, create_instance, DefaultValueNotFoundError, get_fields
from dacite.exceptions import (
    ForwardReferenceError,
    WrongTypeError,
    DaciteError,
    UnionMatchError,
    MissingValueError,
    DaciteFieldError,
    UnexpectedDataError,
    StrictUnionMatchError,
)
from dacite.types import (
    is_instance,
    is_generic_collection,
    is_union,
    extract_generic,
    is_optional,
    transform_value,
    extract_origin_collection,
    is_init_var,
    extract_init_var,
    is_set,
    get_data_class_hints,
)

T = TypeVar("T")


def from_dict(data_class: Type[T], data: Data, config: Optional[Config] = None) -> T:
    """Create a data class instance from a dictionary.

    :param data_class: a data class type
    :param data: a dictionary of a input data
    :param config: a configuration of the creation process
    :return: an instance of a data class
    """
    init_values: DictData = {}
    post_init_values: DictData = {}
    config = config or Config()
    try:
        data_class_hints = get_data_class_hints(data_class, globalns=config.forward_references)
    except NameError as error:
        raise ForwardReferenceError(str(error))
    data_class_fields = get_fields(data_class)
    if config.strict:
        extra_fields = set(data.keys()) - {f.name for f in data_class_fields}
        if extra_fields:
            raise UnexpectedDataError(keys=extra_fields)
    for field in data_class_fields:
        field = copy.copy(field)
        field.type = data_class_hints[field.name]
        if field.name in data:
            try:
                field_data = data[field.name]
                transformed_value = transform_value(
                    type_hooks=config.type_hooks, cast=config.cast, target_type=field.type, value=field_data
                )
                value = _build_value(type_=field.type, data=transformed_value, config=config)
            except DaciteFieldError as error:
                error.update_path(field.name)
                raise
            if config.check_types and not is_instance(value, field.type):
                raise WrongTypeError(field_path=field.name, field_type=field.type, value=value)
        elif not field.init:
            # If the non-init field isn't in the dict, let the dataclass handle default, to ensure
            # we won't get errors in the case of frozen dataclasses, as issue #195 highlights.
            continue
        else:
            try:
                value = get_default_value_for_field(
                    field, allow_missing_fields_as_none=config.allow_missing_fields_as_none
                )
            except DefaultValueNotFoundError:
                raise MissingValueError(field.name)
        if field.init:
            init_values[field.name] = value
        else:
            post_init_values[field.name] = value

    return create_instance(data_class=data_class, init_values=init_values, post_init_values=post_init_values)


def _build_value(type_: Type, data: Any, config: Config) -> Any:
    if is_init_var(type_):
        type_ = extract_init_var(type_)
    if is_union(type_):
        return _build_value_for_union(union=type_, data=data, config=config)
    elif is_generic_collection(type_):
        origin = extract_origin_collection(type_)
        if is_instance(data, origin):
            return _build_value_for_collection(collection=type_, data=data, config=config)
        if is_set(origin):
            return origin(
                _build_value(type_=extract_generic(type_)[0], data=single_val, config=config) for single_val in data
            )
    elif is_dataclass(type_) and is_instance(data, Data):
        if hasattr(type_, "from_dict"):
            return type_.from_dict(data=data, config=config)
        return from_dict(data_class=type_, data=data, config=config)
    return data


def _build_value_for_union(union: Type, data: Any, config: Config) -> Any:
    types = extract_generic(union)
    if is_optional(union) and len(types) == 2:
        return _build_value(type_=types[0], data=data, config=config)
    union_matches = {}
    for inner_type in types:
        try:
            # noinspection PyBroadException
            try:
                data = transform_value(
                    type_hooks=config.type_hooks, cast=config.cast, target_type=inner_type, value=data
                )
            except Exception:  # pylint: disable=broad-except
                continue
            value = _build_value(type_=inner_type, data=data, config=config)
            if is_instance(value, inner_type):
                if config.strict_unions_match:
                    union_matches[inner_type] = value
                else:
                    return value
        except DaciteError:
            pass
    if config.strict_unions_match:
        if len(union_matches) > 1:
            raise StrictUnionMatchError(union_matches)
        return union_matches.popitem()[1]
    if not config.check_types:
        return data
    raise UnionMatchError(field_type=union, value=data)


def _build_value_for_collection(collection: Type, data: Any, config: Config) -> Any:
    data_type = data.__class__
    if is_instance(data, Mapping):
        item_type = extract_generic(collection, defaults=(Any, Any))[1]
        return data_type((key, _build_value(type_=item_type, data=value, config=config)) for key, value in data.items())
    elif is_instance(data, tuple):
        if not data:
            return data_type()
        types = extract_generic(collection)
        if len(types) == 2 and types[1] == Ellipsis:
            return data_type(_build_value(type_=types[0], data=item, config=config) for item in data)
        return data_type(
            _build_value(type_=type_, data=item, config=config) for item, type_ in zip_longest(data, types)
        )
    item_type = extract_generic(collection, defaults=(Any,))[0]
    return data_type(_build_value(type_=item_type, data=item, config=config) for item in data)
